"""
Sri Lanka Landslide Prediction Model — v3 (Year-Wise Polygon SHP Edition)
==========================================================================
WHAT'S NEW vs v2:
  • Output is now a POLYGON shapefile (one row per district × year),
    built by joining the per-year composite-risk score back onto the
    original susceptibility polygon geometry (dissolved to district level).
  • Every year in the rainfall CSV gets its own risk score so the output
    can feed a year-slider / district-dropdown UI.
  • --districts filter still works exactly as before.
  • All 8 analysis steps are preserved; Step 8 is completely rewritten.

OUTPUT SHP SCHEMA (one feature = one district polygon, one year):
  district   – district name
  year       – calendar year (integer)
  risk_class – Low / Moderate / High / Very High
  risk_id    – 1 / 2 / 3 / 4
  comp_risk  – composite score 0–1
  wsi        – Weighted Susceptibility Index (static per district)
  rf_mm      – annual rainfall that year (mm)
  rf_mean    – long-run mean rainfall (mm)
  rf_q75     – Q75 threshold
  rf_q90     – Q90 threshold
  trig_rf    – dynamic trigger threshold (mm)
  pct_vlow   – % very-low susceptibility area
  pct_low    – % low susceptibility area
  pct_mod    – % moderate susceptibility area
  pct_high   – % high susceptibility area
  total_km2  – district area (km²)
  ls_events  – historical landslide events (distributed)
  cluster    – cluster label (from K-Means or trivial assignment)

OUTPUT FOLDER STRUCTURE:
  out_dir/
   ├── Kandy/
   │    ├── LandslideRisk_YearWise_Kandy.shp
   │    ├── LandslideRisk_YearWise_Kandy.dbf
   │    ├── LandslideRisk_YearWise_Kandy.shx
   │    └── LandslideRisk_YearWise_Kandy.csv
   └── Nuwara_Eliya/
        ├── LandslideRisk_YearWise_Nuwara_Eliya.shp
        ├── LandslideRisk_YearWise_Nuwara_Eliya.dbf
        ├── LandslideRisk_YearWise_Nuwara_Eliya.shx
        └── LandslideRisk_YearWise_Nuwara_Eliya.csv

USAGE:
  python landslide_model_v3_yearwise.py \\
      --shp_root  "/path/to/Susceptibility_Phase1_v1" \\
      --rainfall  "/path/to/Srilanka Rainfall year wise.csv" \\
      --landslide "/path/to/landslides_Sri_Lanka.csv" \\
      --out_dir   "/path/to/output_shapefiles" \\
      --districts Kandy "Nuwara Eliya"

  # All 25 districts (omit --districts):
  python landslide_model_v3_yearwise.py \\
      --shp_root  "..." --rainfall "..." --landslide "..." --out_dir "..."
"""

import os
import sys
import glob
import argparse
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
from scipy import stats
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from shapely.geometry import Point
from shapely.ops import unary_union

warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────────────────────────
# DISTRICT COORDINATES  (fallback point geometry when polygon dissolve fails)
# ──────────────────────────────────────────────────────────────────────────────
DISTRICT_COORDS = {
    'Colombo':      (80.029, 6.848),  'Gampaha':     (80.021, 7.119),
    'Kalutara':     (80.135, 6.576),  'Kandy':        (80.641, 7.215),
    'Matale':       (80.624, 7.470),  'Nuwara Eliya': (80.763, 6.961),
    'Galle':        (80.221, 6.033),  'Matara':       (80.535, 5.946),
    'Hambantota':   (81.119, 6.145),  'Jaffna':       (80.013, 9.661),
    'Mannar':       (79.904, 8.978),  'Vavuniya':     (80.497, 8.752),
    'Mullaitivu':   (80.812, 9.268),  'Kilinochchi':  (80.403, 9.394),
    'Batticaloa':   (81.695, 7.717),  'Ampara':       (81.675, 7.300),
    'Trincomalee':  (81.234, 8.571),  'Kurunegala':   (80.362, 7.487),
    'Puttalam':     (79.839, 8.037),  'Anuradhapura': (80.401, 8.337),
    'Polonnaruwa':  (80.995, 7.939),  'Badulla':      (81.058, 6.990),
    'Monaragala':   (81.350, 6.874),  'Ratnapura':    (80.383, 6.704),
    'Kegalle':      (80.350, 7.250),
}

CMAP = {
    'Low':       '#2ecc71',
    'Moderate':  '#f39c12',
    'High':      '#e67e22',
    'Very High': '#c0392b',
}

RISK_ID = {'Low': 1, 'Moderate': 2, 'High': 3, 'Very High': 4}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description='Sri Lanka Landslide Prediction Model v3 (Year-Wise Polygon SHP)'
    )
    p.add_argument('--shp_root',  required=True,
                   help='Root folder — one sub-folder per district, '
                        'each containing *_susceptibility.shp')
    p.add_argument('--rainfall',  required=True,
                   help='Path to Srilanka_Rainfall_year_wise.csv')
    p.add_argument('--landslide', required=True,
                   help='Path to landslides_Sri_Lanka.csv')
    p.add_argument('--out_dir',   default='./output',
                   help='Output directory for .shp and figures')
    p.add_argument('--districts', nargs='+', default=None, metavar='DISTRICT',
                   help='Optional: one or more district names to process. '
                        'If omitted, all 25 districts are processed.')
    p.add_argument('--year_start', type=int, default=None,
                   help='First year to include in output (default: first year in CSV)')
    p.add_argument('--year_end',   type=int, default=None,
                   help='Last year to include in output (default: last year in CSV)')
    return p.parse_args()


def normalise_name(s):
    return str(s).strip().lower().replace('_', ' ').replace('-', ' ')


# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — READ SUSCEPTIBILITY SHAPEFILES + BUILD DISTRICT POLYGON GEOMETRY
# ──────────────────────────────────────────────────────────────────────────────
def read_susceptibility_shapefiles(shp_root, target_districts=None):
    """
    Returns:
        susc_df   – pd.DataFrame with per-district susceptibility statistics
        dist_geom – dict  { district_name -> shapely geometry (dissolved polygon) }
    """
    print("\n" + "=" * 65)
    print("STEP 1: Reading District Susceptibility Shapefiles")
    print("=" * 65)

    target_set = (
        {normalise_name(d) for d in target_districts} if target_districts else None
    )
    if target_set:
        print(f"  Filter active — processing only: {sorted(target_districts)}")
    else:
        print("  No filter — processing ALL districts")

    all_shp_files = glob.glob(
        os.path.join(shp_root, '**', '*susceptibility.shp'), recursive=True
    )
    if not all_shp_files:
        raise FileNotFoundError(
            f"No *susceptibility.shp found under: {shp_root}"
        )
    print(f"  Total SHP files found: {len(all_shp_files)}")

    def shp_district_name(shp_path):
        folder = os.path.basename(os.path.dirname(shp_path))
        fname  = os.path.basename(shp_path).replace('_susceptibility.shp', '')
        candidate = folder if folder and folder.lower() not in ('', '.') else fname
        return candidate.strip().replace('_', ' ')

    shp_files = (
        [s for s in all_shp_files
         if normalise_name(shp_district_name(s)) in target_set]
        if target_set else all_shp_files
    )
    if not shp_files and target_set:
        shp_files = all_shp_files   # fallback: filter by attribute

    print(f"  SHP files to read : {len(shp_files)}")

    records   = []
    dist_geom = {}          # district_name → dissolved polygon

    for shp_path in sorted(shp_files):
        try:
            gdf = gpd.read_file(shp_path)
        except Exception as e:
            print(f"  [WARN] Cannot read {shp_path}: {e}")
            continue

        gdf.columns = [c.lower().strip() for c in gdf.columns]

        name_col = next(
            (c for c in ['class_name', 'classname', 'class', 'susc_class',
                         'suscept', 'label', 'name'] if c in gdf.columns), None
        )
        if name_col is None:
            print(f"  [WARN] No class column in {shp_path}, skipping")
            continue

        area_col = next(
            (c for c in ['area_km2', 'area_km', 'areakm2', 'area']
             if c in gdf.columns), None
        )
        if area_col is None:
            gdf_proj     = gdf.to_crs('EPSG:32644')
            gdf['area_km2'] = gdf_proj.geometry.area / 1e6
            area_col     = 'area_km2'

        if 'district' in gdf.columns:
            district_name = str(gdf['district'].dropna().iloc[0]).strip()
        else:
            district_name = (
                os.path.basename(shp_path)
                .replace('_susceptibility.shp', '')
                .replace('_susceptibility_class.shp', '')
                .strip()
            )
        district_name = district_name.title().replace('_', ' ')

        if target_set and normalise_name(district_name) not in target_set:
            continue

        # ── Build dissolved polygon geometry for this district ─────────────
        try:
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf_4326 = gdf.to_crs('EPSG:4326')
            else:
                gdf_4326 = gdf
            district_polygon = unary_union(gdf_4326.geometry)
            dist_geom[district_name] = district_polygon
        except Exception as e:
            print(f"  [WARN] Could not dissolve geometry for {district_name}: {e}")
            lon, lat = DISTRICT_COORDS.get(district_name, (80.5, 7.5))
            dist_geom[district_name] = Point(lon, lat).buffer(0.15)

        # ── Aggregate area per susceptibility class ───────────────────────
        gdf['_cls'] = gdf[name_col].str.strip().str.lower()
        ca  = gdf.groupby('_cls')[area_col].sum()
        a_vl = sum(ca.get(k, 0) for k in ['very low', 'very_low', 'verylow'])
        a_l  = ca.get('low', 0)
        a_m  = ca.get('moderate', 0)
        a_h  = sum(ca.get(k, 0) for k in ['high', 'very high', 'very_high', 'veryhigh'])
        total = a_vl + a_l + a_m + a_h
        if total == 0:
            print(f"  [WARN] Zero area for {district_name}, skipping")
            continue

        p_vl, p_l, p_m, p_h = a_vl/total, a_l/total, a_m/total, a_h/total
        wsi = (0*p_vl + 1*p_l + 2*p_m + 3*p_h) / 3.0

        records.append({
            'district':       district_name,
            'total_area_km2': round(total, 3),
            'area_very_low':  round(a_vl, 3),
            'area_low':       round(a_l,  3),
            'area_moderate':  round(a_m,  3),
            'area_high':      round(a_h,  3),
            'pct_very_low':   round(p_vl * 100, 2),
            'pct_low':        round(p_l  * 100, 2),
            'pct_moderate':   round(p_m  * 100, 2),
            'pct_high':       round(p_h  * 100, 2),
            'wsi':            round(wsi, 5),
            'shp_path':       shp_path,
        })
        print(f"  ✓ {district_name:20s}  total={total:8.1f} km²  "
              f"VL={p_vl*100:5.1f}%  L={p_l*100:5.1f}%  "
              f"M={p_m*100:5.1f}%  H={p_h*100:5.1f}%  WSI={wsi:.4f}")

    if not records:
        raise ValueError("No valid susceptibility data found.")

    df = pd.DataFrame(records).reset_index(drop=True)
    print(f"\n  Successfully read {len(df)} district(s)")
    return df, dist_geom


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — RAINFALL STATISTICS
# ──────────────────────────────────────────────────────────────────────────────
def compute_rainfall_stats(rainfall_csv, target_districts=None):
    print("\n" + "=" * 65)
    print("STEP 2: Computing Rainfall Statistics")
    print("=" * 65)

    rf_raw   = pd.read_csv(rainfall_csv)
    year_cols = [c for c in rf_raw.columns if str(c).isdigit() and int(c) >= 1901]
    if not year_cols:
        raise ValueError("No year columns found in rainfall CSV.")

    dist_col = next(
        (c for c in rf_raw.columns if c.strip().lower() == 'district'), None
    )
    if dist_col is None:
        raise ValueError(f"No 'District' column found. Columns: {list(rf_raw.columns)}")

    rf = rf_raw[[dist_col] + year_cols].copy()
    rf = rf.rename(columns={dist_col: 'District'})
    rf['District'] = rf['District'].str.strip().str.replace('_', ' ')

    if target_districts:
        tn   = {normalise_name(d) for d in target_districts}
        mask = rf['District'].apply(normalise_name).isin(tn)
        rf   = rf[mask]
        if rf.empty:
            raise ValueError(f"None of {target_districts} found in rainfall CSV.")

    rf    = rf.set_index('District')
    rf_long = rf.melt(ignore_index=False, var_name='year', value_name='rainfall_mm')
    rf_long['year'] = rf_long['year'].astype(int)
    rf_long = rf_long.reset_index().rename(columns={'District': 'district'})
    rf_long['district'] = rf_long['district'].str.strip().str.replace('_', ' ')

    def stats_for(grp):
        v      = grp['rainfall_mm'].dropna()
        yrs    = grp['year']
        recent = grp[grp['year'] >= 2000]['rainfall_mm'].dropna()
        mode_val    = float(stats.mode(v.round(0), keepdims=True)[0][0])
        trend_slope = np.polyfit(yrs, grp['rainfall_mm'].fillna(v.mean()), 1)[0]
        return pd.Series({
            'rf_min':         v.min(),
            'rf_max':         v.max(),
            'rf_mean':        v.mean(),
            'rf_median':      v.median(),
            'rf_mode':        mode_val,
            'rf_std':         v.std(),
            'rf_cv':          v.std() / v.mean() if v.mean() != 0 else 0,
            'rf_skew':        v.skew(),
            'rf_q10':         v.quantile(0.10),
            'rf_q25':         v.quantile(0.25),
            'rf_q50':         v.quantile(0.50),
            'rf_q75':         v.quantile(0.75),
            'rf_q90':         v.quantile(0.90),
            'rf_q95':         v.quantile(0.95),
            'rf_recent_mean': recent.mean() if len(recent) > 0 else v.mean(),
            'rf_recent_max':  recent.max()  if len(recent) > 0 else v.max(),
            'rf_trend':       trend_slope,
        })

    rf_stats = rf_long.groupby('district').apply(stats_for).reset_index()
    print(f"  Rainfall stats for {len(rf_stats)} district(s):")
    print(rf_stats[['district', 'rf_min', 'rf_max', 'rf_mean',
                    'rf_q75', 'rf_q90', 'rf_recent_mean']].to_string(index=False))
    return rf_stats, rf_long


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — HISTORICAL LANDSLIDE DATA
# ──────────────────────────────────────────────────────────────────────────────
def load_landslide_data(landslide_csv, target_districts=None):
    print("\n" + "=" * 65)
    print("STEP 3: Loading Historical Landslide Records")
    print("=" * 65)

    ls = pd.read_csv(landslide_csv)
    ls['event_date'] = pd.to_datetime(ls['event_date'], infer_datetime_format=True)
    ls['year'] = ls['event_date'].dt.year

    province_to_districts = {
        'Uva':           ['Badulla', 'Monaragala'],
        'Central':       ['Kandy', 'Matale', 'Nuwara Eliya'],
        'Southern':      ['Galle', 'Matara', 'Hambantota'],
        'Sabaragamuwa':  ['Ratnapura', 'Kegalle'],
        'Western':       ['Colombo', 'Gampaha', 'Kalutara'],
        'North Central': ['Anuradhapura', 'Polonnaruwa'],
        'North Western': ['Kurunegala', 'Puttalam'],
    }

    prov_year = ls.groupby(['admin_divi', 'year']).agg(
        ls_events    =('event_id',   'count'),
        ls_fatalities=('fatality_c', 'sum')
    ).reset_index().rename(columns={'admin_divi': 'province'})

    rows = []
    for _, row in prov_year.iterrows():
        dists = province_to_districts.get(str(row['province']).strip(), [])
        if not dists:
            continue
        for d in dists:
            rows.append({
                'district':      d,
                'year':          row['year'],
                'ls_events':     row['ls_events']     / len(dists),
                'ls_fatalities': row['ls_fatalities'] / len(dists),
                'province':      row['province'],
            })

    ls_dist_year = pd.DataFrame(rows)
    ls_dist = ls_dist_year.groupby('district').agg(
        ls_total_events    =('ls_events',     'sum'),
        ls_total_fatalities=('ls_fatalities', 'sum'),
        ls_active_years    =('year',          'nunique')
    ).reset_index()

    if target_districts:
        tn          = {normalise_name(d) for d in target_districts}
        ls_dist     = ls_dist[ls_dist['district'].apply(normalise_name).isin(tn)]
        ls_dist_year= ls_dist_year[ls_dist_year['district'].apply(normalise_name).isin(tn)]

    print(f"  Districts with landslide records: {len(ls_dist)}")
    if not ls_dist.empty:
        print(ls_dist.to_string(index=False))
    return ls_dist, ls_dist_year


# ──────────────────────────────────────────────────────────────────────────────
# STEP 4 — MERGE & PATTERN DISCOVERY
# ──────────────────────────────────────────────────────────────────────────────
def merge_and_discover_patterns(susc_df, rf_stats, ls_dist, rf_long, ls_dist_year):
    print("\n" + "=" * 65)
    print("STEP 4: Merging Data & Pattern Discovery")
    print("=" * 65)

    def norm(s): return str(s).strip().lower().replace('_', ' ')
    susc_df  = susc_df.copy();  susc_df['_key']  = susc_df['district'].apply(norm)
    rf_stats = rf_stats.copy(); rf_stats['_key'] = rf_stats['district'].apply(norm)
    ls_dist  = ls_dist.copy();  ls_dist['_key']  = ls_dist['district'].apply(norm)

    merged = susc_df.merge(rf_stats.drop(columns='district'), on='_key', how='inner')
    merged = merged.merge(ls_dist.drop(columns='district'),   on='_key', how='left')
    merged['ls_total_events']     = merged['ls_total_events'].fillna(0)
    merged['ls_total_fatalities'] = merged['ls_total_fatalities'].fillna(0)
    merged['ls_active_years']     = merged['ls_active_years'].fillna(0)
    merged.drop(columns='_key', inplace=True)

    n = len(merged)
    print(f"  Merged: {n} district(s)")

    feat_cols = [c for c in [
        'wsi', 'pct_high', 'pct_moderate',
        'rf_mean', 'rf_std', 'rf_cv', 'rf_skew',
        'rf_q75', 'rf_q90', 'rf_q95', 'rf_trend',
        'rf_recent_mean', 'ls_total_events'
    ] if c in merged.columns]

    corr_matrix = merged[feat_cols].corr()
    print("\n  Correlation with WSI:")
    wsi_corr = corr_matrix['wsi'].drop('wsi').sort_values(key=abs, ascending=False)
    print(wsi_corr.to_string())

    X        = merged[feat_cols].fillna(merged[feat_cols].mean())
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    max_components = min(len(feat_cols), n - 1)
    n_components   = max(1, max_components)

    pca        = PCA(n_components=n_components)
    pca_coords = pca.fit_transform(X_scaled)
    explained  = pca.explained_variance_ratio_

    print(f"\n  PCA: {n_components} component(s), "
          + "  ".join(f"PC{i+1}={v:.1%}" for i, v in enumerate(explained)))

    col_names   = [f'PC{i+1}' for i in range(n_components)]
    pc_loadings = pd.DataFrame(pca.components_.T, index=feat_cols, columns=col_names)
    print("\n  PCA loadings (PC1, top 6):")
    print(pc_loadings.sort_values('PC1', key=abs, ascending=False).head(6).to_string())

    merged['pca1'] = pca_coords[:, 0]
    merged['pca2'] = pca_coords[:, 1] if n_components >= 2 else 0.0

    if n >= 3:
        sil_scores = {}
        for k in range(2, min(6, n)):
            km    = KMeans(n_clusters=k, random_state=42, n_init=20)
            lbl   = km.fit_predict(X_scaled)
            sil_scores[k] = silhouette_score(X_scaled, lbl)
            print(f"  K={k}  silhouette={sil_scores[k]:.4f}")

        best_k   = max(sil_scores, key=sil_scores.get)
        km_final = KMeans(n_clusters=best_k, random_state=42, n_init=20)
        merged['cluster'] = km_final.fit_predict(X_scaled)
        print(f"\n  Optimal K={best_k} (silhouette={sil_scores[best_k]:.4f})")

        cluster_rank = merged.groupby('cluster')[['wsi', 'rf_mean']].mean()
        cluster_rank['rank_score'] = (
            cluster_rank['wsi'] +
            cluster_rank['rf_mean'] / cluster_rank['rf_mean'].max()
        )
        cluster_rank = cluster_rank['rank_score'].rank().astype(int)
        merged['cluster_ranked'] = merged['cluster'].map(cluster_rank)
    else:
        print(f"\n  [INFO] Only {n} district(s) — K-Means skipped.")
        merged['cluster']        = range(n)
        merged['cluster_ranked'] = range(1, n + 1)

    return merged, corr_matrix, pca, pc_loadings, feat_cols, X_scaled, scaler


