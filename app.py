import streamlit as st
import requests
import pandas as pd
import io

# ── Config ────────────────────────────────────────────────────────────────────
API_URL  = "http://158.101.172.136:8000/species/batch"
API_KEY  = "A6MmAE31wO_NRSQf9GlvvvxuTtXs4pDH2X54BsgP5ps"
HEADERS  = {"X-API-Key": API_KEY}
MAX_SPECIES = 100

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="EcoVault Trait Explorer", layout="wide")
st.title("🌿 EcoHelper — Plant Data")
st.caption("Enter species names to retrieve aggregated trait values from TRY.")

# ── Input ─────────────────────────────────────────────────────────────────────
raw_input = st.text_area(
    "Species names (comma-separated)",
    placeholder="Festuca rubra, Carex nigra, Molinia caerulea",
    height=100,
)

run = st.button("Fetch Traits", type="primary")

# ── Logic ─────────────────────────────────────────────────────────────────────
if run:
    # Parse input
    names = [n.strip() for n in raw_input.split(",") if n.strip()]

    if not names:
        st.warning("Please enter at least one species name.")
        st.stop()

    if len(names) > MAX_SPECIES:
        st.error(f"Maximum {MAX_SPECIES} species per request. You entered {len(names)}.")
        st.stop()

    # Call API
    with st.spinner(f"Fetching traits for {len(names)} species…"):
        try:
            resp = requests.post(API_URL, headers=HEADERS, json={"species": names}, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            st.error(f"API request failed: {e}")
            st.stop()

    data = resp.json()
    found   = pd.DataFrame(data["found"])   if data["found"]   else pd.DataFrame()
    missing = data["missing"]

    # ── Results ───────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    col1.metric("Species found",   len(found))
    col2.metric("Species missing", len(missing))

    if missing:
        st.warning("Not found in trait database: " + ", ".join(f"*{m}*" for m in missing))

    if not found.empty:
        # Rename columns for readability
        found = found.rename(columns={
            "species":        "Species",
            "ssd_avg":        "SSD avg",   "ssd_sd":   "SSD SD",   "ssd_n":   "SSD #",
            "leaf_n_avg":     "Leaf Nitrogen avg","leaf_n_sd":"Leaf Nitrogen SD","leaf_n_n": "Leaf Nitrogen #",
            "seed_mass_avg":  "Seed Mass avg","seed_mass_sd":"Seed Mass SD","seed_mass_n":"Seed Mass #",
            "ldmc_avg":       "LDMC avg",  "ldmc_sd":  "LDMC SD",  "ldmc_n":  "LDMC #",
            "height_avg":     "Height avg","height_sd":"Height SD","height_n": "Height #",
            "leaf_area_avg":  "Leaf Area avg","leaf_area_sd":"Leaf Area SD","leaf_area_n":"Leaf Area #",
            "sla_avg":        "SLA avg",   "sla_sd":   "SLA SD",   "sla_n":   "SLA #",
        })

        st.dataframe(found.drop(columns=["references"], errors="ignore"), use_container_width=True)

        # ── Excel export ──────────────────────────────────────────────────────
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            # Sheet 1: trait data
            found.drop(columns=["references"], errors="ignore").to_excel(
                writer, sheet_name="Traits", index=False
            )
            # Sheet 2: missing species
            if missing:
                pd.DataFrame({"Species not found": missing}).to_excel(
                    writer, sheet_name="Missing", index=False
                )
            # Sheet 3: references (flattened)
            if "references" in found.columns:
                refs = (
                    found[["Species", "references"]]
                    .explode("references")
                    .rename(columns={"references": "Reference"})
                    .dropna(subset=["Reference"])
                )
                if not refs.empty:
                    refs.to_excel(writer, sheet_name="References", index=False)

        st.download_button(
            label="⬇️ Download Excel",
            data=buffer.getvalue(),
            file_name="ecovault_traits.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )