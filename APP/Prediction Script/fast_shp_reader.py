"""
╔══════════════════════════════════════════════════════════════════╗
║  FAST SHP READING — Two Solutions                                ║
║                                                                  ║
║  OPTION A : Parallel reading with ProcessPoolExecutor           ║
║             Drop-in replacement for read_susceptibility_shapefiles()
║             in landslide_model_v2.py                            ║
║             Speed: ~4–8x faster depending on CPU cores          ║
║                                                                  ║
║  OPTION B : One-time conversion to single GeoPackage (.gpkg)    ║
║             Run once → future runs load all 25 districts in <1s ║
║             Speed: 50–100x faster on repeat runs                ║
║                                                                  ║
║  RECOMMENDED: Run Option B first (takes same time as before),   ║
║               then all future runs use the .gpkg and are instant ║
╚══════════════════════════════════════════════════════════════════╝

USAGE
-----
# Step 1: Convert once (run this one time only)
python fast_shp_reader.py --mode convert \
    --shp_root "/home/user/Documents/SriLanka/Bisag_Srilanka_Landslide_Prediction/Output/Susceptibility_Phase1_v1" \
    --gpkg_out "/home/user/Documents/SriLanka/Prediction Script/output_shapefiles/all_districts_susceptibility.gpkg"

# Step 2: In all future runs, load the .gpkg (fast)
python fast_shp_reader.py --mode load \
    --gpkg_out "/home/user/Documents/SriLanka/Prediction Script/output_shapefiles/all_districts_susceptibility.gpkg"

# OR: Use parallel reading directly (no pre-conversion needed)
python fast_shp_reader.py --mode parallel \
    --shp_root "/home/user/Documents/SriLanka/Bisag_Srilanka_Landslide_Prediction/Output/Susceptibility_Phase1_v1"
"""

import os
import glob
import time
import argparse
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from concurrent.futures import ProcessPoolExecutor, as_completed

warnings.filterwarnings('ignore')


# ─────────────────────────────────────────────────────────────────
# SHARED: process a single SHP file → returns one dict record
# Must be a top-level function (not nested) for multiprocessing
# ─────────────────────────────────────────────────────────────────
def _read_one_shp(shp_path):
    """
    Read one *_susceptibility.shp and return a dict with all stats.
    This runs in a separate process when using parallel mode.
    Returns (district_name, record_dict) or (None, error_string).
    """
    try:
        gdf = gpd.read_file(shp_path)
    except Exception as e:
        return None, f"[FAIL] {shp_path}: {e}"

    gdf.columns = [c.lower().strip() for c in gdf.columns]

    # ── class name column ───────────────────────────────────────
    name_col = next((c for c in ['class_name','classname','class',
                                  'susc_class','suscept','label','name']
                     if c in gdf.columns), None)
    if name_col is None:
        return None, f"[SKIP] No class column in {shp_path}"

    # ── area column (compute from geometry if missing) ──────────
    area_col = next((c for c in ['area_km2','area_km','areakm2','area']
                     if c in gdf.columns), None)
    if area_col is None:
        gdf_proj   = gdf.to_crs('EPSG:32644')
        gdf['area_km2'] = gdf_proj.geometry.area / 1e6
        area_col   = 'area_km2'

    # ── district name ───────────────────────────────────────────
    if 'district' in gdf.columns:
        dist = str(gdf['district'].dropna().iloc[0]).strip()
    else:
        dist = (os.path.basename(shp_path)
                .replace('_susceptibility.shp', '')
                .replace('_susceptibility_class.shp', ''))
    dist = dist.strip().title().replace('_', ' ')

    # ── aggregate area per class ────────────────────────────────
    gdf['_cls'] = gdf[name_col].str.strip().str.lower()
    ca = gdf.groupby('_cls')[area_col].sum()

    a_vl = sum(ca.get(k, 0) for k in ['very low','very_low','verylow'])
    a_l  = ca.get('low', 0)
    a_m  = ca.get('moderate', 0)
    a_h  = sum(ca.get(k, 0) for k in ['high','very high','very_high','veryhigh'])
    total = a_vl + a_l + a_m + a_h

    if total == 0:
        return None, f"[SKIP] Zero total area for {dist}"

    p_vl = a_vl / total
    p_l  = a_l  / total
    p_m  = a_m  / total
    p_h  = a_h  / total
    wsi  = (0*p_vl + 1*p_l + 2*p_m + 3*p_h) / 3.0

    record = {
        'district':    dist,
        'total_km2':   round(total, 3),
        'area_vl':     round(a_vl, 3),
        'area_l':      round(a_l,  3),
        'area_m':      round(a_m,  3),
        'area_h':      round(a_h,  3),
        'pct_vl':      round(p_vl * 100, 2),
        'pct_l':       round(p_l  * 100, 2),
        'pct_m':       round(p_m  * 100, 2),
        'pct_h':       round(p_h  * 100, 2),
        'wsi':         round(wsi, 5),
        'shp_path':    shp_path,
    }
    return dist, record


