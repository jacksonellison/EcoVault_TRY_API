import sqlite3
import pandas as pd
import pyodbc
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, NVARCHAR, DECIMAL, INT, DateTime

load_dotenv()

AZURE_USERNAME = os.getenv("AZURE_USERNAME")
AZURE_PASSWORD = os.getenv("AZURE_PASSWORD")
AZURE_SERVER = os.getenv("AZURE_SERVER")
AZURE_DATABASE = os.getenv("AZURE_DATABASE")

# SQLite connection (local)
sqlite_conn = sqlite3.connect(r"D:\VegVault\VegVault.sqlite")

# Azure connection (cloud)
connection_string = (
    f"mssql+pyodbc://{AZURE_USERNAME}:{AZURE_PASSWORD}@{AZURE_SERVER}/{AZURE_DATABASE}"
    "?driver=ODBC+Driver+17+for+SQL+Server"
)
engine = create_engine(connection_string, fast_executemany=True)

# VegVault database query
query = """
SELECT
    taxon_name AS Species,
    ROUND(AVG(CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END), 2) AS "Stem Specific Density AVG",
    COUNT(CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END) AS "Stem Specific Density COUNT",
    ROUND(SQRT((SUM((CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END) *
                   (CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END)) -
                  SUM((CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END)) *
                  SUM((CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END)) /
                  COUNT(CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END)) /
                  (COUNT(CASE WHEN t.trait_domain_id = 1 THEN tv.trait_value END) - 1)), 2) AS "Stem Specific Density SD",
    ROUND(AVG(CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END), 2) AS "Leaf Nitrogen Content per Unit Mass AVG",
    COUNT(CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END) AS "Leaf Nitrogen Content per Unit Mass COUNT",
    ROUND(SQRT((SUM((CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END) *
                   (CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END)) -
                  SUM((CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END)) *
                  SUM((CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END)) /
                  COUNT(CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END)) /
                  (COUNT(CASE WHEN t.trait_domain_id = 2 THEN tv.trait_value END) - 1)), 2) AS "Leaf Nitrogen Content per Unit Mass SD",
    ROUND(AVG(CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END), 3) AS "Diaspore Mass AVG",
    COUNT(CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END) AS "Diaspore Mass COUNT",
    ROUND(SQRT((SUM((CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END) *
                   (CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END)) -
                  SUM((CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END)) *
                  SUM((CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END)) /
                  COUNT(CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END)) /
                  (COUNT(CASE WHEN t.trait_domain_id = 3 THEN tv.trait_value END) - 1)), 2) AS "Diaspore Mass SD",
    ROUND(AVG(CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END), 2) AS "Plant Height AVG",
    COUNT(CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END) AS "Plant Height COUNT",
    ROUND(SQRT((SUM((CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END) *
                   (CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END)) -
                  SUM((CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END)) *
                  SUM((CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END)) /
                  COUNT(CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END)) /
                  (COUNT(CASE WHEN t.trait_domain_id = 4 THEN tv.trait_value END) - 1)), 2) AS "Plant Height SD",
    ROUND(AVG(CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END), 2) AS "Leaf Area AVG",
    COUNT(CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END) AS "Leaf Area COUNT",
    ROUND(SQRT((SUM((CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END) *
                   (CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END)) -
                  SUM((CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END)) *
                  SUM((CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END)) /
                  COUNT(CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END)) /
                  (COUNT(CASE WHEN t.trait_domain_id = 5 THEN tv.trait_value END) - 1)), 2) AS "Leaf Area SD",
    ROUND(AVG(CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END), 2) AS "1/SLA AVG",
    COUNT(CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END) AS "1/SLA COUNT",
    ROUND(SQRT((SUM((CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END) *
                   (CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END)) -
                  SUM((CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END)) *
                  SUM((CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END)) /
                  COUNT(CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END)) /
                  (COUNT(CASE WHEN t.trait_domain_id = 6 THEN tv.trait_value END) - 1)), 2) AS "1/SLA SD"
FROM TraitsValue tv
JOIN Traits t ON tv.trait_id = t.trait_id
JOIN TaxonClassification tc ON tv.taxon_id = tc.taxon_id
JOIN Taxa ON tc.taxon_species = Taxa.taxon_id
GROUP BY taxon_name
"""

# Execute the query and fetch data into a pandas DataFrame
df = pd.read_sql_query(query, sqlite_conn)
df["ModifyDate"] = pd.Timestamp.now(tz="UTC")
df["ModifyUser"] = "VegVaultQueryExport"

# Close the SQLite connection
sqlite_conn.close()

# Create table in Azure database
df.to_sql(
    name="vegvault_species_agg",
    con=engine,
    if_exists="replace",
    index=False,
    dtype={
        "Species": NVARCHAR(255),
        "Stem Specific Density AVG": DECIMAL(10, 2),
        "Stem Specific Density SD": DECIMAL(10, 2),
        "Stem Specific Density COUNT": INT,
        "Leaf Nitrogen Content per Unit Mass AVG": DECIMAL(10, 2),
        "Leaf Nitrogen Content per Unit Mass SD": DECIMAL(10, 2),
        "Leaf Nitrogen Content per Unit Mass COUNT": INT,
        "Diaspore Mass AVG": DECIMAL(10, 2),
        "Diaspore Mass SD": DECIMAL(10, 2),
        "Diaspore Mass COUNT": INT,
        "Plant Height AVG": DECIMAL(10, 2),
        "Plant Height SD": DECIMAL(10, 2),
        "Plant Height COUNT": INT,
        "Leaf Area AVG": DECIMAL(10, 2),
        "Leaf Area SD": DECIMAL(10, 2),
        "Leaf Area COUNT": INT,
        "1/SLA AVG": DECIMAL(10, 2),
        "1/SLA SD": DECIMAL(10, 2),
        "1/SLA COUNT": INT,
        "ModifyDate": DateTime(),
        "ModifyUser": NVARCHAR(64),
    },
    chunksize=500,
    method=None,
)

print("Data uploaded successfully to Azure.")
