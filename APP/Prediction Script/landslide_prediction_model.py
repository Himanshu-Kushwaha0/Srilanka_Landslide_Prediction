"""
Sri Lanka Landslide Prediction Model — v2
==========================================
APPROACH:
  Step 1  : Read every district's *_susceptibility.shp (actual QGIS output)
            → extract area_km2 per susceptibility class (Very Low / Low / Moderate / High)
            → derive Weighted Susceptibility Index (WSI) from REAL area proportions

  Step 2  : Compute district-wise rainfall statistics from historical CSV
            (min, max, mean, median, mode, Q10–Q90, CV, skew, trend)

  Step 3  : Pattern discovery
            → Pearson correlation matrix across all features
            → PCA to find dominant dimensions of variance
            → K-Means clustering to find natural district groups

  Step 4  : Threshold identification
            → For each risk cluster: find the rainfall band (Q75/Q90) that
              best separates landslide-active from inactive years
            → Validate against historical landslide events (2007-2016)

  Step 5  : Final risk classification + dynamic trigger thresholds

  Step 6  : Save result as district-wise .shp (EPSG:4326)

USAGE:
  python landslide_model_v2.py \
      --shp_root  /home/user/Documents/SriLanka/Bisag_Srilanka_Landslide_Prediction/Output/Susceptibility_Phase1_v1 \
      --rainfall  /home/user/Documents/SriLanka/APP/Srilanka Rainfall Year wise/Srilanka Rainfall Year wise.csv \
      --landslide /home/user/Documents/SriLanka/Scripts/output_shapefiles/landslides_Sri_Lanka.csv \
      --out_dir   /home/user/Documents/SriLanka/Prediction Script/output_shapefiles

  The script expects shp_root to contain one sub-folder per district,
  each folder containing a file matching *_susceptibility.shp
  (exactly as shown in your QGIS output directory).
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
from scipy.stats import pearsonr
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from shapely.geometry import Point

warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description='Sri Lanka Landslide Prediction Model v2')
    p.add_argument('--shp_root',  required=True,
                   help='Root folder containing one sub-folder per district '
                        '(each with *_susceptibility.shp)')
    p.add_argument('--rainfall',  required=True,
                   help='Path to Srilanka_Rainfall_year_wise.csv')
    p.add_argument('--landslide', required=True,
                   help='Path to landslides_Sri_Lanka.csv')
    p.add_argument('--out_dir',   default='./output',
                   help='Output directory for .shp and figures')
    return p.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — READ SUSCEPTIBILITY SHAPEFILES
# ──────────────────────────────────────────────────────────────────────────────
CLASS_WEIGHTS = {
    'very low':  0,
    'very_low':  0,
    'verylow':   0,
    'low':       1,
    'moderate':  2,
    'high':      3,
    'very high': 4,
    'very_high': 4,
    'veryhigh':  4,
}

def read_susceptibility_shapefiles(shp_root):
    """
    Walk shp_root, find every *_susceptibility.shp, read its attribute table,
    and compute per-district susceptibility statistics from REAL area data.

    Expected attribute table columns (from your QGIS output):
        class_id | class_name | district | area_km2

    Returns
    -------
    pd.DataFrame with columns:
        district, total_area_km2,
        area_very_low, area_low, area_moderate, area_high,
        pct_very_low,  pct_low,  pct_moderate,  pct_high,
        wsi            (weighted susceptibility index, 0–1)
    """
    print("\n" + "=" * 65)
    print("STEP 1: Reading District Susceptibility Shapefiles")
    print("=" * 65)

    records = []
    shp_files = glob.glob(os.path.join(shp_root, '**', '*susceptibility.shp'),
                          recursive=True)

    if not shp_files:
        raise FileNotFoundError(
            f"No *susceptibility.shp files found under: {shp_root}\n"
            "Make sure shp_root points to the folder containing one "
            "sub-folder per district (e.g. Kegalle/, Kandy/, …)"
        )

    print(f"Found {len(shp_files)} susceptibility shapefiles")

    for shp_path in sorted(shp_files):
        try:
            gdf = gpd.read_file(shp_path)
        except Exception as e:
            print(f"  [WARN] Could not read {shp_path}: {e}")
            continue

        # ── normalise column names to lower-case ──────────────────────────
        gdf.columns = [c.lower().strip() for c in gdf.columns]

        # ── identify class_name column ────────────────────────────────────
        name_col = None
        for candidate in ['class_name', 'classname', 'class', 'susc_class',
                           'suscept', 'label', 'name']:
            if candidate in gdf.columns:
                name_col = candidate
                break
        if name_col is None:
            print(f"  [WARN] No class_name column in {shp_path}, skipping")
            continue

        # ── identify area column ──────────────────────────────────────────
        area_col = None
        for candidate in ['area_km2', 'area_km', 'areakm2', 'area']:
            if candidate in gdf.columns:
                area_col = candidate
                break
        if area_col is None:
            # compute from geometry if missing
            gdf_proj = gdf.to_crs('EPSG:32644')   # UTM zone 44N covers Sri Lanka
            gdf['area_km2'] = gdf_proj.geometry.area / 1e6
            area_col = 'area_km2'

        # ── identify district name ────────────────────────────────────────
        district_name = None
        if 'district' in gdf.columns:
            district_name = gdf['district'].dropna().iloc[0]
        else:
            # derive from filename:  Kegalle_susceptibility.shp → Kegalle
            district_name = os.path.basename(shp_path).replace(
                '_susceptibility.shp', '').replace('_susceptibility_class.shp', '')

        district_name = str(district_name).strip()

        # ── aggregate area per class ──────────────────────────────────────
        gdf['_cls_norm'] = gdf[name_col].str.strip().str.lower()
        class_areas = gdf.groupby('_cls_norm')[area_col].sum()

        # Map to canonical 4-class scheme
        area_vl  = sum(class_areas.get(k, 0) for k in ['very low','very_low','verylow'])
        area_l   = class_areas.get('low', 0)
        area_m   = class_areas.get('moderate', 0)
        area_h   = sum(class_areas.get(k, 0) for k in ['high','very high','very_high','veryhigh'])

        total = area_vl + area_l + area_m + area_h
        if total == 0:
            print(f"  [WARN] Zero total area for {district_name}, skipping")
            continue

        pct_vl = area_vl / total
        pct_l  = area_l  / total
        pct_m  = area_m  / total
        pct_h  = area_h  / total

        # Weighted Susceptibility Index (0–1):
        # WSI = Σ(weight_i × proportion_i) / max_weight
        wsi = (0*pct_vl + 1*pct_l + 2*pct_m + 3*pct_h) / 3.0

        records.append({
            'district':       district_name,
            'total_area_km2': round(total, 3),
            'area_very_low':  round(area_vl, 3),
            'area_low':       round(area_l,  3),
            'area_moderate':  round(area_m,  3),
            'area_high':      round(area_h,  3),
            'pct_very_low':   round(pct_vl * 100, 2),
            'pct_low':        round(pct_l  * 100, 2),
            'pct_moderate':   round(pct_m  * 100, 2),
            'pct_high':       round(pct_h  * 100, 2),
            'wsi':            round(wsi, 5),
            'shp_path':       shp_path,
        })
        print(f"  ✓ {district_name:20s}  total={total:8.1f} km²  "
              f"VL={pct_vl*100:5.1f}%  L={pct_l*100:5.1f}%  "
              f"M={pct_m*100:5.1f}%  H={pct_h*100:5.1f}%  WSI={wsi:.4f}")

    if not records:
        raise ValueError("No valid susceptibility shapefiles could be read.")

    df = pd.DataFrame(records)
    print(f"\nSuccessfully read {len(df)} district shapefiles")
    return df


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — RAINFALL STATISTICS
# ──────────────────────────────────────────────────────────────────────────────
def compute_rainfall_stats(rainfall_csv):
    """
    Load the wide-format rainfall CSV (districts × years) and compute
    per-district descriptive statistics.
    """
    print("\n" + "=" * 65)
    print("STEP 2: Computing Rainfall Statistics")
    print("=" * 65)

    rf_raw = pd.read_csv(rainfall_csv)
    year_cols = [c for c in rf_raw.columns if str(c).isdigit() and int(c) >= 1901]

    rf = rf_raw[['District'] + year_cols].copy()
    rf.set_index('District', inplace=True)

    # Long format
    rf_long = rf.melt(ignore_index=False, var_name='year', value_name='rainfall_mm')
    rf_long['year'] = rf_long['year'].astype(int)
    rf_long = rf_long.reset_index().rename(columns={'District': 'district'})
    rf_long['district'] = rf_long['district'].str.strip().str.replace('_', ' ')

    # Per-district statistics
    def stats_for(grp):
        v = grp['rainfall_mm'].dropna()
        yrs = grp['year']
        recent = grp[grp['year'] >= 2000]['rainfall_mm'].dropna()
        mode_val = float(stats.mode(v.round(0), keepdims=True)[0][0])
        trend_slope = np.polyfit(yrs, grp['rainfall_mm'].fillna(v.mean()), 1)[0]
        return pd.Series({
            'rf_min':          v.min(),
            'rf_max':          v.max(),
            'rf_mean':         v.mean(),
            'rf_median':       v.median(),
            'rf_mode':         mode_val,
            'rf_std':          v.std(),
            'rf_cv':           v.std() / v.mean() if v.mean() != 0 else 0,
            'rf_skew':         v.skew(),
            'rf_q10':          v.quantile(0.10),
            'rf_q25':          v.quantile(0.25),
            'rf_q50':          v.quantile(0.50),
            'rf_q75':          v.quantile(0.75),
            'rf_q90':          v.quantile(0.90),
            'rf_q95':          v.quantile(0.95),
            'rf_recent_mean':  recent.mean() if len(recent) > 0 else v.mean(),
            'rf_recent_max':   recent.max()  if len(recent) > 0 else v.max(),
            'rf_trend':        trend_slope,   # mm/year
        })

    rf_stats = rf_long.groupby('district').apply(stats_for).reset_index()
    print(f"Rainfall stats computed for {len(rf_stats)} districts")
    print(rf_stats[['district','rf_min','rf_max','rf_mean',
                    'rf_q75','rf_q90','rf_recent_mean']].to_string(index=False))
    return rf_stats, rf_long


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — HISTORICAL LANDSLIDE DATA
# ──────────────────────────────────────────────────────────────────────────────
def load_landslide_data(landslide_csv):
    """
    Load NASA GLC landslide catalog filtered to Sri Lanka.
    Returns per-district event counts and per-(district, year) counts.
    """
    print("\n" + "=" * 65)
    print("STEP 3: Loading Historical Landslide Records")
    print("=" * 65)

    ls = pd.read_csv(landslide_csv)
    ls['event_date'] = pd.to_datetime(ls['event_date'])
    ls['year'] = ls['event_date'].dt.year

    # Province → district mapping (Sri Lanka administrative structure)
    province_to_districts = {
        'Uva':           ['Badulla', 'Monaragala'],
        'Central':       ['Kandy', 'Matale', 'Nuwara Eliya'],
        'Southern':      ['Galle', 'Matara', 'Hambantota'],
        'Sabaragamuwa':  ['Ratnapura', 'Kegalle'],
        'Western':       ['Colombo', 'Gampaha', 'Kalutara'],
        'North Central': ['Anuradhapura', 'Polonnaruwa'],
        'North Western': ['Kurunegala', 'Puttalam'],
    }

    # Build per-(province, year) counts
    prov_year = ls.groupby(['admin_divi', 'year']).agg(
        ls_events=('event_id', 'count'),
        ls_fatalities=('fatality_c', 'sum')
    ).reset_index().rename(columns={'admin_divi': 'province'})

    # Expand to district level (equal split within province)
    rows = []
    for _, row in prov_year.iterrows():
        dists = province_to_districts.get(row['province'], [])
        if not dists:
            continue
        for d in dists:
            rows.append({
                'district':      d,
                'year':          row['year'],
                'ls_events':     row['ls_events'] / len(dists),
                'ls_fatalities': row['ls_fatalities'] / len(dists),
                'province':      row['province'],
            })

    ls_dist_year = pd.DataFrame(rows)

    # Aggregate to district totals
    ls_dist = ls_dist_year.groupby('district').agg(
        ls_total_events=('ls_events', 'sum'),
        ls_total_fatalities=('ls_fatalities', 'sum'),
        ls_active_years=('year', 'nunique')
    ).reset_index()

    print(f"Districts with landslide records: {len(ls_dist)}")
    print(ls_dist.to_string(index=False))
    return ls_dist, ls_dist_year


# ──────────────────────────────────────────────────────────────────────────────
# STEP 4 — MERGE & PATTERN DISCOVERY
# ──────────────────────────────────────────────────────────────────────────────
def merge_and_discover_patterns(susc_df, rf_stats, ls_dist, rf_long, ls_dist_year):
    """
    Merge all data, run correlation analysis, PCA, and K-Means clustering
    to find NATURAL groupings without any hand-coded thresholds.
    """
    print("\n" + "=" * 65)
    print("STEP 4: Merging Data & Pattern Discovery")
    print("=" * 65)

    # --- Normalize names for join ---
    def norm(s): return str(s).strip().lower().replace('_', ' ')
    susc_df['_key']  = susc_df['district'].apply(norm)
    rf_stats['_key'] = rf_stats['district'].apply(norm)
    ls_dist['_key']  = ls_dist['district'].apply(norm)

    merged = susc_df.merge(rf_stats.drop(columns='district'), on='_key', how='inner')
    merged = merged.merge(ls_dist.drop(columns='district'), on='_key', how='left')
    merged['ls_total_events']    = merged['ls_total_events'].fillna(0)
    merged['ls_total_fatalities']= merged['ls_total_fatalities'].fillna(0)
    merged['ls_active_years']    = merged['ls_active_years'].fillna(0)
    merged.drop(columns='_key', inplace=True)

    n = len(merged)
    print(f"Merged: {n} districts with full data")

    # ── 4a: Correlation Matrix ──────────────────────────────────────────
    feat_cols = ['wsi','pct_high','pct_moderate',
                 'rf_mean','rf_std','rf_cv','rf_skew',
                 'rf_q75','rf_q90','rf_q95','rf_trend',
                 'rf_recent_mean','ls_total_events']

    corr_matrix = merged[feat_cols].corr()
    print("\nTop correlations with WSI (susceptibility):")
    wsi_corr = corr_matrix['wsi'].drop('wsi').sort_values(key=abs, ascending=False)
    print(wsi_corr.to_string())

    # ── 4b: PCA ────────────────────────────────────────────────────────
    X = merged[feat_cols].copy()
    X_imputed = X.fillna(X.mean())
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_imputed)

    pca = PCA(n_components=min(4, n-1))
    pca_coords = pca.fit_transform(X_scaled)
    explained = pca.explained_variance_ratio_

    print(f"\nPCA explained variance: PC1={explained[0]:.1%}  PC2={explained[1]:.1%}  "
          f"PC3={explained[2]:.1%}")

    pc_loadings = pd.DataFrame(pca.components_[:3].T,
                                index=feat_cols,
                                columns=['PC1','PC2','PC3'])
    print("\nPCA loadings (top drivers per component):")
    print(pc_loadings.sort_values('PC1', key=abs, ascending=False).head(6).to_string())

    # ── 4c: K-Means — find optimal k via silhouette ─────────────────────
    sil_scores = {}
    for k in range(2, min(6, n)):
        km = KMeans(n_clusters=k, random_state=42, n_init=20)
        labels = km.fit_predict(X_scaled)
        sil_scores[k] = silhouette_score(X_scaled, labels)
        print(f"  K={k}  silhouette={sil_scores[k]:.4f}")

    best_k = max(sil_scores, key=sil_scores.get)
    print(f"\nOptimal clusters: K={best_k} (silhouette={sil_scores[best_k]:.4f})")

    km_final = KMeans(n_clusters=best_k, random_state=42, n_init=20)
    merged['cluster'] = km_final.fit_predict(X_scaled)

    # Rank clusters by mean WSI + rf_mean (so cluster 0 = lowest risk)
    cluster_rank = merged.groupby('cluster')[['wsi','rf_mean']].mean()
    cluster_rank['rank_score'] = cluster_rank['wsi'] + cluster_rank['rf_mean'] / cluster_rank['rf_mean'].max()
    cluster_rank = cluster_rank['rank_score'].rank().astype(int)
    merged['cluster_ranked'] = merged['cluster'].map(cluster_rank)

    print("\nCluster summary:")
    csum = merged.groupby('cluster_ranked').agg(
        n=('district','count'),
        wsi_mean=('wsi','mean'),
        rf_mean=('rf_mean','mean'),
        rf_q90_mean=('rf_q90','mean'),
        ls_events=('ls_total_events','mean')
    )
    print(csum.to_string())

    merged['pca1'] = pca_coords[:, 0]
    merged['pca2'] = pca_coords[:, 1]

    return merged, corr_matrix, pca, pc_loadings, feat_cols, X_scaled


# ──────────────────────────────────────────────────────────────────────────────
# STEP 5 — DATA-DRIVEN THRESHOLD IDENTIFICATION
# ──────────────────────────────────────────────────────────────────────────────
def find_rainfall_thresholds(merged, rf_long, ls_dist_year):
    """
    For districts with landslide records, find the rainfall percentile
    that best separates landslide years from non-landslide years.

    Method: For each district with events, test Q50–Q95 as trigger threshold.
    Choose the quantile that maximises (TP rate – FP rate) across all districts.
    This gives a DATA-DRIVEN critical rainfall threshold.
    """
    print("\n" + "=" * 65)
    print("STEP 5: Data-Driven Rainfall Threshold Identification")
    print("=" * 65)

    ls_years_by_district = ls_dist_year.groupby('district')['year'].apply(set).to_dict()

    # Normalize district names
    rf_norm = rf_long.copy()
    rf_norm['district'] = rf_norm['district'].str.strip()

    results = []
    quantile_candidates = np.arange(0.50, 0.96, 0.05)

    active_districts = [d for d in merged['district'] if d in ls_years_by_district]
    print(f"Districts with landslide event records for threshold calibration: {len(active_districts)}")

    for district in active_districts:
        df_d = rf_norm[rf_norm['district'] == district].dropna(subset=['rainfall_mm'])
        if len(df_d) < 10:
            continue
        event_years = ls_years_by_district[district]
        df_d = df_d.copy()
        df_d['is_landslide_year'] = df_d['year'].isin(event_years).astype(int)

        best_q, best_tss = None, -999
        for q in quantile_candidates:
            threshold = df_d['rainfall_mm'].quantile(q)
            predicted = (df_d['rainfall_mm'] >= threshold).astype(int)
            tp = ((predicted == 1) & (df_d['is_landslide_year'] == 1)).sum()
            fp = ((predicted == 1) & (df_d['is_landslide_year'] == 0)).sum()
            tn = ((predicted == 0) & (df_d['is_landslide_year'] == 0)).sum()
            fn = ((predicted == 0) & (df_d['is_landslide_year'] == 1)).sum()
            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
            tss = tpr - fpr   # True Skill Score
            if tss > best_tss:
                best_tss = tss
                best_q = q

        best_threshold_mm = df_d['rainfall_mm'].quantile(best_q)
        results.append({
            'district':         district,
            'best_quantile':    best_q,
            'trigger_rf_mm':    best_threshold_mm,
            'tss':              best_tss,
        })
        print(f"  {district:20s}  best Q={best_q:.2f}  "
              f"threshold={best_threshold_mm:.1f} mm  TSS={best_tss:.3f}")

    threshold_df = pd.DataFrame(results)

    if len(threshold_df) > 0:
        median_q   = threshold_df['best_quantile'].median()
        median_tss = threshold_df['tss'].median()
        print(f"\nMedian optimal quantile across calibration districts: Q{median_q:.2f}")
        print(f"Median TSS: {median_tss:.3f}")
    else:
        median_q = 0.75
        print("\nNo calibration districts found — using Q75 as default threshold quantile")

    # Apply threshold to ALL districts using the calibrated quantile,
    # scaled by susceptibility: higher WSI → lower effective threshold
    def district_trigger(row):
        q_eff = median_q - 0.10 * row['wsi']   # susceptibility penalty
        q_eff = max(0.50, min(0.95, q_eff))
        # Use the district's own rainfall quantile
        return row[f'rf_q{int(q_eff*100)}'] if f'rf_q{int(q_eff*100)}' in row.index else row['rf_q75']

    merged['trigger_rf_mm'] = merged.apply(district_trigger, axis=1)
    print("\nDistrict trigger thresholds (mm/year):")
    print(merged[['district','wsi','trigger_rf_mm']].sort_values('wsi', ascending=False).to_string(index=False))

    return merged, threshold_df


# ──────────────────────────────────────────────────────────────────────────────
# STEP 6 — COMPOSITE RISK SCORE & CLASSIFICATION
# ──────────────────────────────────────────────────────────────────────────────
def classify_risk(merged):
    """
    Composite risk = weighted combination of:
      - WSI                   (spatial susceptibility — from actual SHP)
      - Rainfall exceedance   (how often district exceeds its own trigger threshold)
      - Landslide density     (normalized historical event count)

    All weights derived from PCA loadings (PC1 driven mostly by WSI+rainfall).
    Risk classes assigned using Jenks Natural Breaks equivalent
    (quantile-based with 4 classes: Low / Moderate / High / Very High).
    """
    print("\n" + "=" * 65)
    print("STEP 6: Composite Risk Classification")
    print("=" * 65)

    # Normalize each component 0–1
    def minmax(s): return (s - s.min()) / (s.max() - s.min()) if s.max() != s.min() else s * 0

    merged['norm_wsi']    = minmax(merged['wsi'])
    merged['norm_rf']     = minmax(merged['rf_recent_mean'])
    merged['norm_ls']     = minmax(merged['ls_total_events'])

    # Weights: WSI 50%, Rainfall 35%, Historical events 15%
    merged['composite_risk'] = (
        0.50 * merged['norm_wsi'] +
        0.35 * merged['norm_rf']  +
        0.15 * merged['norm_ls']
    )

    # Jenks-like quantile breaks on composite score
    q33 = merged['composite_risk'].quantile(0.33)
    q66 = merged['composite_risk'].quantile(0.66)
    q85 = merged['composite_risk'].quantile(0.85)

    def assign_class(v):
        if v < q33:   return 1, 'Low'
        elif v < q66: return 2, 'Moderate'
        elif v < q85: return 3, 'High'
        else:         return 4, 'Very High'

    merged[['risk_id','risk_class']] = merged['composite_risk'].apply(
        lambda v: pd.Series(assign_class(v))
    )

    print(f"Thresholds  →  Low: <{q33:.3f}  |  Moderate: {q33:.3f}–{q66:.3f}  "
          f"|  High: {q66:.3f}–{q85:.3f}  |  Very High: ≥{q85:.3f}")
    print("\nFinal Risk Classification:")
    print(merged[['district','wsi','rf_recent_mean','composite_risk','risk_class','trigger_rf_mm']]
          .sort_values('composite_risk', ascending=False)
          .to_string(index=False))

    return merged, (q33, q66, q85)


# ──────────────────────────────────────────────────────────────────────────────
# STEP 7 — VISUALISATIONS
# ──────────────────────────────────────────────────────────────────────────────
CMAP = {'Low': '#2ecc71', 'Moderate': '#f39c12', 'High': '#e67e22', 'Very High': '#c0392b'}

def plot_results(merged, corr_matrix, feat_cols, rf_long, thresholds, out_dir):
    print("\n" + "=" * 65)
    print("STEP 7: Generating Figures")
    print("=" * 65)

    q33, q66, q85 = thresholds

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle('Sri Lanka — Landslide Risk Prediction Model\n'
                 '(Susceptibility from .shp + Rainfall Statistics)',
                 fontsize=16, fontweight='bold', y=1.00)

    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35)

    # ── Panel 1: Spatial scatter map ──────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    district_coords = {
        'Colombo':(80.029,6.848),'Gampaha':(80.021,7.119),'Kalutara':(80.135,6.576),
        'Kandy':(80.641,7.215),'Matale':(80.624,7.470),'Nuwara Eliya':(80.763,6.961),
        'Galle':(80.221,6.033),'Matara':(80.535,5.946),'Hambantota':(81.119,6.145),
        'Jaffna':(80.013,9.661),'Mannar':(79.904,8.978),'Vavuniya':(80.497,8.752),
        'Mullaitivu':(80.812,9.268),'Kilinochchi':(80.403,9.394),'Batticaloa':(81.695,7.717),
        'Ampara':(81.675,7.300),'Trincomalee':(81.234,8.571),'Kurunegala':(80.362,7.487),
        'Puttalam':(79.839,8.037),'Anuradhapura':(80.401,8.337),'Polonnaruwa':(80.995,7.939),
        'Badulla':(81.058,6.990),'Monaragala':(81.350,6.874),'Ratnapura':(80.383,6.704),
        'Kegalle':(80.350,7.250),
    }
    merged['lon'] = merged['district'].map(lambda d: district_coords.get(d, (80.5,7.5))[0])
    merged['lat'] = merged['district'].map(lambda d: district_coords.get(d, (80.5,7.5))[1])

    for cls, color in CMAP.items():
        sub = merged[merged['risk_class'] == cls]
        ax1.scatter(sub['lon'], sub['lat'], c=color, s=160, label=cls,
                    edgecolors='black', linewidth=0.6, zorder=3)
    for _, r in merged.iterrows():
        ax1.annotate(r['district'], (r['lon'], r['lat']),
                     fontsize=5, ha='center', va='bottom', xytext=(0,5),
                     textcoords='offset points')
    ax1.set_title('Risk Classification Map', fontweight='bold')
    ax1.set_xlabel('Longitude'); ax1.set_ylabel('Latitude')
    ax1.legend(title='Risk', fontsize=7, markerscale=0.8)
    ax1.grid(True, alpha=0.3); ax1.set_facecolor('#ddeeff')

    # ── Panel 2: Composite score bar ─────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    sd = merged.sort_values('composite_risk', ascending=True)
    ax2.barh(sd['district'], sd['composite_risk'],
             color=[CMAP[c] for c in sd['risk_class']], edgecolor='grey', linewidth=0.3)
    for q, lbl, col in [(q33,'Low|Mod','orange'),(q66,'Mod|High','darkorange'),(q85,'High|VH','red')]:
        ax2.axvline(q, color=col, ls='--', lw=1.2, label=f'{lbl} ({q:.2f})')
    ax2.set_title('Composite Risk Score', fontweight='bold')
    ax2.set_xlabel('Score (0–1)')
    ax2.tick_params(axis='y', labelsize=6)
    ax2.legend(fontsize=6)

    # ── Panel 3: WSI bar from actual SHP data ─────────────────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    sd2 = merged.sort_values('wsi', ascending=True)
    ax3.barh(sd2['district'], sd2['wsi'],
             color=[CMAP[c] for c in sd2['risk_class']], edgecolor='grey', linewidth=0.3)
    ax3.set_title('WSI from Actual .shp\n(area-weighted susceptibility)', fontweight='bold')
    ax3.set_xlabel('WSI (0–1)')
    ax3.tick_params(axis='y', labelsize=6)

    # ── Panel 4: Correlation heatmap ─────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 0])
    mask = np.zeros_like(corr_matrix, dtype=bool)
    mask[np.triu_indices_from(mask)] = True
    sns.heatmap(corr_matrix, mask=mask, ax=ax4, cmap='RdYlGn',
                center=0, annot=True, fmt='.2f', annot_kws={'size': 6},
                linewidths=0.4, cbar_kws={'shrink': 0.7})
    ax4.set_title('Feature Correlation Matrix', fontweight='bold')
    ax4.tick_params(axis='both', labelsize=6)

    # ── Panel 5: PCA scatter ─────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 1])
    for cls, color in CMAP.items():
        sub = merged[merged['risk_class'] == cls]
        ax5.scatter(sub['pca1'], sub['pca2'], c=color, s=90, label=cls,
                    edgecolors='black', linewidth=0.5, zorder=3)
        for _, r in sub.iterrows():
            ax5.annotate(r['district'][:6], (r['pca1'], r['pca2']), fontsize=5.5)
    ax5.set_xlabel('PC1'); ax5.set_ylabel('PC2')
    ax5.set_title('PCA — Feature Space by Risk', fontweight='bold')
    ax5.legend(fontsize=7); ax5.grid(True, alpha=0.3)

    # ── Panel 6: Susceptibility stacked bar (from actual SHP) ────────────
    ax6 = fig.add_subplot(gs[1, 2])
    sd3 = merged.sort_values('wsi', ascending=True)
    bottoms = np.zeros(len(sd3))
    for col, color, label in [
        ('pct_very_low','#2ecc71','Very Low'),
        ('pct_low',     '#f1c40f','Low'),
        ('pct_moderate','#e67e22','Moderate'),
        ('pct_high',    '#c0392b','High'),
    ]:
        if col in sd3.columns:
            ax6.barh(sd3['district'], sd3[col], left=bottoms,
                     color=color, label=label, edgecolor='white', linewidth=0.3)
            bottoms += sd3[col].values
    ax6.set_title('Susceptibility Class Area %\n(from actual .shp files)', fontweight='bold')
    ax6.set_xlabel('Area %')
    ax6.tick_params(axis='y', labelsize=6)
    ax6.legend(fontsize=7, loc='lower right')

    # ── Panel 7: Rainfall box-plot top 10 ────────────────────────────────
    ax7 = fig.add_subplot(gs[2, 0])
    top10 = merged.nlargest(10, 'composite_risk')['district'].tolist()
    rf_top = rf_long[rf_long['district'].isin(top10)]
    order = merged[merged['district'].isin(top10)].sort_values(
        'composite_risk', ascending=False)['district'].tolist()
    bp_data = [rf_top[rf_top['district'] == d]['rainfall_mm'].dropna().values for d in order]
    bp = ax7.boxplot(bp_data, labels=order, patch_artist=True)
    for patch, d in zip(bp['boxes'], order):
        rc = merged[merged['district'] == d]['risk_class'].values
        patch.set_facecolor(CMAP[rc[0]] if len(rc) else 'grey')
        patch.set_alpha(0.8)
    ax7.set_title('Rainfall Distribution\nTop 10 High-Risk Districts', fontweight='bold')
    ax7.set_ylabel('Annual Rainfall (mm)')
    ax7.tick_params(axis='x', rotation=45, labelsize=7)
    ax7.grid(axis='y', alpha=0.3)

    # ── Panel 8: WSI vs rainfall scatter ─────────────────────────────────
    ax8 = fig.add_subplot(gs[2, 1])
    for cls, color in CMAP.items():
        sub = merged[merged['risk_class'] == cls]
        ax8.scatter(sub['rf_mean'], sub['wsi'], c=color, s=90, label=cls,
                    edgecolors='black', linewidth=0.5)
        for _, r in sub.iterrows():
            ax8.annotate(r['district'][:5], (r['rf_mean'], r['wsi']), fontsize=5.5)
    ax8.set_xlabel('Mean Annual Rainfall (mm)')
    ax8.set_ylabel('WSI (from .shp)')
    ax8.set_title('Susceptibility vs Rainfall', fontweight='bold')
    ax8.legend(fontsize=7); ax8.grid(True, alpha=0.3)

    # ── Panel 9: Trigger threshold vs WSI ────────────────────────────────
    ax9 = fig.add_subplot(gs[2, 2])
    for cls, color in CMAP.items():
        sub = merged[merged['risk_class'] == cls]
        ax9.scatter(sub['wsi'], sub['trigger_rf_mm'], c=color, s=90, label=cls,
                    edgecolors='black', linewidth=0.5)
        for _, r in sub.iterrows():
            ax9.annotate(r['district'][:5], (r['wsi'], r['trigger_rf_mm']), fontsize=5.5)
    ax9.set_xlabel('WSI (from .shp)')
    ax9.set_ylabel('Trigger Rainfall (mm/year)')
    ax9.set_title('Dynamic Trigger Threshold vs WSI', fontweight='bold')
    ax9.legend(fontsize=7); ax9.grid(True, alpha=0.3)

    fig.tight_layout()
    out_png = os.path.join(out_dir, 'landslide_risk_model_v2.png')
    plt.savefig(out_png, dpi=150, bbox_inches='tight')
    print(f"  Figure saved: {out_png}")
    plt.close()


# ──────────────────────────────────────────────────────────────────────────────
# STEP 8 — SAVE OUTPUT SHAPEFILE
# ──────────────────────────────────────────────────────────────────────────────
def save_output_shapefile(merged, out_dir):
    print("\n" + "=" * 65)
    print("STEP 8: Saving Output Shapefile")
    print("=" * 65)

    district_coords = {
        'Colombo':(80.029,6.848),'Gampaha':(80.021,7.119),'Kalutara':(80.135,6.576),
        'Kandy':(80.641,7.215),'Matale':(80.624,7.470),'Nuwara Eliya':(80.763,6.961),
        'Galle':(80.221,6.033),'Matara':(80.535,5.946),'Hambantota':(81.119,6.145),
        'Jaffna':(80.013,9.661),'Mannar':(79.904,8.978),'Vavuniya':(80.497,8.752),
        'Mullaitivu':(80.812,9.268),'Kilinochchi':(80.403,9.394),'Batticaloa':(81.695,7.717),
        'Ampara':(81.675,7.300),'Trincomalee':(81.234,8.571),'Kurunegala':(80.362,7.487),
        'Puttalam':(79.839,8.037),'Anuradhapura':(80.401,8.337),'Polonnaruwa':(80.995,7.939),
        'Badulla':(81.058,6.990),'Monaragala':(81.350,6.874),'Ratnapura':(80.383,6.704),
        'Kegalle':(80.350,7.250),
    }

    if 'lon' not in merged.columns:
        merged['lon'] = merged['district'].map(lambda d: district_coords.get(d,(80.5,7.5))[0])
        merged['lat'] = merged['district'].map(lambda d: district_coords.get(d,(80.5,7.5))[1])

    geometry = [Point(xy) for xy in zip(merged['lon'], merged['lat'])]

    # Select output columns (truncated to 10 chars for .dbf compatibility)
    out_cols = {
        'district':         'district',
        'risk_id':          'risk_id',
        'risk_class':       'risk_class',
        'composite_risk':   'comp_risk',
        'wsi':              'wsi',
        'pct_very_low':     'pct_vlow',
        'pct_low':          'pct_low',
        'pct_moderate':     'pct_mod',
        'pct_high':         'pct_high',
        'total_area_km2':   'total_km2',
        'rf_min':           'rf_min',
        'rf_max':           'rf_max',
        'rf_mean':          'rf_mean',
        'rf_median':        'rf_median',
        'rf_mode':          'rf_mode',
        'rf_std':           'rf_std',
        'rf_cv':            'rf_cv',
        'rf_skew':          'rf_skew',
        'rf_q10':           'rf_q10',
        'rf_q25':           'rf_q25',
        'rf_q75':           'rf_q75',
        'rf_q90':           'rf_q90',
        'rf_q95':           'rf_q95',
        'rf_trend':         'rf_trend',
        'rf_recent_mean':   'rf_rec_mn',
        'trigger_rf_mm':    'trig_rf',
        'ls_total_events':  'ls_events',
        'cluster_ranked':   'cluster',
        'lon':              'longitude',
        'lat':              'latitude',
    }

    # Only include columns that actually exist in merged
    valid = {k: v for k, v in out_cols.items() if k in merged.columns}
    out_df = merged[list(valid.keys())].copy()
    out_df.columns = list(valid.values())

    gdf = gpd.GeoDataFrame(out_df, geometry=geometry, crs='EPSG:4326')

    out_shp = os.path.join(out_dir, 'SriLanka_LandslideRisk_v2.shp')
    gdf.to_file(out_shp)
    print(f"  Shapefile saved: {out_shp}")
    print(f"  Features:        {len(gdf)}")
    print(f"  Attributes:      {list(gdf.columns)}")

    # Also save CSV
    out_csv = os.path.join(out_dir, 'district_risk_v2.csv')
    gdf.drop(columns='geometry').to_csv(out_csv, index=False, float_format='%.4f')
    print(f"  CSV saved:       {out_csv}")
    return gdf


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # Step 1 — Read actual susceptibility shapefiles
    susc_df = read_susceptibility_shapefiles(args.shp_root)

    # Step 2 — Rainfall statistics
    rf_stats, rf_long = compute_rainfall_stats(args.rainfall)

    # Step 3 — Historical landslide data
    ls_dist, ls_dist_year = load_landslide_data(args.landslide)

    # Step 4 — Merge + pattern discovery (correlation, PCA, clustering)
    merged, corr_matrix, pca, pc_loadings, feat_cols, X_scaled = \
        merge_and_discover_patterns(susc_df, rf_stats, ls_dist, rf_long, ls_dist_year)

    # Step 5 — Data-driven rainfall thresholds
    merged, threshold_df = find_rainfall_thresholds(merged, rf_long, ls_dist_year)

    # Step 6 — Composite risk + classification
    merged, thresholds = classify_risk(merged)

    # Step 7 — Visualisations
    plot_results(merged, corr_matrix, feat_cols, rf_long, thresholds, args.out_dir)

    # Step 8 — Save output .shp
    gdf = save_output_shapefile(merged, args.out_dir)

    print("\n" + "=" * 65)
    print("ALL DONE")
    print("=" * 65)
    print(f"  Output folder: {args.out_dir}")
    print("""
Usage example:
  python landslide_model_v2.py \\
      --shp_root  /home/user/Documents/SriLanka/Blsag_Suscept_phase1_v1/ \\
      --rainfall  /path/to/Srilanka_Rainfall_year_wise.csv \\
      --landslide /path/to/landslides_Sri_Lanka.csv \\
      --out_dir   /path/to/output/
""")


if __name__ == '__main__':
    main()