# ──────────────────────────────────────────────────────────────────────────────
# STEP 5 — DATA-DRIVEN THRESHOLD IDENTIFICATION
# ──────────────────────────────────────────────────────────────────────────────
def find_rainfall_thresholds(merged, rf_long, ls_dist_year):
    print("\n" + "=" * 65)
    print("STEP 5: Data-Driven Rainfall Threshold Identification")
    print("=" * 65)

    ls_years_by_district = (
        ls_dist_year.groupby('district')['year'].apply(set).to_dict()
    )

    rf_norm = rf_long.copy()
    rf_norm['district'] = rf_norm['district'].str.strip()

    results             = []
    quantile_candidates = np.arange(0.50, 0.96, 0.05)
    active_districts    = [d for d in merged['district'] if d in ls_years_by_district]
    print(f"  Calibration districts: {len(active_districts)}")

    for district in active_districts:
        df_d = rf_norm[rf_norm['district'] == district].dropna(subset=['rainfall_mm'])
        if len(df_d) < 10:
            continue
        df_d = df_d.copy()
        df_d['is_ls_year'] = df_d['year'].isin(ls_years_by_district[district]).astype(int)

        best_q, best_tss = None, -999
        for q in quantile_candidates:
            threshold = df_d['rainfall_mm'].quantile(q)
            predicted = (df_d['rainfall_mm'] >= threshold).astype(int)
            tp  = ((predicted == 1) & (df_d['is_ls_year'] == 1)).sum()
            fp  = ((predicted == 1) & (df_d['is_ls_year'] == 0)).sum()
            tn  = ((predicted == 0) & (df_d['is_ls_year'] == 0)).sum()
            fn  = ((predicted == 0) & (df_d['is_ls_year'] == 1)).sum()
            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
            tss = tpr - fpr
            if tss > best_tss:
                best_tss, best_q = tss, q

        mm = df_d['rainfall_mm'].quantile(best_q)
        results.append({'district': district, 'best_quantile': best_q,
                        'trigger_rf_mm': mm, 'tss': best_tss})
        print(f"  {district:20s}  Q={best_q:.2f}  "
              f"threshold={mm:.1f} mm  TSS={best_tss:.3f}")

    threshold_df = pd.DataFrame(results)
    median_q = threshold_df['best_quantile'].median() if len(threshold_df) > 0 else 0.75
    print(f"\n  Median best quantile: Q{median_q:.2f}")

    def district_trigger(row):
        q_eff = median_q - 0.10 * row['wsi']
        q_eff = max(0.50, min(0.95, q_eff))
        col   = f"rf_q{int(round(q_eff * 100))}"
        return row[col] if col in row.index else row.get('rf_q75', 0)

    merged = merged.copy()
    merged['trigger_rf_mm'] = merged.apply(district_trigger, axis=1)

    print("\n  Trigger thresholds:")
    print(merged[['district', 'wsi', 'trigger_rf_mm']]
          .sort_values('wsi', ascending=False).to_string(index=False))
    return merged, threshold_df


# ──────────────────────────────────────────────────────────────────────────────
# STEP 6 — COMPOSITE RISK SCORE (static, district-level, for calibration only)
# ──────────────────────────────────────────────────────────────────────────────
def classify_risk_static(merged):
    """
    Static (long-run) composite risk — used to calibrate thresholds.
    """
    print("\n" + "=" * 65)
    print("STEP 6: Static Composite Risk (calibration baseline)")
    print("=" * 65)

    def minmax(s):
        rng = s.max() - s.min()
        return (s - s.min()) / rng if rng != 0 else pd.Series(0.5, index=s.index)

    merged = merged.copy()
    merged['norm_wsi'] = minmax(merged['wsi'])
    merged['norm_rf']  = minmax(merged['rf_recent_mean'])
    merged['norm_ls']  = minmax(merged['ls_total_events'])

    merged['composite_risk'] = (
        0.50 * merged['norm_wsi'] +
        0.35 * merged['norm_rf']  +
        0.15 * merged['norm_ls']
    )

    n = len(merged)
    if n >= 4:
        q33 = merged['composite_risk'].quantile(0.33)
        q66 = merged['composite_risk'].quantile(0.66)
        q85 = merged['composite_risk'].quantile(0.85)

        def assign_class(v):
            if v < q33:   return 1, 'Low'
            elif v < q66: return 2, 'Moderate'
            elif v < q85: return 3, 'High'
            else:         return 4, 'Very High'
    else:
        scores_sorted = sorted(merged['composite_risk'].unique())
        classes       = ['Low', 'Moderate', 'High', 'Very High']
        class_map     = {s: (i+1, classes[min(i, len(classes)-1)])
                         for i, s in enumerate(scores_sorted)}
        q33 = scores_sorted[0]
        q66 = scores_sorted[0]
        q85 = scores_sorted[-1] if len(scores_sorted) > 1 else scores_sorted[0]
        def assign_class(v):
            return class_map.get(v, (1, 'Low'))

    merged[['risk_id', 'risk_class']] = merged['composite_risk'].apply(
        lambda v: pd.Series(assign_class(v))
    )
    thresholds = (q33, q66, q85)

    print(merged[['district', 'wsi', 'rf_recent_mean', 'composite_risk',
                  'risk_class']].sort_values('composite_risk', ascending=False)
          .to_string(index=False))
    return merged, thresholds


