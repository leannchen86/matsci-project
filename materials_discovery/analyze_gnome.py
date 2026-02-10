import pandas as pd
import numpy as np
import re

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 80)

SUMMARY_CSV = "/mnt/disk1/home/leann/matsci/materials_discovery/data/gnome_data/stable_materials_summary.csv"
R2SCAN_CSV  = "/mnt/disk1/home/leann/matsci/materials_discovery/data/gnome_data/stable_materials_r2scan.csv"

# ── Load main summary ──
print("=" * 100)
print("LOADING: stable_materials_summary.csv")
print("=" * 100)
df = pd.read_csv(SUMMARY_CSV)

# ── 1. First 5 rows transposed ──
print("\n" + "=" * 100)
print("1. FIRST 5 ROWS (TRANSPOSED)")
print("=" * 100)
print(df.head(5).T.to_string())

# ── 2. Shape, dtypes, null counts ──
print("\n" + "=" * 100)
print("2. SHAPE, DTYPES, NULL COUNTS")
print("=" * 100)
print(f"\nShape: {df.shape[0]} rows x {df.shape[1]} columns\n")
info_df = pd.DataFrame({
    'dtype': df.dtypes,
    'non_null': df.notnull().sum(),
    'null_count': df.isnull().sum(),
    'null_pct': (df.isnull().sum() / len(df) * 100).round(2)
})
print(info_df.to_string())

# ── 3. Distribution stats for key energy columns ──
energy_cols = [
    'Decomposition Energy Per Atom',
    'Decomposition Energy Per Atom All',
    'Decomposition Energy Per Atom Relative',
    'Decomposition Energy Per Atom MP',
    'Decomposition Energy Per Atom MP OQMD',
    'Formation Energy Per Atom',
    'Bandgap',
]

# Only keep columns that actually exist
energy_cols_present = [c for c in energy_cols if c in df.columns]
energy_cols_missing = [c for c in energy_cols if c not in df.columns]

print("\n" + "=" * 100)
print("3. DISTRIBUTION STATS FOR KEY ENERGY / BANDGAP COLUMNS")
print("=" * 100)
if energy_cols_missing:
    print(f"\n  [Missing columns, not in CSV]: {energy_cols_missing}")
if energy_cols_present:
    stats = df[energy_cols_present].describe(percentiles=[0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]).T
    print(f"\n{stats.to_string()}\n")

# ── 4. Decomposition Energy Per Atom: on hull vs above ──
dec_col = 'Decomposition Energy Per Atom'
print("\n" + "=" * 100)
print("4. DECOMPOSITION ENERGY PER ATOM: ON HULL (<= 0) vs ABOVE (> 0)")
print("=" * 100)
if dec_col in df.columns:
    on_hull = (df[dec_col] <= 0).sum()
    above   = (df[dec_col] > 0).sum()
    null_c  = df[dec_col].isnull().sum()
    print(f"  <= 0 (on hull):    {on_hull:>10,}  ({on_hull/len(df)*100:.2f}%)")
    print(f"  >  0 (above hull): {above:>10,}  ({above/len(df)*100:.2f}%)")
    print(f"  null:              {null_c:>10,}  ({null_c/len(df)*100:.2f}%)")
    print(f"  == 0 exactly:      {(df[dec_col] == 0).sum():>10,}")
    print(f"  <  0:              {(df[dec_col] < 0).sum():>10,}")
else:
    print(f"  Column '{dec_col}' not found.")

