import os
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.features import rasterize
import richdem as rd
from shapely.geometry import mapping
from scipy.ndimage import uniform_filter, distance_transform_edt
import warnings
warnings.filterwarnings("ignore")
from tqdm import tqdm
from paths_config import (
    DEM_PATH,
    VILLAGE_SHP,
    FAULT_SHP,
    RIVER_SHP,
    SOIL_CLAY_TIF,
    SOIL_SAND_TIF,
    SOIL_SILT_TIF,
    TOPO_BASE as TOPO_OUTPUT_BASE,
    HYDRO_BASE as HYDRO_OUTPUT_BASE,
    SOIL_BASE as SOIL_OUTPUT_BASE,
    VECTOR_BASE as VECTOR_OUTPUT_BASE,
)
SOIL_FILES = {
    "clay": SOIL_CLAY_TIF,
    "sand": SOIL_SAND_TIF,
    "silt": SOIL_SILT_TIF,
}

DISTRICT_COL     = "adm2_name"
TARGET_CRS       = "EPSG:32644"
TARGET_RES       = 30
STREAM_THRESHOLD = 1000


def select_districts(gdf):
    all_districts = sorted(gdf[DISTRICT_COL].dropna().unique())

    while True:
        raw = input("\n  Selection: ").strip()

        if raw.lower() == "list":
            for i, d in enumerate(all_districts, 1):
                print(f"    {i:>3}. {d}")
            continue

        chosen = all_districts if raw.lower() == "all" else [d.strip() for d in raw.split(",")]
        not_found = [d for d in chosen if d not in all_districts]
        if not_found:
            print(f"  Not found: {not_found}. Try again.")
            continue
        if not chosen:
            continue

        if input("  Proceed? (y/n): ").strip().lower() == "y":
            return chosen


def reproject_dem(dem_path, target_crs):
    reproj_path = dem_path.replace(".tif", "_metric.tif")
    if os.path.exists(reproj_path):
        return reproj_path

    with rasterio.open(dem_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds)
        meta = src.meta.copy()
        meta.update({"crs": target_crs, "transform": transform,
                     "width": width, "height": height,
                     "dtype": "float32", "nodata": -9999.0})
        with rasterio.open(reproj_path, "w", **meta) as dst:
            reproject(source=rasterio.band(src, 1),
                      destination=rasterio.band(dst, 1),
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=target_crs,
                      resampling=Resampling.bilinear, dst_nodata=-9999.0)
    return reproj_path


def reproject_raster(src_path, target_crs, target_res):
    out_path = src_path.replace(".tif", "_metric.tif")
    if os.path.exists(out_path):
        return out_path

    with rasterio.open(src_path) as src:
        t, w, h = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds,
            resolution=target_res)
        meta = src.meta.copy()
        meta.update({"crs": target_crs, "transform": t, "width": w,
                     "height": h, "dtype": "float32", "nodata": -9999.0})
        with rasterio.open(out_path, "w", **meta) as dst:
            reproject(source=rasterio.band(src, 1),
                      destination=rasterio.band(dst, 1),
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=t, dst_crs=target_crs,
                      resampling=Resampling.bilinear, dst_nodata=-9999.0)
    return out_path


def clip_dem_to_polygon(dem_path, polygon, polygon_crs):
    with rasterio.open(dem_path) as src:
        if str(polygon_crs) != str(src.crs):
            gdf_tmp = gpd.GeoDataFrame(geometry=[polygon], crs=polygon_crs).to_crs(src.crs)
            geom = [mapping(gdf_tmp.geometry[0])]
        else:
            geom = [mapping(polygon)]

        clipped, transform = mask(src, geom, crop=True, nodata=-9999.0)
        arr = clipped[0].astype(np.float32)
        arr[arr == -9999.0] = np.nan
        pixel_size = abs(src.res[0])

        meta = src.meta.copy()
        meta.update({"driver": "GTiff", "dtype": "float32", "nodata": -9999.0,
                     "height": arr.shape[0], "width": arr.shape[1],
                     "transform": transform, "compress": "lzw"})
        return arr, transform, pixel_size, meta


def clip_and_save_raster(raster_path, polygon, polygon_crs, out_path):
    with rasterio.open(raster_path) as src:
        if str(polygon_crs) != str(src.crs):
            gdf_tmp = gpd.GeoDataFrame(geometry=[polygon], crs=polygon_crs).to_crs(src.crs)
            geom = [mapping(gdf_tmp.geometry[0])]
        else:
            geom = [mapping(polygon)]

        clipped, transform = mask(src, geom, crop=True, nodata=-9999.0)
        arr = clipped[0].astype(np.float32)
        arr[arr == -9999.0] = np.nan

        meta = src.meta.copy()
        meta.update({"driver": "GTiff", "dtype": "float32", "nodata": -9999.0,
                     "height": arr.shape[0], "width": arr.shape[1],
                     "transform": transform, "compress": "lzw", "count": 1})
        arr_out = np.where(np.isnan(arr), -9999.0, arr).astype(np.float32)
        with rasterio.open(out_path, "w", **meta) as dst:
            dst.write(arr_out, 1)


def save_tif(arr, meta, out_path):
    m = meta.copy()
    m.update({"dtype": "float32", "count": 1, "nodata": -9999.0, "compress": "lzw"})
    arr_out = np.where(np.isnan(arr), -9999.0, arr).astype(np.float32)
    with rasterio.open(out_path, "w", **m) as dst:
        dst.write(arr_out, 1)


def resample_raster_inplace(file_path, target_crs, target_res):
    temp_output = file_path + ".tmp"
    with rasterio.open(file_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds,
            resolution=target_res)
        kwargs = src.meta.copy()
        kwargs.update({"crs": target_crs, "transform": transform,
                       "width": width, "height": height})
        with rasterio.open(temp_output, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(source=rasterio.band(src, i),
                          destination=rasterio.band(dst, i),
                          src_transform=src.transform, src_crs=src.crs,
                          dst_transform=transform, dst_crs=target_crs,
                          resampling=Resampling.bilinear)
    os.replace(temp_output, file_path)


def compute_elevation(dem):
    return dem.copy()


def compute_slope(dem, ps):
    p = np.pad(dem, 1, mode="edge")
    dzdx = (p[1:-1, 2:] - p[1:-1, :-2]) / (2 * ps)
    dzdy = (p[2:,  1:-1] - p[:-2, 1:-1]) / (2 * ps)
    slope = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))
    slope[np.isnan(dem)] = np.nan
    return slope.astype(np.float32), dzdx, dzdy


def compute_aspect(dzdx, dzdy, dem):
    aspect = (np.degrees(np.arctan2(-dzdy, dzdx)) + 360) % 360
    aspect[np.isnan(dem)] = np.nan
    return aspect.astype(np.float32)


def compute_plan_curvature(dem, ps):
    p    = np.pad(dem, 1, mode="edge")
    dzdx = (p[1:-1, 2:] - p[1:-1, :-2]) / (2 * ps)
    dzdy = (p[2:, 1:-1] - p[:-2, 1:-1]) / (2 * ps)
    D2x  = (p[1:-1, 2:] - 2*dem + p[1:-1, :-2]) / ps**2
    D2y  = (p[2:, 1:-1] - 2*dem + p[:-2, 1:-1]) / ps**2
    D2xy = (p[:-2, 2:] - p[:-2, :-2] - p[2:, 2:] + p[2:, :-2]) / (4 * ps**2)
    px, qy = dzdx**2, dzdy**2
    denom  = px + qy
    with np.errstate(invalid="ignore", divide="ignore"):
        plan = np.where(
            denom > 1e-10,
            -(D2x*qy - 2*D2xy*dzdx*dzdy + D2y*px) / (denom * np.sqrt(1 + denom)),
            0.0)
    plan[np.isnan(dem)] = np.nan
    return plan.astype(np.float32)


