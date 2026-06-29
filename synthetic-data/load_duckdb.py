"""Load the generated parquet into a DuckDB file and print the headline diagnostic:
the AI-analysis completion rate by LLM latency band. This is the evidence that the
drop-off is a latency problem (the case for the fallback router).

Run:  python synthetic-data/load_duckdb.py
"""
import os

import duckdb

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
DB = os.path.join(DATA, "warehouse.duckdb")

con = duckdb.connect(DB)
for tbl in ["users", "funnel_events", "llm_traces", "loans"]:
    con.execute(f"CREATE OR REPLACE TABLE raw_{tbl} AS "
                f"SELECT * FROM read_parquet('{DATA}/{tbl}.parquet')")
    n = con.execute(f"SELECT count(*) FROM raw_{tbl}").fetchone()[0]
    print(f"loaded raw_{tbl:14s} {n:>8,} rows")

print("\n=== Completion rate by LLM latency band (the diagnostic) ===")
q = """
WITH t AS (
  SELECT user_id, latency_s,
         CASE WHEN latency_s < 3 THEN '1: <3s (low)'
              WHEN latency_s < 5 THEN '2: 3-5s'
              WHEN latency_s < 8 THEN '3: 5-8s'
              ELSE                    '4: >8s (high)' END AS latency_band
  FROM raw_llm_traces
),
completed AS (
  SELECT DISTINCT user_id FROM raw_funnel_events
  WHERE event_name = 'ai_analysis_completed'
)
SELECT latency_band,
       count(*)                                   AS users,
       round(avg(t.latency_s), 2)                 AS avg_latency_s,
       round(100.0 * count(c.user_id) / count(*), 1) AS completion_rate_pct
FROM t LEFT JOIN completed c USING (user_id)
GROUP BY latency_band ORDER BY latency_band;
"""
print(con.execute(q).df().to_string(index=False))
print(f"\nDuckDB warehouse: {DB}")
con.close()
