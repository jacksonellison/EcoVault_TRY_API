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
from pygbif import species as gbif_species

# Config
VALID_API_KEYS = {
    "A6MmAE31wO_NRSQf9GlvvvxuTtXs4pDH2X54BsgP5ps",
    "om_f2p4Mfh832OrbSOe1K1BZALiskeQr_6LyteZmuT0"
}
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

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

# Models
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

class TaxonomyResult(BaseModel):
    input_name: str
    matched: bool
    canonical_name: str | None = None
    scientific_name: str | None = None  
    authorship: str | None = None
    status: str | None = None
    match_type: str | None = None
    confidence: int | None = None
    is_synonym: bool = False
    accepted_name: str | None = None  
    accepted_authorship: str | None = None
    kingdom: str | None = None
    phylum: str | None = None
    class_name: str | None = None  
    order: str | None = None
    family: str | None = None
    genus: str | None = None
    species: str | None = None
    rank: str | None = None 

class TaxonomyBatchRequest(BaseModel):
    species: List[str] = Field(..., min_length=1, max_length=50)

class TaxonomyBatchResponse(BaseModel):
    results: List[TaxonomyResult]



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

    with engine.begin() as conn:
        rows = conn.execute(sql, {"species_list": [s.lower() for s in clean]}).mappings().all()

    found = []
    for r in rows:
        record = dict(r)
        reference_json = record.pop("reference_json", None)
        record["references"] = json.loads(reference_json) if reference_json else []
        found.append(record)

    found_names_lower = {r["species"].lower() for r in found}
    missing = [s for s in clean if s.lower() not in found_names_lower]

    return {"found": found, "missing": missing}

@app.post("/taxonomy/batch", response_model=TaxonomyBatchResponse)
@limiter.limit("10/minute")
@limiter.limit("100/hour")
@limiter.limit("1000/day")
def get_taxonomy_batch(
    request: Request,
    payload: TaxonomyBatchRequest,
    api_key: str = Security(verify_api_key)
):
    results = []
    
    for name in payload.species:
        name = name.strip()
        if not name:
            continue
            
        try:
            result = gbif_species.name_backbone(name)
            
            if 'usageKey' not in result:
                results.append(TaxonomyResult(
                    input_name=name,
                    matched=False
                ))
                continue
            
            usage = result.get('usage', result) 
            accepted = result.get('acceptedUsage', {})
            diagnostics = result.get('diagnostics', {})
            
            canonical = usage.get('canonicalName', result.get('canonicalName'))
            authorship = usage.get('authorship', result.get('authorship'))
            scientific = usage.get('scientificName', result.get('scientificName', canonical))
            
            is_synonym = result.get('synonym', False)
            
            results.append(TaxonomyResult(
                input_name=name,
                matched=True,
                canonical_name=canonical,
                scientific_name=scientific,
                authorship=authorship,
                status=usage.get('status', result.get('status')),
                match_type=diagnostics.get('matchType', result.get('matchType')),
                confidence=diagnostics.get('confidence', result.get('confidence')),
                is_synonym=is_synonym,
                accepted_name=accepted.get('canonicalName') if is_synonym else None,
                accepted_authorship=accepted.get('authorship') if is_synonym else None,
                kingdom=result.get('kingdom'),
                phylum=result.get('phylum'),
                class_name=result.get('class'),
                order=result.get('order'),
                family=result.get('family'),
                genus=result.get('genus'),
                species=result.get('species'),
                rank=usage.get('rank', result.get('rank'))
            ))
            
        except Exception as e:
            results.append(TaxonomyResult(
                input_name=name,
                matched=False
            ))
    
    return {"results": results}
