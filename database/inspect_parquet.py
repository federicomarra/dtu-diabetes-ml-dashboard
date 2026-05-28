import pandas as pd
import sys
import glob

files = glob.glob('simulated-data/*.parquet')
if not files:
    print("Error: No parquet files found in database/simulated-data")
    sys.exit(1)

print("Found files:", files)
df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
print("--- INFO ---")
df.info()
print("\n--- HEAD ---")
print(df.head())
print("\n--- COLUMNS ---")
print(df.columns.tolist())