def compute_profile_curvature(dem, ps):
    p    = np.pad(dem, 1, mode="edge")
    dzdx = (p[1:-1, 2:] - p[1:-1, :-2]) / (2 * ps)
    dzdy = (p[2:, 1:-1] - p[:-2, 1:-1]) / (2 * ps)
    D2x  = (p[1:-1, 2:] - 2*dem + p[1:-1, :-2]) / ps**2
    D2y  = (p[2:, 1:-1] - 2*dem + p[:-2, 1:-1]) / ps**2
    D2xy = (p[:-2, 2:] - p[:-2, :-2] - p[2:, 2:] + p[2:, :-2]) / (4 * ps**2)
    px, qy = dzdx**2, dzdy**2
    denom  = px + qy
    with np.errstate(invalid="ignore", divide="ignore"):
        prof = np.where(
            denom > 1e-10,
            -(D2x*px + 2*D2xy*dzdx*dzdy + D2y*qy) / (denom * np.sqrt(1 + denom)**3),
            0.0)
    prof[np.isnan(dem)] = np.nan
    return prof.astype(np.float32)


def compute_twi(dem, ps):
    rdem = rd.rdarray(np.where(np.isnan(dem), -9999.0, dem).astype(np.float64), no_data=-9999.0)
    rd.FillDepressions(rdem, epsilon=True, in_place=True)
    accum     = np.array(rd.FlowAccumulation(rdem, method="D8"), dtype=np.float32)
    area      = (accum + 1) * (ps ** 2)
    _, _, sd  = compute_slope(dem, ps)
    slope_rad = np.radians(np.where(sd < 0.001, 0.001, sd))
    with np.errstate(divide="ignore", invalid="ignore"):
        twi = np.log(area / (np.tan(slope_rad) * ps))
    twi[np.isnan(dem)] = np.nan
    return twi.astype(np.float32)


def compute_tri(dem):
    p = np.pad(dem, 1, mode="edge")
    c = dem
    tri = np.sqrt(
        (p[0:-2, 0:-2] - c)**2 + (p[0:-2, 1:-1] - c)**2 + (p[0:-2, 2:] - c)**2 +
        (p[1:-1, 0:-2] - c)**2 +                           (p[1:-1, 2:] - c)**2 +
        (p[2:,   0:-2] - c)**2 + (p[2:,   1:-1] - c)**2 + (p[2:,   2:] - c)**2)
    tri[np.isnan(dem)] = np.nan
    return tri.astype(np.float32)


def compute_spi(dem, ps):
    rdem = rd.rdarray(np.where(np.isnan(dem), -9999.0, dem).astype(np.float64), no_data=-9999.0)
    rd.FillDepressions(rdem, epsilon=True, in_place=True)
    accum     = np.array(rd.FlowAccumulation(rdem, method="D8"), dtype=np.float32)
    sca       = (accum + 1) * ps
    _, _, sd  = compute_slope(dem, ps)
    slope_rad = np.radians(np.where(sd < 0.001, 0.001, sd))
    spi = sca * np.tan(slope_rad)
    spi[np.isnan(dem)] = np.nan
    return spi.astype(np.float32)