# ──────────────────────────────────────────────────────────────────────────────
# STEP 7 — VISUALISATIONS
# ──────────────────────────────────────────────────────────────────────────────
def plot_results(merged, corr_matrix, feat_cols, rf_long, thresholds, out_dir):
    print("\n" + "=" * 65)
    print("STEP 7: Generating Figures")
    print("=" * 65)

    q33, q66, q85 = thresholds
    n             = len(merged)
    districts     = merged['district'].tolist()

    merged = merged.copy()
    merged['lon'] = merged['district'].map(
        lambda d: DISTRICT_COORDS.get(d, (80.5, 7.5))[0])
    merged['lat'] = merged['district'].map(
        lambda d: DISTRICT_COORDS.get(d, (80.5, 7.5))[1])

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        f'Sri Lanka — Landslide Risk Prediction Model (static baseline)\n'
        f'Districts: {", ".join(districts)}',
        fontsize=15, fontweight='bold', y=1.00
    )
    gs = fig.add_gridspec(3, 3, hspace=0.48, wspace=0.38)

    ax1 = fig.add_subplot(gs[0, 0])
    for cls, color in CMAP.items():
        sub = merged[merged['risk_class'] == cls]
        if sub.empty: continue
        ax1.scatter(sub['lon'], sub['lat'], c=color, s=200, label=cls,
                    edgecolors='black', linewidth=0.8, zorder=3)
    for _, r in merged.iterrows():
        ax1.annotate(r['district'], (r['lon'], r['lat']),
                     fontsize=8, ha='center', va='bottom',
                     xytext=(0, 8), textcoords='offset points', fontweight='bold')
    ax1.set_title('Risk Classification Map (baseline)', fontweight='bold')
    ax1.set_xlabel('Longitude'); ax1.set_ylabel('Latitude')
    ax1.legend(title='Risk', fontsize=8, markerscale=0.9)
    ax1.grid(True, alpha=0.3); ax1.set_facecolor('#ddeeff')

    ax2 = fig.add_subplot(gs[0, 1])
    sd = merged.sort_values('composite_risk', ascending=True)
    ax2.barh(sd['district'], sd['composite_risk'],
             color=[CMAP[c] for c in sd['risk_class']],
             edgecolor='grey', linewidth=0.5, height=0.5)
    for q, lbl, col in [(q33,'Low|Mod','orange'),(q66,'Mod|High','darkorange'),
                         (q85,'High|VH','red')]:
        ax2.axvline(q, color=col, ls='--', lw=1.2, label=f'{lbl} ({q:.3f})')
    for _, r in sd.iterrows():
        ax2.text(r['composite_risk']+0.005, r['district'],
                 f"{r['composite_risk']:.3f}", va='center', fontsize=9)
    ax2.set_title('Composite Risk Score\n(WSI 50% + Rainfall 35% + Events 15%)',
                  fontweight='bold')
    ax2.set_xlabel('Score (0–1)')
    ax2.tick_params(axis='y', labelsize=10); ax2.legend(fontsize=7)

    ax3 = fig.add_subplot(gs[0, 2])
    sd2 = merged.sort_values('wsi', ascending=True)
    ax3.barh(sd2['district'], sd2['wsi'],
             color=[CMAP[c] for c in sd2['risk_class']],
             edgecolor='grey', linewidth=0.5, height=0.5)
    for _, r in sd2.iterrows():
        ax3.text(r['wsi']+0.002, r['district'],
                 f"{r['wsi']:.4f}", va='center', fontsize=9)
    ax3.set_title('Weighted Susceptibility Index', fontweight='bold')
    ax3.set_xlabel('WSI (0–1)')
    ax3.tick_params(axis='y', labelsize=10)

    ax4 = fig.add_subplot(gs[1, 0])
    mask = np.zeros_like(corr_matrix, dtype=bool)
    mask[np.triu_indices_from(mask)] = True
    sns.heatmap(corr_matrix, mask=mask, ax=ax4, cmap='RdYlGn',
                center=0, annot=True, fmt='.2f', annot_kws={'size': 7},
                linewidths=0.4, cbar_kws={'shrink': 0.7})
    ax4.set_title('Feature Correlation Matrix', fontweight='bold')
    ax4.tick_params(axis='both', labelsize=6)

    ax5 = fig.add_subplot(gs[1, 1])
    if n >= 2:
        for cls, color in CMAP.items():
            sub = merged[merged['risk_class'] == cls]
            if sub.empty: continue
            ax5.scatter(sub['pca1'], sub['pca2'], c=color, s=150, label=cls,
                        edgecolors='black', linewidth=0.6, zorder=3)
            for _, r in sub.iterrows():
                ax5.annotate(r['district'], (r['pca1'], r['pca2']),
                             fontsize=9, xytext=(4, 4), textcoords='offset points')
        ax5.set_xlabel('PC1'); ax5.set_ylabel('PC2')
        ax5.set_title('PCA — Feature Space', fontweight='bold')
        ax5.legend(fontsize=8); ax5.grid(True, alpha=0.3)

    ax6 = fig.add_subplot(gs[1, 2])
    sd3     = merged.sort_values('wsi', ascending=True)
    bottoms = np.zeros(len(sd3))
    for col, color, label in [
        ('pct_very_low','#2ecc71','Very Low'), ('pct_low','#f1c40f','Low'),
        ('pct_moderate','#e67e22','Moderate'), ('pct_high','#c0392b','High'),
    ]:
        if col in sd3.columns:
            ax6.barh(sd3['district'], sd3[col], left=bottoms,
                     color=color, label=label, edgecolor='white',
                     linewidth=0.3, height=0.5)
            bottoms += sd3[col].values
    ax6.set_title('Susceptibility Class Area %', fontweight='bold')
    ax6.set_xlabel('Area (%)'); ax6.tick_params(axis='y', labelsize=10)
    ax6.legend(fontsize=8, loc='lower right')

    ax7 = fig.add_subplot(gs[2, 0])
    for d in districts:
        ts  = rf_long[rf_long['district'] == d].sort_values('year')
        if ts.empty: continue
        rc  = merged[merged['district'] == d]['risk_class'].values
        col = CMAP.get(rc[0], 'steelblue') if len(rc) else 'steelblue'
        ax7.plot(ts['year'], ts['rainfall_mm'], label=d, color=col, lw=2)
    ax7.set_title('Annual Rainfall Time Series', fontweight='bold')
    ax7.set_xlabel('Year'); ax7.set_ylabel('Rainfall (mm)')
    ax7.legend(fontsize=9); ax7.grid(True, alpha=0.3)

    ax8 = fig.add_subplot(gs[2, 1])
    bp_data   = [rf_long[rf_long['district']==d]['rainfall_mm'].dropna().values
                 for d in districts]
    bp_colors = [CMAP.get(
        merged[merged['district']==d]['risk_class'].values[0]
        if len(merged[merged['district']==d]) else '', 'grey'
    ) for d in districts]
    bp = ax8.boxplot(bp_data, labels=districts, patch_artist=True)
    for patch, col in zip(bp['boxes'], bp_colors):
        patch.set_facecolor(col); patch.set_alpha(0.8)
    ax8.set_title('Rainfall Distribution', fontweight='bold')
    ax8.set_ylabel('Annual Rainfall (mm)'); ax8.tick_params(axis='x', labelsize=10)
    ax8.grid(axis='y', alpha=0.3)

    ax9 = fig.add_subplot(gs[2, 2])
    for cls, color in CMAP.items():
        sub = merged[merged['risk_class'] == cls]
        if sub.empty: continue
        ax9.scatter(sub['wsi'], sub['trigger_rf_mm'], c=color, s=150,
                    label=cls, edgecolors='black', linewidth=0.6)
        for _, r in sub.iterrows():
            ax9.annotate(
                f"{r['district']}\n{r['trigger_rf_mm']:.0f} mm",
                (r['wsi'], r['trigger_rf_mm']),
                fontsize=8, xytext=(6, 4), textcoords='offset points'
            )
    ax9.set_xlabel('WSI'); ax9.set_ylabel('Trigger Threshold (mm/yr)')
    ax9.set_title('Dynamic Trigger Threshold vs WSI', fontweight='bold')
    ax9.legend(fontsize=8); ax9.grid(True, alpha=0.3)

    fig.tight_layout()
    out_png = os.path.join(out_dir, 'landslide_risk_model_v3_baseline.png')
    plt.savefig(out_png, dpi=150, bbox_inches='tight')
    print(f"  Figure saved: {out_png}")
    plt.close()