# ── 5. Binned distribution of Decomposition Energy Per Atom ──
print("\n" + "=" * 100)
print("5. BINNED DISTRIBUTION OF DECOMPOSITION ENERGY PER ATOM")
print("=" * 100)
if dec_col in df.columns:
    vals = df[dec_col].dropna()
    bins = {
        '== 0':          (vals == 0).sum(),
        '(0, 0.001]':    ((vals > 0) & (vals <= 0.001)).sum(),
        '(0.001, 0.01]': ((vals > 0.001) & (vals <= 0.01)).sum(),
        '(0.01, 0.025]': ((vals > 0.01) & (vals <= 0.025)).sum(),
        '(0.025, 0.05]': ((vals > 0.025) & (vals <= 0.05)).sum(),
        '(0.05, 0.1]':   ((vals > 0.05) & (vals <= 0.1)).sum(),
        '> 0.1':         (vals > 0.1).sum(),
        '< 0':           (vals < 0).sum(),
    }
    total_valid = len(vals)
    print(f"\n  {'Bin':<20s} {'Count':>10s} {'Pct':>8s}")
    print(f"  {'-'*20} {'-'*10} {'-'*8}")
    for label, cnt in bins.items():
        print(f"  {label:<20s} {cnt:>10,} {cnt/total_valid*100:>7.2f}%")
    print(f"  {'TOTAL (non-null)':<20s} {total_valid:>10,}")

# ── 6. Is Train distribution ──
print("\n" + "=" * 100)
print("6. IS TRAIN DISTRIBUTION")
print("=" * 100)
train_col_candidates = [c for c in df.columns if 'train' in c.lower() or 'is_train' in c.lower()]
if train_col_candidates:
    for tc in train_col_candidates:
        vc = df[tc].value_counts(dropna=False)
        print(f"\n  Column: '{tc}'")
        for val, cnt in vc.items():
            print(f"    {str(val):<15s}: {cnt:>10,}  ({cnt/len(df)*100:.2f}%)")
else:
    print("  No 'Is Train' column found. Columns available:")
    for c in sorted(df.columns):
        print(f"    {c}")

# ── 7. Distribution of number of elements ──
print("\n" + "=" * 100)
print("7. DISTRIBUTION OF NUMBER OF ELEMENTS")
print("=" * 100)
elem_col_candidates = [c for c in df.columns if 'element' in c.lower() or 'composition' in c.lower() or 'formula' in c.lower()]
print(f"  Candidate columns: {elem_col_candidates}")

# Try multiple strategies
n_elem_series = None
elem_col_used = None

# Strategy 1: If there's a column like 'Number of Elements' or 'Nelements'
for c in df.columns:
    if 'n_element' in c.lower() or 'nelements' in c.lower() or 'number of element' in c.lower() or 'num_element' in c.lower():
        n_elem_series = df[c]
        elem_col_used = c
        break

# Strategy 2: Parse from Elements column (could be list-like)
if n_elem_series is None:
    for c in df.columns:
        if c.lower() == 'elements' or c.lower() == 'reduced formula' or c.lower() == 'composition':
            sample = df[c].dropna().iloc[0]
            print(f"  Trying to parse '{c}', sample value: {sample}")
            if isinstance(sample, str) and ('[' in sample or ',' in sample):
                # Looks like a list
                n_elem_series = df[c].dropna().apply(lambda x: len(str(x).strip('[]').split(',')))
                elem_col_used = c + " (parsed list)"
                break
            elif isinstance(sample, str):
                # Try parsing chemical formula
                n_elem_series = df[c].dropna().apply(lambda x: len(set(re.findall(r'[A-Z][a-z]?', str(x)))))
                elem_col_used = c + " (parsed formula)"
                break

# Strategy 3: 'Nsites' or count from 'Reduced Formula' etc
if n_elem_series is None:
    for c in df.columns:
        if 'formula' in c.lower():
            sample = df[c].dropna().iloc[0]
            print(f"  Trying formula col '{c}', sample: {sample}")
            n_elem_series = df[c].dropna().apply(lambda x: len(set(re.findall(r'[A-Z][a-z]?', str(x)))))
            elem_col_used = c + " (parsed formula)"
            break

if n_elem_series is not None:
    print(f"\n  Used: {elem_col_used}")
    vc = n_elem_series.value_counts().sort_index()
    print(f"\n  {'N_elements':<15s} {'Count':>10s} {'Pct':>8s}")
    print(f"  {'-'*15} {'-'*10} {'-'*8}")
    for val, cnt in vc.items():
        print(f"  {str(val):<15s} {cnt:>10,} {cnt/len(df)*100:>7.2f}%")
