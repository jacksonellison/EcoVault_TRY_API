import json
import os
from typing import List
from fastapi import FastAPI, Security, Request, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, bindparam
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import requests as http   # avoid clash with fastapi.Request

# Config
VALID_API_KEYS = {
    "A6MmAE31wO_NRSQf9GlvvvxuTtXs4pDH2X54BsgP5ps",
    "om_f2p4Mfh832OrbSOe1K1BZALiskeQr_6LyteZmuT0"
}
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

# GNverifier (Global Names) — one call covers every source below
GN_URL = "https://verifier.globalnames.org/api/v1/verifications"
GN_SOURCES = {          # dataSourceId -> short label used in responses
    1:   "CoL",
    3:   "ITIS",
    11:  "GBIF",
    196: "WFO",
}
MAX_ALTERNATIVES = 4    # alternatives returned besides the best match

# Database
connection_string = "sqlite:///database.sqlite"
engine = create_engine(connection_string, connect_args={"check_same_thread": False})

# App setup
app = FastAPI(title="VegVault API")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth check
def verify_api_key(key: str = Security(api_key_header)):
    if key not in VALID_API_KEYS:
        raise HTTPException(403, "Invalid API key")
    return key

@app.get("/")
def root():
    return "VegVault API"

# ── Models ────────────────────────────────────────────────────────────────────
class SpeciesAgg(BaseModel):
    species: str
    ssd_avg: float | None = None
    ssd_sd: float | None = None
    ssd_n: int | None = None
    leaf_n_avg: float | None = None
    leaf_n_sd: float | None = None
    leaf_n_n: int | None = None
    seed_mass_avg: float | None = None
    seed_mass_sd: float | None = None
    seed_mass_n: int | None = None
    ldmc_avg: float | None = None
    ldmc_sd: float | None = None
    ldmc_n: int | None = None
    height_avg: float | None = None
    height_sd: float | None = None
    height_n: int | None = None
    leaf_area_avg: float | None = None
    leaf_area_sd: float | None = None
    leaf_area_n: int | None = None
    sla_avg: float | None = None
    sla_sd: float | None = None
    sla_n: int | None = None
    references: List[str] = []

class SpeciesBatchRequest(BaseModel):
    species: List[str] = Field(..., min_length=1, max_length=50)

class SpeciesBatchResponse(BaseModel):
    found: List[SpeciesAgg]
    missing: List[str]

class Taxon(BaseModel):
    accepted_name: str | None = None      # current/accepted canonical name (use this downstream)
    accepted_scientific_name: str | None = None   # accepted name with authorship, e.g. "Festuca rubra L."
    matched_name: str | None = None       # canonical name the input was matched to
    scientific_name: str | None = None    # matched name with authorship
    status: str | None = None             # Accepted | Synonym | N/A
    is_synonym: bool = False              # matched_name is a synonym of accepted_name
    match_type: str | None = None         # Exact | Fuzzy | PartialExact | PartialFuzzy
    confidence: float | None = None       # GNverifier sortScore, higher is better (~0–10)
    edit_distance: int | None = None      # characters differing from the input
    sources: List[str] = []               # which of CoL / ITIS / GBIF / WFO gave this answer
    kingdom: str | None = None
    phylum: str | None = None
    class_name: str | None = None
    order: str | None = None
    family: str | None = None
    genus: str | None = None

class TaxonomyResult(BaseModel):
    input_name: str
    match_type: str                       # Exact | Fuzzy | PartialExact | PartialFuzzy | NoMatch
    best: Taxon | None = None             # best-supported interpretation, None if NoMatch
    alternatives: List[Taxon] = []        # other distinct accepted names (homonyms etc.), best first
    ambiguous: bool = False               # True if best is not clearly better supported than alternatives

class TaxonomyBatchRequest(BaseModel):
    species: List[str] = Field(..., min_length=1, max_length=100)

class TaxonomyBatchResponse(BaseModel):
    results: List[TaxonomyResult]


