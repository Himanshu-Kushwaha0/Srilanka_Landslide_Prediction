import os
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize, shapes
from shapely.geometry import shape
import warnings
warnings.filterwarnings("ignore")
from tqdm import tqdm
from paths_config import (
    TOPO_BASE,
    HYDRO_BASE,
    SOIL_BASE,
    VECTOR_BASE,
    LULC_SHP,
    VILLAGE_SHP,
    SUSCEPTIBILITY_PHASE1_OUTPUT_BASE,
)

OUTPUT_BASE = SUSCEPTIBILITY_PHASE1_OUTPUT_BASE

DISTRICT_COL = "adm2_name"
TARGET_CRS   = "EPSG:32644"
SOIL_SCALE   = 10.0
M_STATIC_CAP = 0.3

AHP_WEIGHTS_BASE = {
    "slope":            0.22,
    "twi":              0.16,
    "curvature":        0.12,
    "drainage_density": 0.10,
    "spi":              0.09,
    "dist_to_fault":    0.08,
    "dist_to_river":    0.07,
    "lulc":             0.06,
    "fs":               0.06,
    "tri":              0.04,
}
assert abs(sum(AHP_WEIGHTS_BASE.values()) - 1.0) < 1e-6

SINMAP_PARAMS = {
    0: (2.0,  35.0, 1600, 1.5),
    1: (5.0,  30.0, 1500, 1.5),
    2: (10.0, 25.0, 1400, 1.5),
    3: (15.0, 20.0, 1300, 1.5),
}
WATER_DENSITY = 1000.0
G             = 9.81

LULC_ROOT_COHESION = {1:0.0, 2:8.0, 4:0.0, 5:2.0, 7:0.0, 8:1.0, 11:1.0}

SLOPE_T = [(0,10,1),(10,20,2),(20,30,3),(30,45,4),(45,999,5)]
FAULT_T = [(0,500,5),(500,1000,4),(1000,2000,3),(2000,5000,2),(5000,1e9,1)]
FS_T    = [(0,1.0,5),(1.0,1.25,4),(1.25,1.5,3),(1.5,2.0,3),(2.0,99,3)]

LULC_SCORES  = {1:4, 2:1, 4:5, 5:3, 7:4, 8:3, 11:3}
CLASS_LABELS = {1:"Very Low", 2:"Low", 3:"Moderate", 4:"High", 5:"Very High"}

def adaptive_thresholds(arr, high_risk_direction="high"):
    valid = arr[~np.isnan(arr)]
    if len(valid) == 0:
        return [(-1e9, 1e9, 3)], valid

    percs = np.percentile(valid, [20, 40, 60, 80])
    breaks = sorted(set(percs.tolist()))

    if len(breaks) < 4:
        extra = np.percentile(valid, [10, 25, 50, 75, 90]).tolist()
        breaks = sorted(set(breaks + extra))[:4]    

    if len(breaks) < 4:
        lo_v = float(valid.min())
        hi_v = float(valid.max())
        span = hi_v - lo_v if hi_v > lo_v else 1.0
        pad  = [lo_v + span * f for f in [0.25, 0.50, 0.75]]
        breaks = sorted(set(breaks + pad))[:4]

    b1, b2, b3, b4 = breaks[0], breaks[1], breaks[2], breaks[3]
    lo = float(valid.min()) - 1e-6
    hi = float(valid.max()) + 1e-6

    if high_risk_direction == "high":
        thresholds = [(lo,b1,1),(b1,b2,2),(b2,b3,3),(b3,b4,4),(b4,hi,5)]
    else:
        thresholds = [(lo,b1,5),(b1,b2,4),(b2,b3,3),(b3,b4,2),(b4,hi,1)]

    return thresholds, valid


def log_thresholds(name, thresholds, valid, data_min, data_max):
    return