else:
    print("  Could not determine number of elements. Columns:")
    for c in sorted(df.columns):
        print(f"    {c}")

# ── 8. Bandgap data availability ──
print("\n" + "=" * 100)
print("8. BANDGAP DATA AVAILABILITY")
print("=" * 100)
bg_col = 'Bandgap'
if bg_col not in df.columns:
    bg_col = [c for c in df.columns if 'bandgap' in c.lower() or 'band_gap' in c.lower()]
    bg_col = bg_col[0] if bg_col else None

if bg_col:
    non_null = df[bg_col].notnull().sum()
    non_zero = ((df[bg_col].notnull()) & (df[bg_col] != 0)).sum()
    zero_val = ((df[bg_col].notnull()) & (df[bg_col] == 0)).sum()
    null_val = df[bg_col].isnull().sum()
    print(f"  Column: '{bg_col}'")
    print(f"  Non-null:              {non_null:>10,}  ({non_null/len(df)*100:.2f}%)")
    print(f"  Non-null AND non-zero: {non_zero:>10,}  ({non_zero/len(df)*100:.2f}%)")
    print(f"  Zero:                  {zero_val:>10,}  ({zero_val/len(df)*100:.2f}%)")
    print(f"  Null:                  {null_val:>10,}  ({null_val/len(df)*100:.2f}%)")
    if non_zero > 0:
        print(f"\n  Stats for non-zero bandgaps:")
        nz = df.loc[(df[bg_col].notnull()) & (df[bg_col] != 0), bg_col]
        print(f"    mean: {nz.mean():.4f}, median: {nz.median():.4f}, std: {nz.std():.4f}")
        print(f"    min: {nz.min():.4f}, max: {nz.max():.4f}")
else:
    print("  No bandgap column found.")

# ── 9. Crystal System distribution ──
print("\n" + "=" * 100)
print("9. CRYSTAL SYSTEM DISTRIBUTION")
print("=" * 100)
cs_col = [c for c in df.columns if 'crystal' in c.lower() and 'system' in c.lower()]
if not cs_col:
    cs_col = [c for c in df.columns if 'crystal' in c.lower() or 'lattice' in c.lower()]
cs_col = cs_col[0] if cs_col else None

if cs_col:
    vc = df[cs_col].value_counts(dropna=False)
    print(f"  Column: '{cs_col}'\n")
    print(f"  {'Crystal System':<25s} {'Count':>10s} {'Pct':>8s}")
    print(f"  {'-'*25} {'-'*10} {'-'*8}")
    for val, cnt in vc.items():
        print(f"  {str(val):<25s} {cnt:>10,} {cnt/len(df)*100:>7.2f}%")
else:
    print("  No Crystal System column found.")

# ── 10. Unique Space Groups ──
print("\n" + "=" * 100)
print("10. UNIQUE SPACE GROUPS")
print("=" * 100)
sg_col = [c for c in df.columns if 'space' in c.lower() and 'group' in c.lower()]
if not sg_col:
    sg_col = [c for c in df.columns if 'spacegroup' in c.lower() or 'sg' in c.lower()]
sg_col = sg_col[0] if sg_col else None

if sg_col:
    nunique = df[sg_col].nunique()
    print(f"  Column: '{sg_col}'")
    print(f"  Unique space groups: {nunique}")
    print(f"\n  Top 20 most common:")
    vc = df[sg_col].value_counts().head(20)
    for val, cnt in vc.items():
        print(f"    {str(val):<30s}: {cnt:>8,}  ({cnt/len(df)*100:.2f}%)")
else:
    print("  No Space Group column found.")

# ── 11. Cross-tab: Is Train vs binned Decomposition Energy ──
print("\n" + "=" * 100)
print("11. CROSS-TAB: IS TRAIN vs BINNED DECOMPOSITION ENERGY")
print("=" * 100)

