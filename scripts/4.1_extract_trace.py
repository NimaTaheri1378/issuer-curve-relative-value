import wrds
import pandas as pd
import numpy as np

print("=== LOAD ELIGIBLE CUSIPS ===")
df_cusip = pd.read_parquet("artifacts/interim/4.0_fisd_eligible_bonds.parquet")

cusips = df_cusip["cusip"].dropna().unique()
print("Total CUSIPs:", len(cusips))

# SAMPLE for pilot
np.random.seed(42)
cusips = np.random.choice(cusips, size=5000, replace=False)
print("Pilot sample:", len(cusips))

print("=== CONNECT WRDS ===")
db = wrds.Connection()

# chunk to avoid SQL limits
CHUNK = 500

results = []

for i in range(0, len(cusips), CHUNK):
    chunk = cusips[i:i+CHUNK]
    
    print(f"[QUERY] chunk {i} → {i+len(chunk)}")

    cusip_list = ",".join([f"'{c}'" for c in chunk])

    query = f"""
    SELECT
        cusip_id as cusip,
        trd_exctn_dt as trade_date,
        rptd_pr as price,
        yld_pt as yield,
        entrd_vol_qt as size
    FROM wrdsapps_bondret.trace_enhanced_clean
    WHERE cusip_id IN ({cusip_list})
      AND trd_exctn_dt >= '2024-01-01'
      AND trd_exctn_dt < '2025-01-01'
    """

    try:
        df = db.raw_sql(query)
        results.append(df)
    except Exception as e:
        print("ERROR:", e)

print("=== CONCAT RESULTS ===")
df = pd.concat(results, ignore_index=True)

print("Rows:", len(df))

# aggregate
agg = df.groupby(["cusip", "trade_date"]).agg(
    n_trades=("price","count"),
    price_mean=("price","mean"),
    yield_mean=("yield","mean"),
    size_sum=("size","sum")
).reset_index()

print("Aggregated rows:", len(agg))

agg.to_parquet("artifacts/interim/4.1_trace_pilot.parquet")

print("Saved TRACE pilot")

db.close()