# ──────────────────────────────────────────────────────────────────────────────
# STEP 8 (NEW) — YEAR-WISE RISK COMPUTATION + POLYGON SHP OUTPUT
# ──────────────────────────────────────────────────────────────────────────────
def build_yearwise_risk(merged_static, rf_long, dist_geom,
                        year_start=None, year_end=None):
    """
    For every (district, year) pair in rf_long, compute a year-specific
    composite risk score and assign a risk class.

    FORMULA:
        annual_rf_norm = (rf_mm − district_rf_min) / (district_rf_max − district_rf_min)
        composite_yr   = 0.50 * wsi_norm
                       + 0.35 * annual_rf_norm
                       + 0.15 * ls_events_norm

    wsi_norm and ls_events_norm are static (do not change year-to-year).
    Only the rainfall component varies per year.

    Risk class thresholds are derived from the DISTRIBUTION of all
    (district × year) composite scores, so they are globally consistent.
    """
    print("\n" + "=" * 65)
    print("STEP 8 (NEW): Building Year-Wise Risk — Polygon SHP")
    print("=" * 65)

    # ── per-district min/max rainfall (for annual normalisation) ──────────
    rf_range = rf_long.groupby('district')['rainfall_mm'].agg(['min', 'max'])
    rf_range.columns = ['rf_annual_min', 'rf_annual_max']
    rf_range = rf_range.reset_index()

    # ── static per-district attributes from merged_static ─────────────────
    static_cols = [
        'district', 'wsi', 'pct_very_low', 'pct_low', 'pct_moderate',
        'pct_high', 'total_area_km2', 'ls_total_events',
        'cluster_ranked', 'trigger_rf_mm',
        'rf_mean', 'rf_q75', 'rf_q90',
    ]
    static_cols = [c for c in static_cols if c in merged_static.columns]
    static_df   = merged_static[static_cols].copy()

    # ── min-max scalers for wsi and ls_events (across districts) ──────────
    def minmax_col(series):
        lo, hi = series.min(), series.max()
        if hi == lo:
            return pd.Series(0.5, index=series.index)
        return (series - lo) / (hi - lo)

    static_df['wsi_norm'] = minmax_col(static_df['wsi'])
    static_df['ls_norm']  = minmax_col(static_df['ls_total_events'])

    # ── merge rainfall long-form with static data ─────────────────────────
    rf_work = rf_long.copy()
    rf_work['district'] = rf_work['district'].str.strip()

    # Apply year filter
    if year_start:
        rf_work = rf_work[rf_work['year'] >= year_start]
    if year_end:
        rf_work = rf_work[rf_work['year'] <= year_end]

    rf_work = rf_work.merge(rf_range, on='district', how='left')
    rf_work = rf_work.merge(
        static_df[['district', 'wsi_norm', 'ls_norm']],
        on='district', how='left'
    )

    # ── annual rainfall normalised within each district's historic range ──
    rf_rng = rf_work['rf_annual_max'] - rf_work['rf_annual_min']
    rf_work['rf_annual_norm'] = np.where(
        rf_rng > 0,
        (rf_work['rainfall_mm'] - rf_work['rf_annual_min']) / rf_rng,
        0.5
    ).clip(0, 1)

    # ── year-specific composite score ─────────────────────────────────────
    rf_work['comp_yr'] = (
        0.50 * rf_work['wsi_norm'] +
        0.35 * rf_work['rf_annual_norm'] +
        0.15 * rf_work['ls_norm']
    )

    # ── global quantile thresholds across all district×year scores ────────
    q33 = rf_work['comp_yr'].quantile(0.33)
    q66 = rf_work['comp_yr'].quantile(0.66)
    q85 = rf_work['comp_yr'].quantile(0.85)
    print(f"  Global thresholds:  Low < {q33:.4f}  "
          f"Moderate {q33:.4f}–{q66:.4f}  "
          f"High {q66:.4f}–{q85:.4f}  VH ≥ {q85:.4f}")

    def assign_class(v):
        if v < q33:   return 1, 'Low'
        elif v < q66: return 2, 'Moderate'
        elif v < q85: return 3, 'High'
        else:         return 4, 'Very High'

    rf_work[['risk_id', 'risk_class']] = rf_work['comp_yr'].apply(
        lambda v: pd.Series(assign_class(v))
    )

    # ── merge all static attributes back for the output SHP ──────────────
    all_static = static_df.drop(columns=['wsi_norm', 'ls_norm'])
    rf_work = rf_work.merge(all_static, on='district', how='left')

    total_rows = len(rf_work)
    years      = sorted(rf_work['year'].unique())
    print(f"  Year range : {years[0]} – {years[-1]}  ({len(years)} years)")
    print(f"  Districts  : {sorted(rf_work['district'].unique())}")
    print(f"  Total rows : {total_rows}  (= {len(years)} years × "
          f"{len(rf_work['district'].unique())} districts)")

    # ── risk class distribution ───────────────────────────────────────────
    print("\n  Risk class distribution across all district-years:")
    print(rf_work['risk_class'].value_counts().to_string())

    return rf_work, (q33, q66, q85)


# ──────────────────────────────────────────────────────────────────────────────
# STEP 9 — SAVE YEAR-WISE POLYGON SHP  (one polygon per district × year)
# ──────────────────────────────────────────────────────────────────────────────