def adjust_weights_for_district(district, slope_arr, fault_arr_raw):
    weights = AHP_WEIGHTS_BASE.copy()
    fault_is_empty = (fault_arr_raw is None) or (
        np.sum(~np.isnan(fault_arr_raw)) == 0
    )
    if fault_is_empty:
        w = weights.pop("dist_to_fault")
        weights["twi"]           += w * 0.5
        weights["dist_to_river"] += w * 0.5
    valid_slope = slope_arr[~np.isnan(slope_arr)]
    flat_pct = 0.0
    if len(valid_slope) > 0:
        flat_pct = 100 * np.sum(valid_slope < 10.0) / len(valid_slope)

    if flat_pct > 85.0:
        t  = 0.08
        sg = t * 0.6
        spg = t * 0.4
        weights["slope"]            -= sg
        weights["spi"]              -= spg
        weights["twi"]              += t * 0.5
        weights["drainage_density"] += t * 0.5

    total   = sum(weights.values())
    weights = {k: round(v / total, 6) for k, v in weights.items()}

    return weights, fault_is_empty

def select_districts(gdf):
    all_districts = sorted(gdf[DISTRICT_COL].dropna().unique())
    while True:
        raw = input("\n  Selection: ").strip()
        if raw.lower() == "list":
            for i, d in enumerate(all_districts, 1):
                print(f"    {i:>3}. {d}")
            continue
        chosen = all_districts if raw.lower() == "all" \
                 else [d.strip() for d in raw.split(",")]
        not_found = [d for d in chosen if d not in all_districts]
        if not_found:
            print(f"  Not found: {not_found}")
            continue
        if not chosen:
            continue
        if input("  Proceed? (y/n): ").strip().lower() == "y":
            return chosen

