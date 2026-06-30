"""
Delete all rows from the observations table only.
Run from the project root:
    python backend/clean_db.py
"""
#wang

import os
import pathlib

import psycopg2
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env")

db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise SystemExit("DATABASE_URL not set in backend/.env")

conn = psycopg2.connect(db_url)
try:
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM observations")
            deleted = cur.rowcount
    print(f"Deleted {deleted} row(s) from observations.")
finally:
    conn.close()