def _write_qml_style(shp_path, risk_colors):
    """
    Write a QGIS .qml sidecar file next to the shapefile so that when
    the layer is loaded in QGIS it automatically shows categorized colours
    based on the 'risk_class' field — no manual styling needed.

    Each category gets:
      • solid fill colour  (from risk_colors dict)
      • no outline stroke  (so overlapping year-polygons don't show black lines)

    The QML targets the field name 'risk_class' (≤10 chars, safe for DBF).
    """

    # Convert hex  #rrggbb  →  R,G,B  strings that QML expects
    def hex_to_rgb_str(h):
        h = h.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"{r},{g},{b},255"

    # Build one <category> + <symbol> block per risk class
    categories_xml = ""
    symbols_xml    = ""

    ordered_classes = ['Low', 'Moderate', 'High', 'Very High']
    for idx, cls in enumerate(ordered_classes):
        hex_col = risk_colors.get(cls, '#cccccc')
        rgba    = hex_to_rgb_str(hex_col)

        categories_xml += f"""
      <category render="true" symbol="{idx}" value="{cls}" label="{cls}"/>"""

        symbols_xml += f"""
      <symbol name="{idx}" type="fill" clip_to_extent="1" alpha="1" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleFill" pass="0" enabled="1" locked="0">
          <Option type="Map">
            <Option name="color"          type="QString" value="{rgba}"/>
            <Option name="style"          type="QString" value="solid"/>
            <Option name="outline_style"  type="QString" value="no"/>
            <Option name="outline_width"  type="QString" value="0"/>
            <Option name="joinstyle"      type="QString" value="miter"/>
            <Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
          </Option>
          <prop k="color"         v="{rgba}"/>
          <prop k="style"         v="solid"/>
          <prop k="outline_style" v="no"/>
          <prop k="outline_width" v="0"/>
        </layer>
      </symbol>"""

    qml_content = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.0" styleCategories="AllStyleCategories">
  <renderer-v2 type="categorizedSymbol" attr="risk_class" enableorderby="0" forceraster="0" symbollevels="0">
    <categories>{categories_xml}
    </categories>
    <symbols>{symbols_xml}
    </symbols>
    <rotation/>
    <sizescale/>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
