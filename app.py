import io
import os

import pandas as pd
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = os.environ.get("ECOVAULT_API_URL", "http://158.101.172.136:8000")
API_KEY  = os.environ.get("ECOVAULT_API_KEY", "A6MmAE31wO_NRSQf9GlvvvxuTtXs4pDH2X54BsgP5ps")
HEADERS  = {"X-API-Key": API_KEY}
MAX_SPECIES = 100
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

TRAIT_COLUMNS = {
    "species":        "Species",
    "ssd_avg":        "SSD avg",           "ssd_sd":       "SSD SD",           "ssd_n":       "SSD #",
    "leaf_n_avg":     "Leaf Nitrogen avg", "leaf_n_sd":    "Leaf Nitrogen SD", "leaf_n_n":    "Leaf Nitrogen #",
    "seed_mass_avg":  "Seed Mass avg",     "seed_mass_sd": "Seed Mass SD",     "seed_mass_n": "Seed Mass #",
    "ldmc_avg":       "LDMC avg",          "ldmc_sd":      "LDMC SD",          "ldmc_n":      "LDMC #",
    "height_avg":     "Height avg",        "height_sd":    "Height SD",        "height_n":    "Height #",
    "leaf_area_avg":  "Leaf Area avg",     "leaf_area_sd": "Leaf Area SD",     "leaf_area_n": "Leaf Area #",
    "sla_avg":        "SLA avg",           "sla_sd":       "SLA SD",           "sla_n":       "SLA #",
}
TAXONOMY_COLUMNS = ["Genus", "Family", "Order", "Class", "Phylum", "Kingdom"]   # low -> high rank


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_names(raw: str) -> list[str]:
    """Comma- or newline-separated input -> unique, trimmed names, order kept."""
    seen: set[str] = set()
    out = []
    for n in raw.replace("\n", ",").split(","):
        n = n.strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def call_api(path: str, names: list[str]) -> dict | None:
    try:
        resp = requests.post(f"{API_BASE}{path}", headers=HEADERS,
                             json={"species": names}, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        return None


def validate_names(names: list[str]) -> bool:
    if not names:
        st.warning("Please enter at least one species name.")
        return False
    if len(names) > MAX_SPECIES:
        st.error(f"Maximum {MAX_SPECIES} species per request. You entered {len(names)}.")
        return False
    return True


SOURCE_ORDER = ["CoL", "ITIS", "GBIF", "WFO"]


def taxonomy_to_frame(results: list[dict]) -> pd.DataFrame:
    """
    One row per candidate accepted name. A clean input gives one row; a homonym,
    synonym or disputed name gives one row per candidate, best-supported first.
    'Scientific Name' is the accepted name with author and is blank for genus-level
    results. 'Synonym' holds the name you typed (with author) when it is a synonym
    of the accepted name. 'Accepted name' (no author) is what goes to the Traits tab.
    """
    def row(input_name, spelling, t, use):
        accepted = t.get("accepted_name") or ""
        is_species = len(accepted.split()) >= 2
        synonym = t.get("scientific_name") if (t.get("is_synonym") and is_species) else ""
        sources = sorted(t.get("sources", []), key=lambda s: SOURCE_ORDER.index(s) if s in SOURCE_ORDER else 99)
        return {
            "Use":             use and is_species,
            "Input":           input_name,
            "Scientific Name": (t.get("accepted_scientific_name") or accepted) if is_species else "",
            "Spelling":        spelling,
            "Synonym":         synonym or "",
            "Sources":         ", ".join(sources),
            "Genus":           t.get("genus"),
            "Family":          t.get("family"),
            "Order":           t.get("order"),
            "Class":           t.get("class_name"),
            "Phylum":          t.get("phylum"),
            "Kingdom":         t.get("kingdom"),
            "Accepted name":   accepted if is_species else "",
        }

    rows = []
    for r in results:
        if r["match_type"] == "NoMatch" or not r.get("best"):
            rows.append(row(r["input_name"], "No match", {}, False))
            continue
        spelling = "Correct" if r["match_type"] == "Exact" else "Fuzzy"
        rows.append(row(r["input_name"], spelling, r["best"], True))
        for alt in r.get("alternatives", []):
            rows.append(row(r["input_name"], spelling, alt, False))

    return pd.DataFrame(rows)


def input_status(group: pd.DataFrame) -> str:
    """Exact = one row, spelling correct, no synonym, species-level; else Review / No match."""
    if (group["Spelling"] == "No match").all():
        return "No match"
    if (len(group) == 1
            and group["Spelling"].iloc[0] == "Correct"
            and group["Synonym"].iloc[0] == ""
            and group["Scientific Name"].iloc[0] != ""):
        return "Exact"
    return "Review"


def excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()


# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="EcoHelper — Plant Data", layout="wide")
st.title("🌿 EcoHelper — Plant Data")

st.session_state.setdefault("taxonomy_df", None)
st.session_state.setdefault("trait_input", "")

tab_names, tab_traits = st.tabs(["1 · Check names", "2 · Traits"])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — Taxonomy
# ══════════════════════════════════════════════════════════════════════════════
with tab_names:
    st.caption(
        "Validate species names against Catalogue of Life, ITIS, GBIF and World Flora Online. "
        "A clean name gives one row; a synonym, homonym or disputed name gives one row per candidate — "
        "tick **Use** on the one you want."
    )

    tax_raw = st.text_area(
        "Species names (comma- or newline-separated)",
        placeholder="festuca rubra, Carex nigra, Agrostis tenuis",
        height=100,
        key="tax_raw",
    )

    if st.button("Check names", type="primary", key="btn_check"):
        names = parse_names(tax_raw)
        if validate_names(names):
            with st.spinner(f"Checking {len(names)} names…"):
                data = call_api("/taxonomy/batch", names)
            if data is not None:
                st.session_state.taxonomy_df = taxonomy_to_frame(data["results"])
                st.session_state.pop("tax_editor", None)   # discard edits from a previous run

    df = st.session_state.taxonomy_df
    if df is not None:
        status = df.groupby("Input", sort=False).apply(input_status, include_groups=False)
        n_exact  = (status == "Exact").sum()
        n_review = (status == "Review").sum()
        n_none   = (status == "No match").sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Exact", n_exact)
        c2.metric("Review", n_review)
        c3.metric("No match", n_none)

        if n_review:
            st.info(
                f"{n_review} name(s) need a look: a corrected spelling, a synonym, a homonym "
                "(same name published by different authors for different species), or a genus-level name. "
                "The best-supported candidate is pre-ticked in **Use**; change the tick if you disagree."
            )

        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            column_order=[c for c in df.columns if c != "Accepted name"],
            disabled=[c for c in df.columns if c != "Use"],
            column_config={
                "Use":             st.column_config.CheckboxColumn(help="Tick the candidate to send to the Traits tab"),
                "Scientific Name": st.column_config.TextColumn(help="Accepted name with author; blank for genus-level results"),
                "Spelling":        st.column_config.TextColumn(help="Correct = your input exists verbatim; Fuzzy = a typo was corrected"),
                "Synonym":         st.column_config.TextColumn(help="The name you typed, when it is a synonym of the accepted name"),
            },
            key="tax_editor",
        )
        st.session_state.taxonomy_df = edited

        names_clean = edited["Accepted name"].fillna("").str.strip()
        accepted = list(dict.fromkeys(n for n in names_clean[edited["Use"].fillna(False).astype(bool)] if n))
        has_species = (names_clean != "").groupby(edited["Input"], sort=False).any()
        unmatched = has_species[~has_species].index.tolist()

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button(f"Send {len(accepted)} names to Traits →", disabled=not accepted, key="btn_send"):
                st.session_state.trait_input = ", ".join(accepted)
                st.success("Names sent. Open the **2 · Traits** tab and press *Fetch traits*.")
        with b2:
            st.download_button(
                "⬇️ Download taxonomy (Excel)",
                data=excel_bytes({
                    "Taxonomy":  edited,
                    "Unmatched": pd.DataFrame({"Input": unmatched}),
                }),
                file_name="ecohelper_taxonomy.xlsx",
                mime=XLSX_MIME,
                key="dl_tax",
            )


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Traits
# ══════════════════════════════════════════════════════════════════════════════
with tab_traits:
    st.caption("Retrieve aggregated trait values from TRY. Names checked in tab 1 are pre-filled here.")

    trait_raw = st.text_area(
        "Species names (comma- or newline-separated)",
        placeholder="Festuca rubra, Carex nigra, Molinia caerulea",
        height=100,
        key="trait_input",
    )

    if st.button("Fetch traits", type="primary", key="btn_traits"):
        names = parse_names(trait_raw)
        if validate_names(names):
            with st.spinner(f"Fetching traits for {len(names)} species…"):
                data = call_api("/species/batch", names)
            if data is not None:
                found   = pd.DataFrame(data["found"]) if data["found"] else pd.DataFrame()
                missing = data["missing"]

                c1, c2 = st.columns(2)
                c1.metric("Species found",   len(found))
                c2.metric("Species missing", len(missing))
                if missing:
                    st.warning("Not found in trait database: " + ", ".join(f"*{m}*" for m in missing))

                if not found.empty:
                    found = found.rename(columns=TRAIT_COLUMNS)
                    traits = found.drop(columns=["references"], errors="ignore")

                    # Attach taxonomy if these names came through tab 1
                    tax = st.session_state.taxonomy_df
                    if tax is not None:
                        tax_cols = (tax[tax["Use"].fillna(False).astype(bool)]
                                    [["Accepted name"] + TAXONOMY_COLUMNS]
                                    .drop_duplicates("Accepted name"))
                        traits = traits.merge(tax_cols, left_on="Species", right_on="Accepted name", how="left") \
                                       .drop(columns="Accepted name")
                        traits = traits[["Species"] + TAXONOMY_COLUMNS +
                                        [c for c in traits.columns if c not in ["Species"] + TAXONOMY_COLUMNS]]

                    st.dataframe(traits, use_container_width=True)

                    refs = (
                        found[["Species", "references"]]
                        .explode("references")
                        .rename(columns={"references": "Reference"})
                        .dropna(subset=["Reference"])
                    ) if "references" in found.columns else pd.DataFrame()

                    st.download_button(
                        "⬇️ Download traits (Excel)",
                        data=excel_bytes({
                            "Traits":     traits,
                            "Missing":    pd.DataFrame({"Species": missing}),
                            "References": refs,
                        }),
                        file_name="ecohelper_traits.xlsx",
                        mime=XLSX_MIME,
                        key="dl_traits",
                    )