# ── Trait data ────────────────────────────────────────────────────────────────
@app.post("/species/batch", response_model=SpeciesBatchResponse)
@limiter.limit("10/minute")
@limiter.limit("100/hour")
@limiter.limit("1000/day")
def get_species_batch(
    request: Request,
    payload: SpeciesBatchRequest,
    api_key: str = Security(verify_api_key)
):
    # Normalize input
    seen = set()
    clean = [s.strip() for s in payload.species if (s2 := s.strip()) and not (s2 in seen or seen.add(s2))]
    if not clean:
        return {"found": [], "missing": payload.species}

    # Query with case-insensitive matching
    sql = text("""
        SELECT
            species,
            ssd_avg, ssd_sd, ssd_n,
            leaf_n_avg, leaf_n_sd, leaf_n_n,
            seed_mass_avg, seed_mass_sd, seed_mass_n,
            ldmc_avg, ldmc_sd, ldmc_n,
            height_avg, height_sd, height_n,
            leaf_area_avg, leaf_area_sd, leaf_area_n,
            sla_avg, sla_sd, sla_n,
            reference_json
        FROM agg
        WHERE LOWER(species) IN :species_list
    """).bindparams(bindparam("species_list", expanding=True))

    # Traits are matched at species level: infraspecific input (subsp./var.) is
    # looked up under its parent binomial.
    binomial = {s: " ".join(s.split()[:2]).lower() for s in clean}

    with engine.begin() as conn:
        rows = conn.execute(sql, {"species_list": list(set(binomial.values()))}).mappings().all()

    found = []
    for r in rows:
        record = dict(r)
        reference_json = record.pop("reference_json", None)
        record["references"] = json.loads(reference_json) if reference_json else []
        found.append(record)

    found_names_lower = {r["species"].lower() for r in found}
    missing = [s for s in clean if binomial[s] not in found_names_lower]

    return {"found": found, "missing": missing}


# ── Taxonomy ──────────────────────────────────────────────────────────────────
def _parse_gn_result(r: dict) -> Taxon:
    """Turn one GNverifier result record into a Taxon."""
    ranks = r.get("classificationRanks", "").split("|")
    path  = r.get("classificationPath", "").split("|")
    clf   = dict(zip(ranks, path))

    return Taxon(
        accepted_name   = r.get("currentCanonicalSimple"),
        accepted_scientific_name = r.get("currentName"),
        matched_name    = r.get("matchedCanonicalSimple"),
        scientific_name = r.get("matchedName"),
        status          = r.get("taxonomicStatus"),
        is_synonym      = bool(r.get("isSynonym", False)),
        match_type      = r.get("matchType"),
        confidence      = r.get("sortScore"),
        edit_distance   = r.get("editDistance"),
        sources         = [GN_SOURCES.get(r.get("dataSourceId"), r.get("dataSourceTitleShort"))],
        kingdom         = clf.get("kingdom"),
        phylum          = clf.get("phylum") or clf.get("division"),   # ITIS uses "division"
        class_name      = clf.get("class"),
        order           = clf.get("order"),
        family          = clf.get("family"),
        genus           = clf.get("genus"),
    )


def _rank_candidates(results: List[dict]) -> List[Taxon]:
    """
    One Taxon per distinct accepted name, merging the sources that point to it,
    ranked by: number of supporting sources, accepted before synonym, GN score.
    Several entries usually means the input is a homonym (same binomial published
    by different authors for different taxa), e.g. 'Agrostis tenuis'.
    """
    merged: dict[str, Taxon] = {}
    for r in results:   # GNverifier order: best sortScore first
        key = (r.get("currentCanonicalSimple") or "").lower()
        if not key:
            continue
        if key in merged:
            src = _parse_gn_result(r).sources[0]
            if src not in merged[key].sources:
                merged[key].sources.append(src)
        else:
            merged[key] = _parse_gn_result(r)

    return sorted(
        merged.values(),
        key=lambda t: (-len(t.sources), t.is_synonym, -(t.confidence or 0)),
    )


def _is_ambiguous(cands: List[Taxon]) -> bool:
    """Best must beat the runner-up on source support and not itself be a synonym."""
    if len(cands) < 2:
        return False
    best, second = cands[0], cands[1]
    return best.is_synonym or len(best.sources) <= len(second.sources)


@app.post("/taxonomy/batch", response_model=TaxonomyBatchResponse)
@limiter.limit("10/minute")
@limiter.limit("100/hour")
@limiter.limit("1000/day")
def get_taxonomy_batch(
    request: Request,
    payload: TaxonomyBatchRequest,
    api_key: str = Security(verify_api_key)
):
    names = [n.strip().capitalize() for n in payload.species if n.strip()]
    if not names:
        return {"results": []}
    try:
        resp = http.post(GN_URL, json={
            "nameStrings": names,
            "dataSources": list(GN_SOURCES.keys()),
            "withAllMatches": True,
        }, timeout=30)
        resp.raise_for_status()
        gn_names = resp.json().get("names", [])
    except http.RequestException as e:
        raise HTTPException(502, f"GNverifier request failed: {e}")
    results = []
    for name, entry in zip(names, gn_names):
        candidates = _rank_candidates(entry.get("results", []))
        # Partial* = only the genus part of the input was recognised; not a usable match
        if entry.get("matchType") in (None, "NoMatch", "PartialExact", "PartialFuzzy") or not candidates:
            results.append(TaxonomyResult(input_name=name, match_type="NoMatch"))
            continue

        results.append(TaxonomyResult(
            input_name   = name,
            match_type   = entry["matchType"],
            best         = candidates[0],
            alternatives = candidates[1:1 + MAX_ALTERNATIVES],
            ambiguous    = _is_ambiguous(candidates),
        ))

    return {"results": results}