"""
    qml_path = shp_path.replace('.shp', '.qml')
    with open(qml_path, 'w', encoding='utf-8') as f:
        f.write(qml_content)
    return qml_path


def save_yearwise_shapefile(rf_work, dist_geom, out_dir, target_districts):
    """
    Build a GeoDataFrame where:
        • geometry  = the dissolved district polygon (same every year)
        • one row   = one (district, year) combination

    Output folder structure:
        out_dir/
         ├── Kandy/
         │    ├── LandslideRisk_YearWise_Kandy.shp
         │    ├── LandslideRisk_YearWise_Kandy.dbf
         │    ├── LandslideRisk_YearWise_Kandy.shx
         │    ├── LandslideRisk_YearWise_Kandy.qml   ← QGIS auto-style
         │    └── LandslideRisk_YearWise_Kandy.csv
         └── Nuwara_Eliya/
              ├── LandslideRisk_YearWise_Nuwara_Eliya.shp
              ├── LandslideRisk_YearWise_Nuwara_Eliya.qml
              └── LandslideRisk_YearWise_Nuwara_Eliya.csv

    Attribute field names are kept ≤ 10 chars (DBF limit).

    WHY THE BLACK DOTS HAPPENED:
        All 123 year-rows share the EXACT same polygon geometry and are
        stacked on top of each other. QGIS rendered all of them with its
        default purple single-symbol style, and the polygon vertex markers
        showed through as black dots.

    FIX:
        1. outline_style = "no"  in the QML  →  no border lines / vertex dots
        2. A .qml sidecar file  →  QGIS auto-loads categorized colours by
           risk_class when the .shp is opened, replacing the purple default.
    """
    print("\n" + "=" * 65)
    print("STEP 9: Saving Year-Wise Polygon Shapefiles (per district)")
    print("=" * 65)

    # ── Risk colour map ───────────────────────────────────────────────────
    risk_colors = {
        'Low':       '#2ecc71',   # green
        'Moderate':  '#f39c12',   # amber
        'High':      '#e67e22',   # orange
        'Very High': '#c0392b',   # red
    }

    # ── Column rename map (output ≤ 10 chars for DBF) ────────────────────
    col_map = {
        'district':       'district',
        'year':           'year',
        'risk_class':     'risk_class',
        'risk_id':        'risk_id',
        'comp_yr':        'comp_risk',
        'wsi':            'wsi',
        'pct_very_low':   'pct_vlow',
        'pct_low':        'pct_low',
        'pct_moderate':   'pct_mod',
        'pct_high':       'pct_high',
        'total_area_km2': 'total_km2',
        'rainfall_mm':    'rf_mm',
        'rf_mean':        'rf_mean',
        'rf_q75':         'rf_q75',
        'rf_q90':         'rf_q90',
        'trigger_rf_mm':  'trig_rf',
        'ls_total_events':'ls_events',
        'cluster_ranked': 'cluster',
    }

    # Select only columns that exist in rf_work
    valid_src = [c for c in col_map if c in rf_work.columns]
    out_df    = rf_work[valid_src].copy()
    out_df    = out_df.rename(columns={c: col_map[c] for c in valid_src})

    # ── Add hex colour column (stored in DBF for reference) ───────────────
    # Uses .apply(dict.get)  — works on ALL pandas versions
    out_df['color'] = out_df['risk_class'].apply(
        lambda x: risk_colors.get(str(x), '#cccccc')
    )

    # ── Geometry helper ───────────────────────────────────────────────────
    def get_geom(district_name):
        if district_name in dist_geom:
            return dist_geom[district_name]
        lon, lat = DISTRICT_COORDS.get(district_name, (80.5, 7.5))
        return Point(lon, lat).buffer(0.15)

    # ── Attach geometry and build master GeoDataFrame ─────────────────────
    geometries = out_df['district'].apply(get_geom).values
    gdf        = gpd.GeoDataFrame(out_df, geometry=geometries, crs='EPSG:4326')
    gdf        = gdf.sort_values(['district', 'year']).reset_index(drop=True)

    # ── Save one sub-folder + SHP + QML + CSV per district ────────────────
    districts = sorted(gdf['district'].unique())

    for dist in districts:
        dist_safe   = dist.replace(' ', '_')
        dist_folder = os.path.join(out_dir, dist_safe)
        os.makedirs(dist_folder, exist_ok=True)

        gdf_dist = gdf[gdf['district'] == dist].copy()

        shp_path = os.path.join(dist_folder,
                    f"LandslideRisk_YearWise_{dist_safe}.shp")
        csv_path = os.path.join(dist_folder,
                    f"LandslideRisk_YearWise_{dist_safe}.csv")

        # ── Save shapefile (.shp / .dbf / .shx / .prj) ───────────────────
        gdf_dist.to_file(shp_path)

        # ── Write QGIS style sidecar (.qml) ──────────────────────────────
        # This is the KEY FIX:
        #   • Tells QGIS to colour polygons by risk_class automatically
        #   • outline_style="no" removes the black vertex dots / border lines
        qml_path = _write_qml_style(shp_path, risk_colors)

        # ── Save CSV (no geometry column) ─────────────────────────────────
        gdf_dist.drop(columns='geometry').to_csv(
            csv_path, index=False, float_format='%.4f'
        )

        n_rows       = len(gdf_dist)
        n_years      = gdf_dist['year'].nunique()
        risk_summary = gdf_dist['risk_class'].value_counts().to_dict()
        print(f"  ✓ {dist:20s}  ({n_years} years, {n_rows} rows)")
        print(f"      SHP : {shp_path}")
        print(f"      QML : {qml_path}  ← QGIS auto-style (categorized by risk_class)")
        print(f"      CSV : {csv_path}")
        print(f"      Risk breakdown: {risk_summary}")

    print(f"\n  CRS        : EPSG:4326")
    print(f"  Total rows : {len(gdf)}  "
          f"({gdf['district'].nunique()} districts × {gdf['year'].nunique()} years)")
    print(f"  Attributes : {[c for c in gdf.columns if c != 'geometry']}")
    print(f"\n  NOTE: Open the .shp in QGIS — the .qml sidecar will auto-apply")
    print(f"        categorized colours (Green=Low / Amber=Moderate /")
    print(f"        Orange=High / Red=Very High) with no border lines.")
    print(f"        Use the 'year' field with a filter/slider to browse years.")

    # ── Quick sample preview ──────────────────────────────────────────────
    print("\n  Sample output (first 5 / last 5 rows):")
    preview_cols = ['district', 'year', 'risk_class', 'comp_risk', 'rf_mm', 'wsi']
    preview_cols = [c for c in preview_cols if c in gdf.columns]
    print(pd.concat([gdf[preview_cols].head(5),
                     gdf[preview_cols].tail(5)]).to_string(index=False))

    return gdf


# ──────────────────────────────────────────────────────────────────────────────
# STEP 10 — YEAR-WISE SUMMARY CHART
# ──────────────────────────────────────────────────────────────────────────────
def plot_yearwise_summary(gdf_yearwise, out_dir):
    print("\n" + "=" * 65)
    print("STEP 10: Generating Year-Wise Summary Charts")
    print("=" * 65)

    districts = sorted(gdf_yearwise['district'].unique())
    n_d       = len(districts)

    fig, axes = plt.subplots(
        n_d, 1, figsize=(18, 4 * n_d), sharex=True,
        squeeze=False
    )
    fig.suptitle('Sri Lanka — Year-Wise Landslide Risk per District',
                 fontsize=15, fontweight='bold')

    for i, dist in enumerate(districts):
        ax  = axes[i][0]
        sub = gdf_yearwise[gdf_yearwise['district'] == dist].sort_values('year')

        # Shade background by risk class
        for _, row in sub.iterrows():
            ax.axvspan(row['year'] - 0.5, row['year'] + 0.5,
                       color=CMAP.get(row['risk_class'], 'grey'), alpha=0.35)

        # Composite risk line
        ax.plot(sub['year'], sub['comp_risk'], color='black',
                lw=1.5, label='Composite Risk', zorder=5)

        # Rainfall secondary axis
        ax2 = ax.twinx()
        if 'rf_mm' in sub.columns:
            ax2.bar(sub['year'], sub['rf_mm'], color='steelblue',
                    alpha=0.25, label='Rainfall (mm)')
            ax2.set_ylabel('Rainfall (mm)', color='steelblue', fontsize=8)
            ax2.tick_params(axis='y', labelcolor='steelblue', labelsize=7)

        # Trigger threshold line
        if 'trig_rf' in sub.columns:
            trig = sub['trig_rf'].iloc[0]
            ax2.axhline(trig, color='red', ls='--', lw=1,
                        label=f'Trigger {trig:.0f} mm')

        ax.set_ylabel('Composite Risk', fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.set_title(dist, fontweight='bold', fontsize=11, loc='left')
        ax.grid(axis='y', alpha=0.3)

        # Legend patches
        patches = [mpatches.Patch(color=c, label=l, alpha=0.7)
                   for l, c in CMAP.items()]
        ax.legend(handles=patches, loc='upper left', fontsize=7,
                  title='Risk Class', title_fontsize=7)

    axes[-1][0].set_xlabel('Year', fontsize=11)
    fig.tight_layout()

    out_png = os.path.join(out_dir, 'landslide_risk_model_v3_yearwise.png')
    plt.savefig(out_png, dpi=150, bbox_inches='tight')
    print(f"  Figure saved: {out_png}")
    plt.close()


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    target_districts = (
        [d.strip().title().replace('_', ' ') for d in args.districts]
        if args.districts else None
    )

    if target_districts:
        print(f"\n  ► Running for selected districts: {target_districts}")
    else:
        print("\n  ► Running for ALL districts")

    # ── Steps 1–3: read raw data ──────────────────────────────────────────
    susc_df, dist_geom        = read_susceptibility_shapefiles(
                                    args.shp_root, target_districts)
    rf_stats, rf_long         = compute_rainfall_stats(
                                    args.rainfall, target_districts)
    ls_dist, ls_dist_year     = load_landslide_data(
                                    args.landslide, target_districts)

    # ── Steps 4–6: analysis + static baseline ────────────────────────────
    merged_static, corr_matrix, pca, pc_loadings, feat_cols, X_scaled, scaler = \
        merge_and_discover_patterns(
            susc_df, rf_stats, ls_dist, rf_long, ls_dist_year
        )

    merged_static, threshold_df = find_rainfall_thresholds(
        merged_static, rf_long, ls_dist_year
    )
    merged_static, thresholds_static = classify_risk_static(merged_static)

    # ── Step 7: baseline visualisation ───────────────────────────────────
    plot_results(
        merged_static, corr_matrix, feat_cols, rf_long,
        thresholds_static, args.out_dir
    )

    # ── Steps 8–9 (NEW): year-wise risk polygons ─────────────────────────
    rf_yearwise, yw_thresholds = build_yearwise_risk(
        merged_static, rf_long, dist_geom,
        year_start=args.year_start,
        year_end=args.year_end,
    )

    gdf_yearwise = save_yearwise_shapefile(
        rf_yearwise, dist_geom, args.out_dir, target_districts
    )

    # ── Step 10: year-wise summary plot ───────────────────────────────────
    plot_yearwise_summary(gdf_yearwise, args.out_dir)

    # ── Final summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("ALL DONE")
    print("=" * 65)
    print(f"  Outputs in: {args.out_dir}")
    print(f"\n  Output folder structure:")
    for dist in sorted(gdf_yearwise['district'].unique()):
        dist_safe = dist.replace(' ', '_')
        print(f"    {dist_safe}/")
        print(f"      LandslideRisk_YearWise_{dist_safe}.shp")
        print(f"      LandslideRisk_YearWise_{dist_safe}.dbf")
        print(f"      LandslideRisk_YearWise_{dist_safe}.shx")
        print(f"      LandslideRisk_YearWise_{dist_safe}.csv")
    print(f"\n  Figures:")
    print(f"    landslide_risk_model_v3_baseline.png")
    print(f"    landslide_risk_model_v3_yearwise.png")


if __name__ == '__main__':
    main()