train_col = train_col_candidates[0] if train_col_candidates else None
if train_col and dec_col in df.columns:
    def bin_dec_energy(x):
        if pd.isna(x):
            return 'null'
        if x < 0:
            return '< 0'
        if x == 0:
            return '== 0'
        if x <= 0.001:
            return '(0, 0.001]'
        if x <= 0.01:
            return '(0.001, 0.01]'
        if x <= 0.025:
            return '(0.01, 0.025]'
        if x <= 0.05:
            return '(0.025, 0.05]'
        if x <= 0.1:
            return '(0.05, 0.1]'
        return '> 0.1'

    df['_dec_bin'] = df[dec_col].apply(bin_dec_energy)
    ct = pd.crosstab(df[train_col], df['_dec_bin'], margins=True)
    # Reorder columns
    desired_order = ['< 0', '== 0', '(0, 0.001]', '(0.001, 0.01]', '(0.01, 0.025]', '(0.025, 0.05]', '(0.05, 0.1]', '> 0.1', 'null', 'All']
    actual_order = [c for c in desired_order if c in ct.columns]
    ct = ct[actual_order]
    print(f"\n{ct.to_string()}")

    # Also show percentages per row
    print("\n  Row percentages:")
    ct_pct = pd.crosstab(df[train_col], df['_dec_bin'], normalize='index') * 100
    actual_order_noa = [c for c in desired_order if c in ct_pct.columns]
    ct_pct = ct_pct[actual_order_noa].round(2)
    print(f"\n{ct_pct.to_string()}")

    df.drop(columns=['_dec_bin'], inplace=True)
else:
    print("  Cannot produce cross-tab (missing train or decomposition energy column).")

# ══════════════════════════════════════════════════════════════════════════════
# R2SCAN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("R2SCAN DATASET ANALYSIS: stable_materials_r2scan.csv")
print("=" * 100)

df2 = pd.read_csv(R2SCAN_CSV)

print(f"\nShape: {df2.shape[0]} rows x {df2.shape[1]} columns")
print(f"\nColumns:\n  {list(df2.columns)}")

print(f"\nFirst 3 rows (transposed):")
print(df2.head(3).T.to_string())

print(f"\nDtypes and nulls:")
info2 = pd.DataFrame({
    'dtype': df2.dtypes,
    'non_null': df2.notnull().sum(),
    'null_count': df2.isnull().sum(),
    'null_pct': (df2.isnull().sum() / len(df2) * 100).round(2)
})
print(info2.to_string())

# Numeric stats
num_cols2 = df2.select_dtypes(include=[np.number]).columns.tolist()
if num_cols2:
    print(f"\nNumeric column stats:")
    print(df2[num_cols2].describe().T.to_string())

# ── Overlap analysis ──
print("\n" + "=" * 100)
print("OVERLAP ANALYSIS: summary vs r2scan")
print("=" * 100)

# Try MaterialId
for id_col_name in ['MaterialId', 'Material Id', 'material_id', 'Reduced Formula', 'Composition']:
    if id_col_name in df.columns and id_col_name in df2.columns:
        set1 = set(df[id_col_name].dropna().astype(str))
        set2 = set(df2[id_col_name].dropna().astype(str))
        overlap = set1 & set2
        print(f"\n  By '{id_col_name}':")
        print(f"    Summary unique: {len(set1):>10,}")
        print(f"    R2SCAN unique:  {len(set2):>10,}")
        print(f"    Overlap:        {len(overlap):>10,}  ({len(overlap)/len(set2)*100:.2f}% of r2scan)")

# Also try matching on common column names
common_cols = set(df.columns) & set(df2.columns)
print(f"\n  Common columns between the two files:")
for c in sorted(common_cols):
    print(f"    {c}")

print("\n" + "=" * 100)
print("ANALYSIS COMPLETE")
print("=" * 100)
