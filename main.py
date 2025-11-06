import os
from typing import List
from fastapi import FastAPI, Security, Request, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, bindparam
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Config
API_KEY = "A6MmAE31wO_NRSQf9GlvvvxuTtXs4pDH2X54BsgP5ps"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

# Database
connection_string = "sqlite:///VegVault_agg.sqlite"
engine = create_engine(connection_string, connect_args={"check_same_thread": False})

# App setup
app = FastAPI(title="VegVault API")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth check
def verify_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(403, "Invalid API key")
    return key

@app.get("/")
def root():
    return "VegVault API"

# Models
class SpeciesAgg(BaseModel):
    Species: str
    Stem_Specific_Density_AVG: float | None = None
    Stem_Specific_Density_SD: float | None = None
    Stem_Specific_Density_COUNT: int | None = None
    Leaf_Nitrogen_Content_per_Unit_Mass_AVG: float | None = None
    Leaf_Nitrogen_Content_per_Unit_Mass_SD: float | None = None
    Leaf_Nitrogen_Content_per_Unit_Mass_COUNT: int | None = None
    Diaspore_Mass_AVG: float | None = None
    Diaspore_Mass_SD: float | None = None
    Diaspore_Mass_COUNT: int | None = None
    Plant_Height_AVG: float | None = None
    Plant_Height_SD: float | None = None
    Plant_Height_COUNT: int | None = None
    Leaf_Area_AVG: float | None = None
    Leaf_Area_SD: float | None = None
    Leaf_Area_COUNT: int | None = None
    Inv_SLA_AVG: float | None = None
    Inv_SLA_SD: float | None = None
    Inv_SLA_COUNT: int | None = None

class SpeciesBatchRequest(BaseModel):
    species: List[str] = Field(..., min_length=1, max_length=50)

class SpeciesBatchResponse(BaseModel):
    found: List[SpeciesAgg]
    missing: List[str]

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
            [Species],
            [Stem Specific Density AVG] AS Stem_Specific_Density_AVG,
            [Stem Specific Density SD] AS Stem_Specific_Density_SD,
            [Stem Specific Density COUNT] AS Stem_Specific_Density_COUNT,
            [Leaf Nitrogen Content per Unit Mass AVG] AS Leaf_Nitrogen_Content_per_Unit_Mass_AVG,
            [Leaf Nitrogen Content per Unit Mass SD] AS Leaf_Nitrogen_Content_per_Unit_Mass_SD,
            [Leaf Nitrogen Content per Unit Mass COUNT] AS Leaf_Nitrogen_Content_per_Unit_Mass_COUNT,
            [Diaspore Mass AVG] AS Diaspore_Mass_AVG,
            [Diaspore Mass SD] AS Diaspore_Mass_SD,
            [Diaspore Mass COUNT] AS Diaspore_Mass_COUNT,
            [Plant Height AVG] AS Plant_Height_AVG,
            [Plant Height SD] AS Plant_Height_SD,
            [Plant Height COUNT] AS Plant_Height_COUNT,
            [Leaf Area AVG] AS Leaf_Area_AVG,
            [Leaf Area SD] AS Leaf_Area_SD,
            [Leaf Area COUNT] AS Leaf_Area_COUNT,
            [1/SLA AVG] AS Inv_SLA_AVG,
            [1/SLA SD] AS Inv_SLA_SD,
            [1/SLA COUNT] AS Inv_SLA_COUNT
        FROM [vegvault_species_agg]
        WHERE LOWER([Species]) IN :species_list
    """).bindparams(bindparam("species_list", expanding=True))

    with engine.begin() as conn:
        rows = conn.execute(sql, {"species_list": [s.lower() for s in clean]}).mappings().all()

    found = [dict(r) for r in rows]
    found_names_lower = {r["Species"].lower() for r in found}
    missing = [s for s in clean if s.lower() not in found_names_lower]

    return {"found": found, "missing": missing}
