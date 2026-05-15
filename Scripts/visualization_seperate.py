import os, io, base64, warnings
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.gridspec import GridSpec
import geopandas as gpd
import rasterio
from rasterio.warp import reproject, Resampling, calculate_default_transform
import folium
from folium import raster_layers
from PIL import Image
warnings.filterwarnings("ignore")
from tqdm import tqdm
from paths_config import SUSCEPTIBILITY_PHASE1_OUTPUT_BASE, VILLAGE_SHP

OUTPUT_BASE  = SUSCEPTIBILITY_PHASE1_OUTPUT_BASE
DISTRICT_COL = "adm2_name"
TARGET_CRS   = "EPSG:32644"
WGS84        = "EPSG:4326"

RISK_COLORS  = ["#2ecc71","#a8d8a8","#f39c12","#e67e22","#c0392b"]
RISK_LABELS  = ["Very Low","Low","Moderate","High","Very High"]
RISK_CMAP    = mcolors.ListedColormap(RISK_COLORS) 
RISK_NORM    = mcolors.BoundaryNorm([0.5,1.5,2.5,3.5,4.5,5.5], RISK_CMAP.N)

SCORE_CMAP   = matplotlib.colormaps["RdYlGn_r"]
FS_CMAP      = matplotlib.colormaps["RdYlGn"]     # green=stable, red=unstable

AHP_WEIGHTS  = {
    "Slope":            0.22,
    "TWI":              0.16,
    "Curvature":        0.12,
    "Drainage Density": 0.10,
    "SPI":              0.09,
    "Dist. to Fault":   0.08,
    "Dist. to River":   0.07,
    "LULC":             0.06,
    "Factor of Safety": 0.06,
    "TRI":              0.04,
}