# ─────────────────────────────────────────────────────────────────
# OPTION A: PARALLEL READER
# Drop this function into landslide_model_v2.py to replace
# read_susceptibility_shapefiles()
# ─────────────────────────────────────────────────────────────────
def read_susceptibility_parallel(shp_root, max_workers=None):
    """
    Parallel version of read_susceptibility_shapefiles().
    Reads all 25 district SHPs simultaneously using multiple CPU cores.

    Parameters
    ----------
    shp_root    : str  — same path you already use
    max_workers : int  — None = use all available CPU cores

    Returns
    -------
    pd.DataFrame  (same schema as original function)
    """
    print("\n" + "═"*65)
    print("STEP 1: Reading Susceptibility SHPs (PARALLEL)")
    print("═"*65)

    shp_files = glob.glob(
        os.path.join(shp_root, '**', '*susceptibility.shp'),
        recursive=True
    )
    if not shp_files:
        raise FileNotFoundError(f"No *susceptibility.shp found under: {shp_root}")

    print(f"  Found {len(shp_files)} SHP files — reading in parallel...")
    t0 = time.time()

    records = []
    errors  = []

    # Use ProcessPoolExecutor: each SHP file is read in a separate process
    # max_workers=None → automatically uses os.cpu_count()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_read_one_shp, shp): shp
                   for shp in sorted(shp_files)}
        for future in as_completed(futures):
            dist, result = future.result()
            if dist is None:
                errors.append(result)
            else:
                records.append(result)
                print(f"  ✓ {dist:20s}  WSI={result['wsi']:.4f}  "
                      f"H={result['pct_h']:5.1f}%  M={result['pct_m']:5.1f}%")

    elapsed = time.time() - t0

    for e in errors:
        print(e)

    if not records:
        raise ValueError("No valid SHP files could be read.")

    df = pd.DataFrame(records).sort_values('district').reset_index(drop=True)
    print(f"\n  ✓ Read {len(df)} districts in {elapsed:.1f}s")
    return df


# ─────────────────────────────────────────────────────────────────
# OPTION B — STEP 1: Convert all SHPs to one GeoPackage (run once)
# ─────────────────────────────────────────────────────────────────
def convert_shps_to_gpkg(shp_root, gpkg_out):
    """
    ONE-TIME operation: reads all 25 *_susceptibility.shp files and
    merges them into a single GeoPackage file.

    After running this once, use load_susceptibility_from_gpkg()
    for all future runs — loads in under 1 second.
    """
    print("\n" + "═"*65)
    print("CONVERT: Merging all SHPs into single GeoPackage")
    print("═"*65)

    shp_files = glob.glob(
        os.path.join(shp_root, '**', '*susceptibility.shp'),
        recursive=True
    )
    if not shp_files:
        raise FileNotFoundError(f"No *susceptibility.shp found under: {shp_root}")

    print(f"  Found {len(shp_files)} SHP files")
    t0 = time.time()

    gdfs = []
    for shp in sorted(shp_files):
        try:
            gdf = gpd.read_file(shp)
        except Exception as e:
            print(f"  [WARN] {shp}: {e}")
            continue

        gdf.columns = [c.lower().strip() for c in gdf.columns]

        # Ensure district column exists
        if 'district' not in gdf.columns:
            dist = (os.path.basename(shp)
                    .replace('_susceptibility.shp','')
                    .replace('_susceptibility_class.shp',''))
            gdf['district'] = dist.strip().title().replace('_',' ')
        else:
            gdf['district'] = gdf['district'].astype(str).str.strip()

        # Compute area from geometry if missing
        if 'area_km2' not in gdf.columns:
            gdf_proj = gdf.to_crs('EPSG:32644')
            gdf['area_km2'] = gdf_proj.geometry.area / 1e6

        gdfs.append(gdf)
        print(f"  ✓ Loaded {gdf['district'].iloc[0]} ({len(gdf)} rows)")

    if not gdfs:
        raise ValueError("No SHP files could be read.")

    combined = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    combined = combined.set_crs('EPSG:4326', allow_override=True)

    os.makedirs(os.path.dirname(gpkg_out), exist_ok=True)
    combined.to_file(gpkg_out, driver='GPKG', layer='susceptibility')

    elapsed = time.time() - t0
    print(f"\n  ✓ GeoPackage saved: {gpkg_out}")
    print(f"  ✓ Total features: {len(combined)}")
    print(f"  ✓ Conversion time: {elapsed:.1f}s")
    print(f"\n  Next time, load with:")
    print(f"    susc_df = load_susceptibility_from_gpkg('{gpkg_out}')")
    return gpkg_out