def compute_flow_direction_vectorized(dem, pixel_size):
    dem_clean = np.where(np.isnan(dem), -9999.0, dem).astype(np.float64)
    rdem = rd.rdarray(dem_clean, no_data=-9999.0)
    rd.FillDepressions(rdem, epsilon=True, in_place=True)
    dem_f = np.array(rdem, dtype=np.float32)
    dem_f[np.isnan(dem)] = np.nan

    pad = np.pad(dem_f, 1, mode="edge")

    nbrs = [
        (slice(1,-1), slice(2,None),  pixel_size,              1),
        (slice(2,None), slice(2,None), pixel_size*np.sqrt(2),  2),
        (slice(2,None), slice(1,-1),  pixel_size,              4),
        (slice(2,None), slice(0,-2),  pixel_size*np.sqrt(2),   8),
        (slice(1,-1), slice(0,-2),    pixel_size,             16),
        (slice(0,-2), slice(0,-2),    pixel_size*np.sqrt(2),  32),
        (slice(0,-2), slice(1,-1),    pixel_size,             64),
        (slice(0,-2), slice(2,None),  pixel_size*np.sqrt(2), 128),
    ]

    centre = dem_f
    max_slope = np.full_like(dem_f, -np.inf)
    fdir = np.zeros_like(dem_f)

    for rs, cs, dist, code in nbrs:
        nbr = pad[rs, cs]
        slope = (centre - nbr) / dist
        update = slope > max_slope
        max_slope = np.where(update, slope, max_slope)
        fdir = np.where(update, code, fdir)

    fdir[np.isnan(dem)] = np.nan
    return fdir.astype(np.float32)


def compute_flow_accumulation_mfd(dem, pixel_size, p=1.1):
    dem_clean = np.where(np.isnan(dem), -9999.0, dem).astype(np.float64)
    rdem = rd.rdarray(dem_clean, no_data=-9999.0)
    rd.FillDepressions(rdem, epsilon=True, in_place=True)
    dem_f = np.array(rdem, dtype=np.float64)
    dem_f[np.isnan(dem)] = np.nan

    rows, cols = dem_f.shape
    nodata_mask = np.isnan(dem_f)

    nbrs = [
        (-1, -1, pixel_size * np.sqrt(2)),
        (-1,  0, pixel_size),
        (-1,  1, pixel_size * np.sqrt(2)),
        ( 0, -1, pixel_size),
        ( 0,  1, pixel_size),
        ( 1, -1, pixel_size * np.sqrt(2)),
        ( 1,  0, pixel_size),
        ( 1,  1, pixel_size * np.sqrt(2)),
    ]

    accum = np.ones((rows, cols), dtype=np.float64)
    accum[nodata_mask] = 0.0

    valid_elev = np.where(nodata_mask, np.nan, dem_f)
    flat_idx   = np.argsort(-valid_elev.ravel(), kind="stable")

    for idx in flat_idx:
        r, c = divmod(idx, cols)
        if nodata_mask[r, c]:
            continue
        z = dem_f[r, c]
        weights = []
        targets = []
        for dr, dc, dist in nbrs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not nodata_mask[nr, nc]:
                dz = z - dem_f[nr, nc]
                if dz > 0:
                    weights.append((dz / dist) ** p)
                    targets.append((nr, nc))
        if not weights:
            continue
        total_w = sum(weights)
        for (nr, nc), w in zip(targets, weights):
            accum[nr, nc] += accum[r, c] * (w / total_w)

    accum[nodata_mask] = np.nan
    return accum.astype(np.float32)


def compute_drainage_density(accum_arr, pixel_size, window_size=21):
    stream_mask     = np.where((~np.isnan(accum_arr)) & (accum_arr >= STREAM_THRESHOLD), 1.0, 0.0)
    stream_length_m = stream_mask * pixel_size
    half            = window_size // 2
    padded          = np.pad(stream_length_m, half, mode="reflect")
    window_sum      = uniform_filter(padded, size=window_size, mode="reflect")
    window_sum      = window_sum[half:-half, half:-half] * (window_size ** 2)
    window_area_km2 = ((window_size * pixel_size) ** 2) / 1e6
    dd = (window_sum / 1000.0) / window_area_km2
    dd[np.isnan(accum_arr)] = np.nan
    return dd.astype(np.float32)