def load_tif(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        bounds = src.bounds
        crs = src.crs
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        arr[arr == -9999.0] = np.nan
        return arr, meta, bounds, crs


def reproject_to_wgs84(arr, meta):
    src_crs = meta["crs"]
    transform, width, height = calculate_default_transform(
        src_crs, WGS84, meta["width"], meta["height"],
        left=meta["transform"].c, bottom=meta["transform"].f + meta["transform"].e * meta["height"],
        right=meta["transform"].c + meta["transform"].a * meta["width"],
        top=meta["transform"].f,
    )
    out = np.full((height, width), np.nan, dtype=np.float32)
    reproject(
        source=arr, destination=out,
        src_transform=meta["transform"], src_crs=src_crs,
        dst_transform=transform, dst_crs=WGS84,
        resampling=Resampling.nearest,
        src_nodata=np.nan, dst_nodata=np.nan,
    )
    from rasterio.transform import array_bounds
    west, south, east, north = array_bounds(height, width, transform)
    return out, [[south, west],[north, east]]


def array_to_png_base64(arr, cmap, vmin, vmax, alpha=0.75):
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    rgba = cmap(norm(np.ma.masked_invalid(arr)))
    rgba[..., 3] = np.where(np.isnan(arr), 0, alpha)
    rgba_uint8 = (rgba * 255).astype(np.uint8)
    img = Image.fromarray(rgba_uint8, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def class_array_to_png_base64(arr, alpha=0.75):
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for i, col in enumerate(RISK_COLORS, start=1):
        r, g, b = [int(col[j:j+2], 16) for j in (1, 3, 5)]
        mask = arr == i
        rgba[mask] = [r, g, b, int(alpha * 255)]
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def district_boundary_wgs84(village_gdf, district):
    dist_gdf = (village_gdf[village_gdf[DISTRICT_COL] == district]
                .dissolve().to_crs(WGS84))
    return dist_gdf


def select_districts(village_gdf):
    all_d = sorted(village_gdf[DISTRICT_COL].dropna().unique())
    while True:
        raw = input("\n  Selection: ").strip()
        if raw.lower() == "list":
            for i, d in enumerate(all_d, 1):
                print(f"    {i:>3}. {d}")
            continue
        chosen = all_d if raw.lower() == "all" \
                 else [x.strip() for x in raw.split(",")]
        not_found = [d for d in chosen if d not in all_d]
        if not_found:
            print(f"  Not found: {not_found}")
            continue
        if input("  ➤  Proceed? (y/n): ").strip().lower() == "y":
            return chosen

def make_static_figure(district, class_arr, score_arr, fs_arr, meta, out_path):
    fig = plt.figure(figsize=(20, 14), facecolor="#0d1117")
    fig.patch.set_facecolor("#0d1117")

    gs = GridSpec(2, 3, figure=fig,
                  hspace=0.35, wspace=0.25,
                  left=0.05, right=0.97, top=0.92, bottom=0.06)

    ax_cls   = fig.add_subplot(gs[0, 0])   # Susceptibility Class
    ax_score = fig.add_subplot(gs[0, 1])   # Susceptibility Score
    ax_fs    = fig.add_subplot(gs[0, 2])   # Factor of Safety
    ax_pie   = fig.add_subplot(gs[1, 0])   # Class pie
    ax_bar   = fig.add_subplot(gs[1, 1])   # AHP weights
    ax_stats = fig.add_subplot(gs[1, 2])   # Stats table

    PANEL_BG = "#161b22"
    for ax in [ax_cls, ax_score, ax_fs, ax_pie, ax_bar, ax_stats]:
        ax.set_facecolor(PANEL_BG)
        for spine in ax.spines.values():
            spine.set_edgecolor("#30363d")

    im_cls = ax_cls.imshow(class_arr, cmap=RISK_CMAP, norm=RISK_NORM,
                           interpolation="nearest", aspect="auto")
    ax_cls.set_title("Susceptibility Class", color="white",
                     fontsize=13, fontweight="bold", pad=8)
    ax_cls.axis("off")
    patches = [mpatches.Patch(color=RISK_COLORS[i], label=RISK_LABELS[i])
               for i in range(5)]
    ax_cls.legend(handles=patches, loc="lower left", fontsize=8,
                  framealpha=0.3, facecolor="#0d1117",
                  edgecolor="#30363d", labelcolor="white")

    s_min, s_max = 1.0, 5.0
    im_score = ax_score.imshow(score_arr, cmap=SCORE_CMAP,
                               vmin=s_min, vmax=s_max,
                               interpolation="bilinear", aspect="auto")
    ax_score.set_title("Susceptibility Score (1–5)", color="white",
                       fontsize=13, fontweight="bold", pad=8)
    ax_score.axis("off")
    cb_score = plt.colorbar(im_score, ax=ax_score, fraction=0.03, pad=0.02)
    cb_score.ax.tick_params(colors="white", labelsize=8)
    cb_score.set_label("Risk Score", color="white", fontsize=9)

    fs_plot = np.clip(fs_arr, 0, 4)
    im_fs = ax_fs.imshow(fs_plot, cmap=FS_CMAP, vmin=0, vmax=4,
                         interpolation="bilinear", aspect="auto")
    ax_fs.set_title("Factor of Safety (0–4+)", color="white",
                    fontsize=13, fontweight="bold", pad=8)
    ax_fs.axis("off")
    cb_fs = plt.colorbar(im_fs, ax=ax_fs, fraction=0.03, pad=0.02)
    cb_fs.ax.tick_params(colors="white", labelsize=8)
    cb_fs.set_label("FS  (green = stable)", color="white", fontsize=9)
    fs_unstable = np.where(fs_arr < 1.0, 1.0, np.nan)
    ax_fs.imshow(fs_unstable, cmap=mcolors.ListedColormap(["red"]),
                 vmin=0, vmax=1, alpha=0.55, aspect="auto",
                 interpolation="nearest")
    ax_fs.text(0.02, 0.02, "■ FS < 1.0 (red overlay = UNSTABLE)",
               transform=ax_fs.transAxes, color="#ff6b6b", fontsize=7,
               va="bottom")

    total = np.sum(~np.isnan(class_arr))
    counts = [np.sum(class_arr == i) for i in range(1, 6)]
    pcts   = [100 * c / total if total > 0 else 0 for c in counts]
    wedge_props = {"edgecolor": "#0d1117", "linewidth": 1.5}
    wedges, texts, autotexts = ax_pie.pie(
        counts, labels=None, colors=RISK_COLORS,
        autopct=lambda p: f"{p:.1f}%" if p > 2 else "",
        startangle=140, wedgeprops=wedge_props,
        textprops={"color": "white", "fontsize": 9},
    )
    ax_pie.set_title("Area by Risk Class", color="white",
                     fontsize=13, fontweight="bold", pad=8)
    ax_pie.legend(
        wedges, [f"{RISK_LABELS[i]}  ({pcts[i]:.1f}%)" for i in range(5)],
        loc="lower center", bbox_to_anchor=(0.5, -0.22),
        fontsize=8, framealpha=0.2, facecolor="#0d1117",
        edgecolor="#30363d", labelcolor="white", ncol=2,
    )

    names  = list(AHP_WEIGHTS.keys())
    values = list(AHP_WEIGHTS.values())
    bar_colors = [RISK_COLORS[4] if v >= 0.15
                  else RISK_COLORS[3] if v >= 0.09
                  else RISK_COLORS[2] if v >= 0.07
                  else RISK_COLORS[1] for v in values]
    bars = ax_bar.barh(names[::-1], [v*100 for v in values[::-1]],
                       color=bar_colors[::-1], edgecolor="#30363d",
                       linewidth=0.5, height=0.65)
    ax_bar.set_title("AHP Factor Weights (%)", color="white",
                     fontsize=13, fontweight="bold", pad=8)
    ax_bar.set_xlabel("Weight (%)", color="white", fontsize=9)
    ax_bar.tick_params(colors="white", labelsize=9)
    ax_bar.xaxis.label.set_color("white")
    for bar, val in zip(bars, [v*100 for v in values[::-1]]):
        ax_bar.text(val + 0.3, bar.get_y() + bar.get_height()/2,
                    f"{val:.0f}%", va="center", color="white", fontsize=8)
    ax_bar.set_xlim(0, 28)
    ax_bar.grid(axis="x", color="#30363d", linewidth=0.5)

    ax_stats.axis("off")
    ax_stats.set_title("Summary Statistics", color="white",
                       fontsize=13, fontweight="bold", pad=8)
    rows = [
        ["Metric", "Score", "FS"],
        ["Min",    f"{np.nanmin(score_arr):.2f}", f"{np.nanmin(fs_arr):.2f}"],
        ["Max",    f"{np.nanmax(score_arr):.2f}", f"{np.nanmax(fs_arr):.2f}"],
        ["Mean",   f"{np.nanmean(score_arr):.2f}", f"{np.nanmean(fs_arr):.2f}"],
        ["Median", f"{np.nanmedian(score_arr):.2f}", f"{np.nanmedian(fs_arr):.2f}"],
        ["FS < 1.0", "—", f"{100*np.sum(fs_arr<1.0)/np.sum(~np.isnan(fs_arr)):.1f}%"],
        ["High+VHigh", f"{pcts[3]+pcts[4]:.1f}%", "—"],
    ]
    col_widths = [0.45, 0.275, 0.275]
    row_h = 0.115
    for r, row in enumerate(rows):
        y = 0.92 - r * row_h
        bg = "#1c2128" if r % 2 == 0 else "#22272e"
        if r == 0: bg = "#c0392b"
        ax_stats.add_patch(mpatches.FancyBboxPatch(
            (0.02, y - row_h + 0.01), 0.96, row_h - 0.01,
            boxstyle="round,pad=0.005", facecolor=bg,
            edgecolor="none", transform=ax_stats.transAxes,
        ))
        x = 0.04
        for ci, (cell, cw) in enumerate(zip(row, col_widths)):
            fw = "bold" if r == 0 else "normal"
            fc = "white" if r == 0 else ("#a8d8a8" if ci > 0 else "#e6edf3")
            ax_stats.text(x + cw/2, y - row_h/2, cell,
                          transform=ax_stats.transAxes,
                          ha="center", va="center",
                          color=fc, fontsize=9, fontweight=fw)
            x += cw

    fig.suptitle(f"Landslide Susceptibility Assessment — {district}",
                 color="white", fontsize=17, fontweight="bold", y=0.97)
    fig.text(0.5, 0.002,
             "Method: MCE-AHP (Yalcin 2008, Pradhan 2010) | SINMAP FS (Pack 1998) | Phase 1",
             ha="center", color="#7d8590", fontsize=8)

    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)

def get_top10_hotspots(score_arr, fs_arr, meta, n=10, min_dist_px=30):
    from pyproj import Transformer

    transform = meta["transform"]
    src_crs   = str(meta["crs"])

    masked = np.where(np.isnan(score_arr) | np.isnan(fs_arr), np.nan, score_arr)

    flat   = masked.flatten()
    order  = np.argsort(flat)[::-1]  # highest first

    transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    selected = []
    used_px  = []

    for idx in order:
        if len(selected) >= n:
            break
        if np.isnan(flat[idx]):
            break
        row_i = idx // masked.shape[1]
        col_i = idx %  masked.shape[1]

        too_close = any(
            abs(row_i - r) < min_dist_px and abs(col_i - c) < min_dist_px
            for r, c in used_px
        )
        if too_close:
            continue

        x_proj = transform.c + (col_i + 0.5) * transform.a
        y_proj = transform.f + (row_i + 0.5) * transform.e
        lon, lat = transformer.transform(x_proj, y_proj)

        selected.append({
            "rank":  len(selected) + 1,
            "lat":   round(lat, 6),
            "lon":   round(lon, 6),
            "score": round(float(flat[idx]), 3),
            "fs":    round(float(fs_arr[row_i, col_i]), 3),
        })
        used_px.append((row_i, col_i))

    return selected

def main():
    village_gdf = gpd.read_file(VILLAGE_SHP)
    chosen = select_districts(village_gdf)

    for district in tqdm(chosen, desc="Districts", unit="district", dynamic_ncols=True):
        dist_safe = district.replace(" ", "_")
        dist_dir  = os.path.join(OUTPUT_BASE, dist_safe)

        cls_path   = os.path.join(dist_dir, f"{district}_susceptibility_class.tif")
        score_path = os.path.join(dist_dir, f"{district}_susceptibility_score.tif")
        fs_path    = os.path.join(dist_dir, f"{district}_factor_of_safety.tif")
        shp_path   = os.path.join(dist_dir, f"{district}_susceptibility.shp")

        missing = [p for p in [cls_path, score_path, fs_path] if not os.path.exists(p)]
        if missing:
            continue

        class_arr, meta, _, _ = load_tif(cls_path)
        score_arr, _,    _, _ = load_tif(score_path)
        fs_arr,    _,    _, _ = load_tif(fs_path)

        ref = class_arr.shape
        def crop(a): return a[:ref[0], :ref[1]]
        score_arr = crop(score_arr)
        fs_arr    = crop(fs_arr)

        static_out = os.path.join(dist_dir, f"{district}_susceptibility_map.png")
        make_static_figure(district, class_arr, score_arr, fs_arr, meta, static_out)


if __name__ == "__main__":
    main()