"""Builds data/subset/*.parquet — the exact tables the agent uses (already cleaned: amount_usd filled).
Makes the deployed server start in ~1 s and use far less memory than reading the 200 MB of CSVs.
    python3 scripts/build_subset.py
"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents")); sys.path.insert(0, ROOT)
os.environ["HACKATHON_DATA"] = os.environ.get("HACKATHON_DATA", os.path.join(ROOT, "hackathon-data"))
import tools
assert not os.path.exists(os.path.join(tools.SUBSET_DIR, "customers.parquet")) or "--force" in sys.argv, \
    "subset already exists (use --force to rebuild from the CSVs)"
if "--force" in sys.argv:
    tools.SUBSET_DIR = "/nonexistent"  # force reading the CSVs
con = tools._con()
out = os.path.join(ROOT, "data", "subset"); os.makedirs(out, exist_ok=True)
for t in ("customers", "txns", "complaint_stats"):
    con.execute(f"COPY {t} TO '{out}/{t}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
    print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0], "rows",
          round(os.path.getsize(f"{out}/{t}.parquet") / 1e6, 1), "MB")