def clip_vector(gdf_full, polygon, polygon_crs, buffer_m=2000):
    poly_gdf = gpd.GeoDataFrame(geometry=[polygon], crs=polygon_crs)
    buffered = poly_gdf.buffer(buffer_m).iloc[0]
    return gdf_full[gdf_full.intersects(buffered)].copy()


def compute_distance_raster(gdf_lines, ref_meta, nodata_arr):
    height     = ref_meta["height"]
    width      = ref_meta["width"]
    transform  = ref_meta["transform"]
    pixel_size = abs(transform.a)

    if len(gdf_lines) == 0:
        return np.full((height, width), np.nan, dtype=np.float32)

    line_raster = rasterize(
        shapes=((geom, 1) for geom in gdf_lines.geometry if geom is not None),
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype=np.uint8)

    non_line = (line_raster == 0).astype(np.uint8)
    dist_px  = distance_transform_edt(non_line)
    dist_m   = (dist_px * pixel_size).astype(np.float32)
    dist_m[nodata_arr] = np.nan
    return dist_m


def run_topographic(gdf_dist, dem_metric):
    FEATURES = ["elevation", "slope", "aspect", "plan_curvature",
                "profile_curvature", "twi", "tri", "spi"]

    with tqdm(total=len(gdf_dist), desc="Topographic — Districts",
              unit="district", colour="green", dynamic_ncols=True) as dist_bar:

        for _, row in gdf_dist.iterrows():
            district    = row[DISTRICT_COL]
            dist_folder = os.path.join(TOPO_OUTPUT_BASE, district.replace(" ", "_"))
            os.makedirs(dist_folder, exist_ok=True)
            dist_bar.set_description(f"Topo: {district}")

            try:
                dem_arr, transform, pixel_size, meta = clip_dem_to_polygon(
                    dem_metric, row.geometry, gdf_dist.crs)

                if np.all(np.isnan(dem_arr)) or dem_arr.size < 9:
                    dist_bar.update(1)
                    continue

                slope_arr, dzdx, dzdy = compute_slope(dem_arr, pixel_size)

                with tqdm(total=len(FEATURES), desc=f"  {district}",
                          unit="feature", colour="cyan",
                          dynamic_ncols=True, leave=False) as feat_bar:

                    for feat in FEATURES:
                        feat_bar.set_postfix(f=feat)
                        out = os.path.join(dist_folder, f"{district}_{feat}.tif")
                        if not os.path.exists(out):
                            if feat == "elevation":
                                save_tif(compute_elevation(dem_arr), meta, out)
                            elif feat == "slope":
                                save_tif(slope_arr, meta, out)
                            elif feat == "aspect":
                                save_tif(compute_aspect(dzdx, dzdy, dem_arr), meta, out)
                            elif feat == "plan_curvature":
                                save_tif(compute_plan_curvature(dem_arr, pixel_size), meta, out)
                            elif feat == "profile_curvature":
                                save_tif(compute_profile_curvature(dem_arr, pixel_size), meta, out)
                            elif feat == "twi":
                                save_tif(compute_twi(dem_arr, pixel_size), meta, out)
                            elif feat == "tri":
                                save_tif(compute_tri(dem_arr), meta, out)
                            elif feat == "spi":
                                save_tif(compute_spi(dem_arr, pixel_size), meta, out)
                        feat_bar.update(1)

            except Exception as e:
                pass

            dist_bar.update(1)


