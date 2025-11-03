import os
from typing import List
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, bindparam

connection_string = "sqlite:///VegVault_agg.sqlite"
engine = create_engine(
    connection_string,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True
)

app = FastAPI()

@app.get("/")
def root():
    return("VegVault API")

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
    species: List[str] = Field(..., min_length=1)

class SpeciesBatchResponse(BaseModel):
    found: List[SpeciesAgg]
    missing: List[str]

@app.post("/species/batch", response_model=SpeciesBatchResponse)
def get_species_batch(payload: SpeciesBatchRequest):
    # normalize input: strip whitespace, drop empties, de-duplicate preserving order
    seen = set()
    clean = []
    for s in payload.species:
        s2 = s.strip()
        if s2 and s2 not in seen:
            seen.add(s2)
            clean.append(s2)
    if not clean:
        return {"found": [], "missing": payload.species}

    # SQL Server IN with expanding parameter
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