# ─────────────────────────────────────────────────────────────────
# OPTION B — STEP 2: Load from GeoPackage (fast, all future runs)
# ─────────────────────────────────────────────────────────────────
def load_susceptibility_from_gpkg(gpkg_path):
    """
    FAST LOAD: reads the pre-built GeoPackage and returns the same
    pd.DataFrame as read_susceptibility_shapefiles().

    Typical load time: 0.1–0.5 seconds for 25 districts.
    """
    print("\n" + "═"*65)
    print("STEP 1: Loading Susceptibility from GeoPackage (FAST)")
    print("═"*65)

    if not os.path.exists(gpkg_path):
        raise FileNotFoundError(
            f"GeoPackage not found: {gpkg_path}\n"
            f"Run convert_shps_to_gpkg() first to create it."
        )

    t0 = time.time()
    gdf = gpd.read_file(gpkg_path, layer='susceptibility')
    elapsed = time.time() - t0
    print(f"  Loaded {len(gdf)} features in {elapsed:.2f}s")

    # Normalize column names
    gdf.columns = [c.lower().strip() for c in gdf.columns]

    # Find class name column
    name_col = next((c for c in ['class_name','classname','class',
                                  'susc_class','suscept','label','name']
                     if c in gdf.columns), None)
    if name_col is None:
        raise ValueError("No class_name column found in GeoPackage.")

    area_col = next((c for c in ['area_km2','area_km','areakm2','area']
                     if c in gdf.columns), None)
    if area_col is None:
        gdf_proj = gdf.to_crs('EPSG:32644')
        gdf['area_km2'] = gdf_proj.geometry.area / 1e6
        area_col = 'area_km2'

    # Aggregate per district (same logic as original)
    records = []
    for dist, grp in gdf.groupby('district'):
        dist = str(dist).strip().title().replace('_',' ')
        grp['_cls'] = grp[name_col].str.strip().str.lower()
        ca = grp.groupby('_cls')[area_col].sum()

        a_vl = sum(ca.get(k, 0) for k in ['very low','very_low','verylow'])
        a_l  = ca.get('low', 0)
        a_m  = ca.get('moderate', 0)
        a_h  = sum(ca.get(k, 0) for k in ['high','very high','very_high','veryhigh'])
        total = a_vl + a_l + a_m + a_h
        if total == 0:
            continue

        p_vl = a_vl / total
        p_l  = a_l  / total
        p_m  = a_m  / total
        p_h  = a_h  / total
        wsi  = (0*p_vl + 1*p_l + 2*p_m + 3*p_h) / 3.0

        records.append({
            'district':  dist,
            'total_km2': round(total, 3),
            'area_vl':   round(a_vl, 3),
            'area_l':    round(a_l,  3),
            'area_m':    round(a_m,  3),
            'area_h':    round(a_h,  3),
            'pct_vl':    round(p_vl * 100, 2),
            'pct_l':     round(p_l  * 100, 2),
            'pct_m':     round(p_m  * 100, 2),
            'pct_h':     round(p_h  * 100, 2),
            'wsi':       round(wsi, 5),
        })
        print(f"  ✓ {dist:20s}  WSI={wsi:.4f}  "
              f"H={p_h*100:5.1f}%  M={p_m*100:5.1f}%")

    df = pd.DataFrame(records).sort_values('district').reset_index(drop=True)
    print(f"\n  ✓ {len(df)} districts loaded in {time.time()-t0:.2f}s total")
    return df


# ─────────────────────────────────────────────────────────────────
# CLI — run directly to convert or benchmark
# ─────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['convert','load','parallel'],
                   required=True,
                   help='convert: SHPs→GPKG (once) | load: fast load from GPKG | parallel: parallel SHP read')
    p.add_argument('--shp_root', default=None,
                   help='Root folder with district sub-folders (for convert/parallel mode)')
    p.add_argument('--gpkg_out', default=None,
                   help='Path to .gpkg file (for convert/load mode)')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()

    if args.mode == 'convert':
        if not args.shp_root or not args.gpkg_out:
            print("ERROR: --shp_root and --gpkg_out required for convert mode")
        else:
            convert_shps_to_gpkg(args.shp_root, args.gpkg_out)

    elif args.mode == 'load':
        if not args.gpkg_out:
            print("ERROR: --gpkg_out required for load mode")
        else:
            df = load_susceptibility_from_gpkg(args.gpkg_out)
            print(df[['district','wsi','pct_h','pct_m']].to_string(index=False))

    elif args.mode == 'parallel':
        if not args.shp_root:
            print("ERROR: --shp_root required for parallel mode")
        else:
            df = read_susceptibility_parallel(args.shp_root)
            print(df[['district','wsi','pct_h','pct_m']].to_string(index=False))