def run_hydrological(gdf_dist, dem_metric):
    with tqdm(total=len(gdf_dist), desc="Hydrology — Districts",
              unit="district", colour="green", dynamic_ncols=True) as dist_bar:

        for _, row in gdf_dist.iterrows():
            district    = row[DISTRICT_COL]
            dist_folder = os.path.join(HYDRO_OUTPUT_BASE, district.replace(" ", "_"))
            os.makedirs(dist_folder, exist_ok=True)
            dist_bar.set_description(f"Hydro: {district}")

            try:
                dem_arr, transform, pixel_size, meta = clip_dem_to_polygon(
                    dem_metric, row.geometry, gdf_dist.crs)

                if np.all(np.isnan(dem_arr)) or dem_arr.size < 9:
                    dist_bar.update(1)
                    continue

                with tqdm(total=3, desc=f"  {district}",
                          unit="layer", colour="cyan",
                          dynamic_ncols=True, leave=False) as feat_bar:

                    feat_bar.set_postfix(f="Flow Direction")
                    fd_path = os.path.join(dist_folder, f"{district}_flow_direction.tif")
                    if not os.path.exists(fd_path):
                        save_tif(compute_flow_direction_vectorized(dem_arr, pixel_size), meta, fd_path)
                    feat_bar.update(1)

                    feat_bar.set_postfix(f="Flow Accumulation")
                    fa_path = os.path.join(dist_folder, f"{district}_flow_accumulation_mfd.tif")
                    if not os.path.exists(fa_path):
                        accum_arr = compute_flow_accumulation_mfd(dem_arr, pixel_size)
                        save_tif(accum_arr, meta, fa_path)
                    else:
                        with rasterio.open(fa_path) as src:
                            accum_arr = src.read(1).astype(np.float32)
                            accum_arr[accum_arr == -9999.0] = np.nan
                    feat_bar.update(1)

                    feat_bar.set_postfix(f="Drainage Density")
                    dd_path = os.path.join(dist_folder, f"{district}_drainage_density.tif")
                    if not os.path.exists(dd_path):
                        save_tif(compute_drainage_density(accum_arr, pixel_size), meta, dd_path)
                    feat_bar.update(1)

            except Exception as e:
                pass

            dist_bar.update(1)


def run_soil(gdf_dist, reproj_soil_paths):
    with tqdm(total=len(gdf_dist), desc="Soil — Districts",
              unit="district", colour="green", dynamic_ncols=True) as dist_bar:

        for _, row in gdf_dist.iterrows():
            district    = row[DISTRICT_COL]
            dist_folder = os.path.join(SOIL_OUTPUT_BASE, district.replace(" ", "_"))
            os.makedirs(dist_folder, exist_ok=True)
            dist_bar.set_description(f"Soil: {district}")

            with tqdm(total=len(SOIL_FILES), desc=f"  {district}",
                      unit="layer", colour="cyan",
                      dynamic_ncols=True, leave=False) as soil_bar:

                for soil_name, reproj_path in reproj_soil_paths.items():
                    soil_bar.set_postfix(layer=soil_name)
                    out_path = os.path.join(dist_folder, f"{district}_{soil_name}.tif")
                    if not os.path.exists(out_path):
                        try:
                            clip_and_save_raster(reproj_path, row.geometry, gdf_dist.crs, out_path)
                        except Exception as e:
                            pass
                    soil_bar.update(1)

            dist_bar.update(1)