def load_tif(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        arr[arr == -9999.0] = np.nan
        return arr, src.meta.copy()

def load_optional(path, ref_shape):
    if not os.path.exists(path):
        return None
    arr, _ = load_tif(path)
    arr = match_shape(arr, ref_shape)
    if np.sum(~np.isnan(arr)) == 0:
        return None
    return arr

def save_tif(arr, meta, path):
    m = meta.copy()
    m.update({"dtype":"float32","count":1,"nodata":-9999.0,"compress":"lzw"})
    with rasterio.open(path, "w", **m) as dst:
        dst.write(np.where(np.isnan(arr), -9999.0, arr).astype(np.float32), 1)

def match_shape(arr, ref_shape):
    r, c = ref_shape
    arr = arr[:min(arr.shape[0],r), :min(arr.shape[1],c)]
    if arr.shape != ref_shape:
        arr = np.pad(arr, ((0,r-arr.shape[0]),(0,c-arr.shape[1])),
                     constant_values=np.nan)
    return arr[:r, :c]

def rasterize_lulc(gdf, meta):
    gdf = gdf.to_crs(meta["crs"]).copy()
    gdf["DN"] = gdf["DN"].fillna(11).astype(int)
    return rasterize(
        ((geom,val) for geom,val in zip(gdf.geometry, gdf["DN"])),
        out_shape=(meta["height"], meta["width"]),
        transform=meta["transform"], fill=11, dtype=np.int16
    ).astype(np.int16)

def classify(arr, thresholds, default=3):
    edges  = [thresholds[0][0]] + [t[1] for t in thresholds]
    classes = np.array([t[2] for t in thresholds], dtype=np.float32)

    flat = arr.ravel()
    idx  = np.digitize(flat, edges[1:])
    idx  = np.clip(idx, 0, len(classes) - 1)
    out  = classes[idx].reshape(arr.shape)
    out[np.isnan(arr)] = np.nan
    return out

def score_lulc(arr):
    out = np.full_like(arr, 3.0, dtype=np.float32)
    for k, v in LULC_SCORES.items():
        out[arr == k] = float(v)
    return out

def compute_fs(slope_deg, twi_arr, hsg_arr, lulc_arr):
    """
    Compute Factor of Safety (Fs) for slope stability using a SINMAP-like model.
    
    Parameters:
        slope_deg (np.ndarray): Array of slope angles in degrees.
        twi_arr (np.ndarray): Topographic Wetness Index array.
        hsg_arr (np.ndarray): Hydrologic Soil Group indices array.
        lulc_arr (np.ndarray): Land Use / Land Cover indices array.
    
    Returns:
        np.ndarray: Factor of Safety (Fs) array, same shape as input arrays.
    """
    
    # --- Step 1: Preprocess slope ---
    # Convert slope from degrees to radians for trigonometric calculations
    # Clip slope values to avoid extremes that cause numerical issues (0.5° to 89°)
    slope_rad = np.radians(np.clip(slope_deg, 0.5, 89.0))

    # --- Step 2: Normalize Topographic Wetness Index (TWI) ---
    # Replace NaNs in TWI with 0.0 to avoid invalid calculations
    twi_safe  = np.where(np.isnan(twi_arr), 0.0, twi_arr)
    
    # Compute 5th and 95th percentiles for normalization (reduces effect of outliers)
    twi_min   = float(np.nanpercentile(twi_arr, 5))
    twi_max   = float(np.nanpercentile(twi_arr, 95))
    
    # Normalize TWI between 0 and 1
    twi_norm  = np.clip((twi_safe - twi_min) / max(twi_max - twi_min, 1e-6), 0, 1)
    
    # Compute pore pressure coefficient 'm' scaled by maximum static capillary rise
    m         = twi_norm * M_STATIC_CAP

    # --- Step 3: Initialize default soil parameters ---
    # C: cohesion (kPa), phi: friction angle (degrees), rho: density (kg/m^3), z: depth (m)
    C   = np.full_like(slope_deg, 5.0,    dtype=np.float32)
    phi = np.full_like(slope_deg, 30.0,   dtype=np.float32)
    rho = np.full_like(slope_deg, 1500.0, dtype=np.float32)
    z   = np.full_like(slope_deg, 1.5,    dtype=np.float32)

    # --- Step 4: Assign soil parameters based on Hydrologic Soil Group (HSG) ---
    # SINMAP_PARAMS: dictionary mapping HSG index to (cohesion, friction angle, density, depth)
    for idx, (c,p,r,zz) in SINMAP_PARAMS.items():
        px = (hsg_arr == idx)  # Boolean mask where HSG matches current index
        C[px]   = c
        phi[px] = p
        rho[px] = r
        z[px]   = zz

    # --- Step 5: Add root cohesion based on land cover ---
    # LULC_ROOT_COHESION: dictionary mapping LULC codes to additional root cohesion
    root_c = np.zeros_like(slope_deg)
    for dn, rc in LULC_ROOT_COHESION.items():
        root_c[lulc_arr == dn] = rc

    # --- Step 6: Compute Factor of Safety (Fs) ---
    # Convert total cohesion to Pascals (from kPa)
    C_pa    = (C + root_c) * 1000.0
    # Convert friction angle to radians
    phi_rad = np.radians(phi)

    # Numerator: shear strength along the slope
    num = C_pa + np.cos(slope_rad)**2 * (rho - m*WATER_DENSITY) * G * z * np.tan(phi_rad)
    
    # Denominator: downslope gravitational driving stress
    den = rho * G * z * np.sin(slope_rad) * np.cos(slope_rad)

    # Compute Fs safely, avoid division by zero
    with np.errstate(divide="ignore", invalid="ignore"):
        fs = np.where(den > 1e-6, num / den, 10.0)  # If denominator too small, assign high Fs

    # Clip Fs to reasonable bounds (0 = unstable, 10 = very stable)
    fs = np.clip(fs, 0.0, 10.0)
    
    # Assign NaN where slope or TWI were NaN
    fs[np.isnan(slope_deg) | np.isnan(twi_arr)] = np.nan

    return fs.astype(np.float32)

def classify_mce(mce):
    out = np.full_like(mce, np.nan)
    out = np.where(mce <  1.5, 1.0, out)
    out = np.where((mce>=1.5)&(mce<2.5), 2.0, out)
    out = np.where((mce>=2.5)&(mce<3.5), 3.0, out)
    out = np.where((mce>=3.5)&(mce<4.5), 4.0, out)
    out = np.where(mce >= 4.5, 5.0, out)
    out[np.isnan(mce)] = np.nan
    return out

def to_shapefile(class_arr, meta, district, out_shp):
    cls_int = np.where(np.isnan(class_arr), 0, class_arr.astype(np.int32))
    polys = [{"geometry": shape(g), "class_id": int(v),
              "class_name": CLASS_LABELS.get(int(v),"?"),
              "district": district}
             for g,v in shapes(cls_int.astype(np.int32),
                               mask=(cls_int>0).astype(np.uint8),
                               transform=meta["transform"])
             if int(v) > 0]
    if not polys:
        return
    gdf = gpd.GeoDataFrame(polys, crs=meta["crs"])
    gdf = gdf.dissolve(by=["class_id","class_name","district"]).reset_index()
    gdf["area_km2"] = (gdf.geometry.area / 1e6).round(2)
    gdf.to_file(out_shp)

def main():
    gdf      = gpd.read_file(VILLAGE_SHP)
    lulc_gdf = gpd.read_file(LULC_SHP).to_crs(TARGET_CRS)
    chosen   = select_districts(gdf)

    gdf_dist = (gdf[gdf[DISTRICT_COL].isin(chosen)]
                .dissolve(by=DISTRICT_COL)
                .reset_index()[[DISTRICT_COL,"geometry"]]
                .to_crs(TARGET_CRS))
    os.makedirs(OUTPUT_BASE, exist_ok=True)

    with tqdm(total=len(gdf_dist), desc="Districts",
              unit="district", colour="green", dynamic_ncols=True) as dbar:

        for _, row in gdf_dist.iterrows():
            district  = row[DISTRICT_COL]
            dist_safe = district.replace(" ","_")
            out_dir   = os.path.join(OUTPUT_BASE, dist_safe)
            os.makedirs(out_dir, exist_ok=True)

            topo_f  = os.path.join(TOPO_BASE,   dist_safe)
            hydro_f = os.path.join(HYDRO_BASE,  dist_safe)
            soil_f  = os.path.join(SOIL_BASE,   dist_safe)
            vec_f   = os.path.join(VECTOR_BASE, dist_safe)
            dbar.set_description(f"{district}")

            try:
                with tqdm(total=10, desc=f"  {district}",
                          unit="step", colour="cyan",
                          dynamic_ncols=True, leave=False) as step:

                    step.set_postfix(step="Slope")
                    slope_arr, meta = load_tif(f"{topo_f}/{district}_slope.tif")
                    ref = slope_arr.shape
                    step.update(1)

                    step.set_postfix(step="Topo")
                    twi_arr  = match_shape(load_tif(f"{topo_f}/{district}_twi.tif")[0],               ref)
                    tri_arr  = match_shape(load_tif(f"{topo_f}/{district}_tri.tif")[0],               ref)
                    spi_arr  = match_shape(load_tif(f"{topo_f}/{district}_spi.tif")[0],               ref)
                    plan_arr = match_shape(load_tif(f"{topo_f}/{district}_plan_curvature.tif")[0],    ref)
                    prof_arr = match_shape(load_tif(f"{topo_f}/{district}_profile_curvature.tif")[0], ref)
                    curv_arr = plan_arr + prof_arr
                    step.update(1)

                    step.set_postfix(step="Hydro")
                    dd_arr = match_shape(load_tif(f"{hydro_f}/{district}_drainage_density.tif")[0], ref)
                    dd_arr = np.where(dd_arr < 0, 0.0, dd_arr)
                    step.update(1)

                    step.set_postfix(step="Soil HSG")
                    clay = match_shape(load_tif(f"{soil_f}/{district}_clay.tif")[0], ref) / SOIL_SCALE
                    sand = match_shape(load_tif(f"{soil_f}/{district}_sand.tif")[0], ref) / SOIL_SCALE
                    silt = match_shape(load_tif(f"{soil_f}/{district}_silt.tif")[0], ref) / SOIL_SCALE

                    hsg = np.full(ref, 1, dtype=np.int8)
                    hsg = np.where((sand>70)&(clay<10), 0, hsg)
                    hsg = np.where(((sand>=50)&(sand<=70))|((silt>50)&(clay<20)), 1, hsg)
                    hsg = np.where((clay>=20)&(clay<40)&(sand<50), 2, hsg)
                    hsg = np.where(clay>=40, 3, hsg)
                    hsg[np.isnan(clay)|np.isnan(sand)|np.isnan(silt)] = -1

                    n_invalid = int(np.sum(hsg == -1))
                    if n_invalid > 0:
                        valid_hsg = hsg[hsg >= 0]
                        if len(valid_hsg) > 0:
                            majority_hsg = int(np.bincount(valid_hsg.astype(np.intp)).argmax())
                            hsg[hsg == -1] = majority_hsg
                        else:
                            hsg[:] = 1
                    step.update(1)

                    step.set_postfix(step="LULC")
                    lulc_clip = lulc_gdf[lulc_gdf.intersects(row.geometry)].copy()
                    lulc_arr  = match_shape(rasterize_lulc(lulc_clip, meta), ref)
                    step.update(1)

                    step.set_postfix(step="Distances")
                    fault_path = f"{vec_f}/{district}_dist_to_fault.tif"
                    fault_raw  = None
                    if os.path.exists(fault_path):
                        fault_raw, _ = load_tif(fault_path)
                        fault_raw    = match_shape(fault_raw, ref)

                    river_arr = load_optional(f"{vec_f}/{district}_dist_to_river.tif", ref)
                    step.update(1)

                    AHP_WEIGHTS, fault_is_empty = adjust_weights_for_district(
                        district, slope_arr, fault_raw
                    )
                    fault_arr = None if fault_is_empty else fault_raw

                    step.set_postfix(step="SINMAP FS")
                    fs_arr = compute_fs(slope_arr, twi_arr, hsg, lulc_arr)
                    save_tif(fs_arr, meta, f"{out_dir}/{district}_factor_of_safety.tif")
                    step.update(1)

                    step.set_postfix(step="Adaptive thresholds")

                    twi_t, twi_v = adaptive_thresholds(twi_arr, "high")

                    tri_t, tri_v = adaptive_thresholds(tri_arr, "high")

                    spi_t, spi_v = adaptive_thresholds(spi_arr, "high")

                    dd_t, dd_v = adaptive_thresholds(dd_arr, "high")

                    curv_t, curv_v = adaptive_thresholds(curv_arr, "low")

                    if river_arr is not None:
                        river_t, river_v = adaptive_thresholds(river_arr, "low")
                    else:
                        river_t = None

                    step.update(1)

                    step.set_postfix(step="Classify")

                    c_slope = classify(slope_arr, SLOPE_T)
                    c_fs    = classify(fs_arr,    FS_T)
                    c_lulc  = score_lulc(lulc_arr)

                    c_twi  = classify(twi_arr,  twi_t)
                    c_tri  = classify(tri_arr,  tri_t)
                    c_spi  = classify(spi_arr,  spi_t)
                    c_dd   = classify(dd_arr,   dd_t)
                    c_curv = classify(curv_arr, curv_t)

                    c_river = classify(river_arr, river_t) if river_arr is not None \
                              else np.full(ref, 3.0, dtype=np.float32)

                    if fault_arr is not None:
                        c_fault = classify(fault_arr, FAULT_T)
                    step.update(1)

                    step.set_postfix(step="MCE")
                    factor_map = {
                        "slope":            c_slope,
                        "twi":              c_twi,
                        "curvature":        c_curv,
                        "drainage_density": c_dd,
                        "spi":              c_spi,
                        "dist_to_river":    c_river,
                        "lulc":             c_lulc,
                        "fs":               c_fs,
                        "tri":              c_tri,
                    }
                    if fault_arr is not None:
                        factor_map["dist_to_fault"] = c_fault

                    mce = np.zeros(ref, dtype=np.float32)
                    for factor, arr in factor_map.items():
                        if factor in AHP_WEIGHTS:
                            mce += AHP_WEIGHTS[factor] * arr

                    mce[np.isnan(slope_arr)] = np.nan
                    save_tif(mce, meta, f"{out_dir}/{district}_susceptibility_score.tif")
                    step.update(1)

                    step.set_postfix(step="Output")
                    susc = classify_mce(mce)
                    save_tif(susc, meta, f"{out_dir}/{district}_susceptibility_class.tif")
                    to_shapefile(susc, meta, district,
                                 f"{out_dir}/{district}_susceptibility.shp")
                    step.update(1)

            except Exception as e:
                pass
            dbar.update(1)

if __name__ == "__main__":
    main()