def run_vector(gdf_dist, fault_gdf, river_gdf):
    with tqdm(total=len(gdf_dist), desc="Vector — Districts",
              unit="district", colour="green", dynamic_ncols=True) as dist_bar:

        for _, row in gdf_dist.iterrows():
            district    = row[DISTRICT_COL]
            dist_safe   = district.replace(" ", "_")
            dist_folder = os.path.join(VECTOR_OUTPUT_BASE, dist_safe)
            os.makedirs(dist_folder, exist_ok=True)
            dist_bar.set_description(f"Vector: {district}")

            try:
                slope_path = os.path.join(TOPO_OUTPUT_BASE, dist_safe, f"{district}_slope.tif")
                with rasterio.open(slope_path) as src:
                    ref_meta   = src.meta.copy()
                    raster_crs = src.crs
                    slope_arr  = src.read(1).astype(np.float32)
                    nodata_mask = (slope_arr == src.nodata) if src.nodata is not None else np.isnan(slope_arr)

                with tqdm(total=4, desc=f"  {district}",
                          unit="step", colour="cyan",
                          dynamic_ncols=True, leave=False) as step_bar:

                    step_bar.set_postfix(step="Fault clip")
                    fault_clip     = clip_vector(fault_gdf, row.geometry, gdf_dist.crs).to_crs(raster_crs)
                    fault_shp_path = os.path.join(dist_folder, f"{district}_fault_lines.shp")
                    if not os.path.exists(fault_shp_path) and len(fault_clip) > 0:
                        fault_clip.to_file(fault_shp_path)
                    step_bar.update(1)

                    step_bar.set_postfix(step="Fault distance")
                    fault_dist_path = os.path.join(dist_folder, f"{district}_dist_to_fault.tif")
                    if not os.path.exists(fault_dist_path):
                        save_tif(compute_distance_raster(fault_clip, ref_meta, nodata_mask), ref_meta, fault_dist_path)
                    step_bar.update(1)

                    step_bar.set_postfix(step="River clip")
                    river_clip     = clip_vector(river_gdf, row.geometry, gdf_dist.crs).to_crs(raster_crs)
                    river_shp_path = os.path.join(dist_folder, f"{district}_river_lines.shp")
                    if not os.path.exists(river_shp_path) and len(river_clip) > 0:
                        river_clip.to_file(river_shp_path)
                    step_bar.update(1)

                    step_bar.set_postfix(step="River distance")
                    river_dist_path = os.path.join(dist_folder, f"{district}_dist_to_river.tif")
                    if not os.path.exists(river_dist_path):
                        save_tif(compute_distance_raster(river_clip, ref_meta, nodata_mask), ref_meta, river_dist_path)
                    step_bar.update(1)

            except Exception as e:
                pass

            dist_bar.update(1)


def run_resample_all():
    tif_files = []
    for base in [TOPO_OUTPUT_BASE, HYDRO_OUTPUT_BASE, SOIL_OUTPUT_BASE, VECTOR_OUTPUT_BASE]:
        for root, _, files in os.walk(base):
            for f in files:
                if f.endswith(".tif"):
                    tif_files.append(os.path.join(root, f))

    with tqdm(total=len(tif_files), desc="Resampling",
              unit="file", colour="yellow", dynamic_ncols=True) as bar:
        for path in tif_files:
            bar.set_postfix(f=os.path.basename(path))
            try:
                resample_raster_inplace(path, TARGET_CRS, TARGET_RES)
            except Exception as e:
                pass
            bar.update(1)


def main():
    gdf = gpd.read_file(VILLAGE_SHP)

    chosen = select_districts(gdf)

    gdf_dist = (
        gdf[gdf[DISTRICT_COL].isin(chosen)]
        .dissolve(by=DISTRICT_COL)
        .reset_index()[[DISTRICT_COL, "geometry"]]
        .to_crs(TARGET_CRS)
    )
    dem_metric = reproject_dem(DEM_PATH, TARGET_CRS)

    reproj_soil_paths = {
        name: reproject_raster(path, TARGET_CRS, TARGET_RES)
        for name, path in SOIL_FILES.items()
    }

    fault_gdf = gpd.read_file(FAULT_SHP).to_crs(TARGET_CRS)
    river_gdf = gpd.read_file(RIVER_SHP).to_crs(TARGET_CRS)

    for base in [TOPO_OUTPUT_BASE, HYDRO_OUTPUT_BASE, SOIL_OUTPUT_BASE, VECTOR_OUTPUT_BASE]:
        os.makedirs(base, exist_ok=True)

    run_topographic(gdf_dist, dem_metric)
    run_hydrological(gdf_dist, dem_metric)
    run_soil(gdf_dist, reproj_soil_paths)
    run_vector(gdf_dist, fault_gdf, river_gdf)
    run_resample_all()


if __name__ == "__main__":
    main()
