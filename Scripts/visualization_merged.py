import os, gc, warnings
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import matplotlib.ticker as mticker
import matplotlib.cm as mcm
from matplotlib.gridspec import GridSpec
from mpl_toolkits.axes_grid1 import make_axes_locatable
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling as RIOResampling
from shapely.geometry import box
warnings.filterwarnings("ignore")
from tqdm import tqdm
from paths_config import SUSCEPTIBILITY_PHASE1_OUTPUT_BASE, VILLAGE_SHP
OUTPUT_BASE  = SUSCEPTIBILITY_PHASE1_OUTPUT_BASE
DISTRICT_COL = "adm2_name"
WGS84        = "EPSG:4326"
RISK_COLORS = ["#2ecc71", "#a8d8a8", "#f39c12", "#e67e22", "#c0392b"]
RISK_LABELS = ["Very Low", "Low", "Moderate", "High", "Very High"]
RISK_CMAP   = mcolors.ListedColormap(RISK_COLORS)
RISK_NORM   = mcolors.BoundaryNorm([0.5,1.5,2.5,3.5,4.5,5.5], RISK_CMAP.N)
BG          = "#0d1117"
PANEL_BG    = "#161b22"
BORDER      = "#30363d"
TEXT_WHITE  = "#e6edf3"
TEXT_DIM    = "#7d8590"
SCORE_CMAP  = matplotlib.colormaps["RdYlGn_r"]
FS_CMAP     = matplotlib.colormaps["RdYlGn"]
HVH_CMAP    = matplotlib.colormaps["OrRd"]

def dark_ax(ax):
    ax.set_facecolor(PANEL_BG)
    for sp in ax.spines.values():
        sp.set_edgecolor(BORDER)
    ax.tick_params(colors=TEXT_WHITE, labelsize=9)
    ax.xaxis.label.set_color(TEXT_WHITE)
    ax.yaxis.label.set_color(TEXT_WHITE)
    ax.title.set_color(TEXT_WHITE)


def load_tif_full(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        arr[arr == -9999.0] = np.nan
    return arr


def discover_districts(output_base):
    found = []
    for entry in sorted(os.scandir(output_base), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        district = entry.name.replace("_", " ")
        dist_dir = entry.path
        cls_p   = os.path.join(dist_dir, f"{district}_susceptibility_class.tif")
        score_p = os.path.join(dist_dir, f"{district}_susceptibility_score.tif")
        fs_p    = os.path.join(dist_dir, f"{district}_factor_of_safety.tif")
        if all(os.path.exists(p) for p in [cls_p, score_p, fs_p]):
            found.append(district)
    return found


def paths_for(district, output_base):
    dist_safe = district.replace(" ", "_")
    dist_dir  = os.path.join(output_base, dist_safe)
    return (
        os.path.join(dist_dir, f"{district}_susceptibility_class.tif"),
        os.path.join(dist_dir, f"{district}_susceptibility_score.tif"),
        os.path.join(dist_dir, f"{district}_factor_of_safety.tif"),
    )


def build_stats(districts, output_base):
    stats = []
    for district in tqdm(districts, desc="Loading districts", unit="district", dynamic_ncols=True):
        cls_p, score_p, fs_p = paths_for(district, output_base)
        cls_arr   = load_tif_full(cls_p)
        score_arr = load_tif_full(score_p)
        fs_arr    = load_tif_full(fs_p)

        h = min(cls_arr.shape[0], score_arr.shape[0], fs_arr.shape[0])
        w = min(cls_arr.shape[1], score_arr.shape[1], fs_arr.shape[1])
        cls_arr   = cls_arr[:h, :w]
        score_arr = score_arr[:h, :w]
        fs_arr    = fs_arr[:h, :w]

        valid = ~np.isnan(cls_arr)
        total = int(np.sum(valid))

        if total == 0:
            del cls_arr, score_arr, fs_arr
            gc.collect()
            continue

        counts = [int(np.sum(cls_arr == i)) for i in range(1, 6)]
        pcts   = [100.0 * c / total for c in counts]
        dominant_class = int(np.argmax(counts)) + 1
        fs_valid     = fs_arr[~np.isnan(fs_arr)]
        pct_unstable = 100.0 * np.sum(fs_valid < 1.0) / max(len(fs_valid), 1)
        score_sample = score_arr[valid].flatten()[::50]

        stats.append({
            "district":      district,
            "mean_score":    float(np.nanmean(score_arr)),
            "median_score":  float(np.nanmedian(score_arr)),
            "mean_fs":       float(np.nanmean(fs_arr)),
            "dominant_class": dominant_class,
            "pct_unstable":  pct_unstable,
            "pct_vl":  pcts[0], "pct_l": pcts[1], "pct_m": pcts[2],
            "pct_h":   pcts[3], "pct_vh": pcts[4],
            "pct_hvh": pcts[3] + pcts[4],
            "total_px": total,
            "_score_sample": score_sample,
        })

        del cls_arr, score_arr, fs_arr, fs_valid, score_sample
        gc.collect()

    return stats


def load_district_geodataframe(village_shp, district_col):
    gdf = gpd.read_file(village_shp)
    dist_gdf = gdf.dissolve(by=district_col).reset_index()
    dist_gdf = dist_gdf[[district_col, "geometry"]].copy()
    dist_gdf = dist_gdf.to_crs(WGS84)
    dist_gdf.columns = ["district", "geometry"]
    return dist_gdf


def merge_stats_to_gdf(dist_gdf, stats):
    import pandas as pd
    df = pd.DataFrame([{k: v for k, v in s.items() if not k.startswith("_")}
                       for s in stats])
    merged = dist_gdf.merge(df, on="district", how="left")
    return merged


def style_map_ax(ax, title):
    ax.set_facecolor("#0a1628")   # ocean color
    for sp in ax.spines.values():
        sp.set_edgecolor(BORDER)
    ax.tick_params(colors=TEXT_DIM, labelsize=7)
    ax.set_title(title, color=TEXT_WHITE, fontsize=12,
                 fontweight="bold", pad=8)
    ax.grid(True, color=BORDER, linewidth=0.4, alpha=0.5, linestyle="--")


def add_district_labels(ax, gdf, col=None, fontsize=5.5):
    for _, row in gdf.iterrows():
        try:
            cx = row.geometry.centroid.x
            cy = row.geometry.centroid.y
            name = row["district"]
            short = name.replace(" ", "\n") if len(name) > 10 else name
            ax.text(cx, cy, short, ha="center", va="center",
                    fontsize=fontsize, color="white",
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.1", fc="#00000066",
                              ec="none", alpha=0.6))
        except Exception:
            pass


def make_choropleth_maps(gdf_stats, stats, out_path):
    fig = plt.figure(figsize=(22, 20), facecolor=BG)
    fig.patch.set_facecolor(BG)

    gs = GridSpec(2, 2, figure=fig,
                  hspace=0.12, wspace=0.08,
                  left=0.04, right=0.96, top=0.93, bottom=0.04)

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 0])
    ax4 = fig.add_subplot(gs[1, 1])

    SL_BOUNDS = [79.5, 5.85, 81.95, 9.9]

    def set_sl_extent(ax):
        ax.set_xlim(SL_BOUNDS[0], SL_BOUNDS[2])
        ax.set_ylim(SL_BOUNDS[1], SL_BOUNDS[3])

    style_map_ax(ax1, "Mean Susceptibility Score")
    score_min = gdf_stats["mean_score"].min()
    score_max = gdf_stats["mean_score"].max()
    norm_score = mcolors.Normalize(vmin=score_min, vmax=score_max)

    gdf_stats.plot(ax=ax1, color="#2a2a3a", edgecolor="#444", linewidth=0.5)
    valid_mask = gdf_stats["mean_score"].notna()
    gdf_stats[valid_mask].plot(
        ax=ax1, column="mean_score",
        cmap=SCORE_CMAP, norm=norm_score,
        edgecolor="#333", linewidth=0.6,
        legend=False,
    )
    set_sl_extent(ax1)
    add_district_labels(ax1, gdf_stats)
    sm1 = mcm.ScalarMappable(cmap=SCORE_CMAP, norm=norm_score)
    sm1.set_array([])
    cb1 = fig.colorbar(sm1, ax=ax1, fraction=0.03, pad=0.02, shrink=0.8)
    cb1.ax.tick_params(colors=TEXT_WHITE, labelsize=8)
    cb1.set_label("Mean Score (1–5)", color=TEXT_WHITE, fontsize=9)
    cb1.ax.yaxis.set_tick_params(color=TEXT_WHITE)

    style_map_ax(ax2, "Dominant Risk Class")
    gdf_stats.plot(ax=ax2, color="#2a2a3a", edgecolor="#444", linewidth=0.5)
    for cls_val, cls_col, cls_lbl in zip(range(1, 6), RISK_COLORS, RISK_LABELS):
        mask = gdf_stats["dominant_class"] == cls_val
        if mask.any():
            gdf_stats[mask].plot(ax=ax2, color=cls_col,
                                 edgecolor="#222", linewidth=0.7)
    set_sl_extent(ax2)
    add_district_labels(ax2, gdf_stats)
    patches = [mpatches.Patch(color=RISK_COLORS[i], label=RISK_LABELS[i])
               for i in range(5)]
    ax2.legend(handles=patches, loc="lower left", fontsize=8,
               framealpha=0.6, facecolor="#0d1117",
               edgecolor=BORDER, labelcolor="white",
               title="Dominant Class", title_fontsize=8)

    style_map_ax(ax3, "Mean Factor of Safety")
    gdf_stats["mean_fs_capped"] = gdf_stats["mean_fs"].clip(upper=4.0)
    fs_min = gdf_stats["mean_fs_capped"].min()
    fs_max = gdf_stats["mean_fs_capped"].max()
    norm_fs = mcolors.Normalize(vmin=fs_min, vmax=fs_max)
    gdf_stats.plot(ax=ax3, color="#2a2a3a", edgecolor="#444", linewidth=0.5)
    valid_fs = gdf_stats["mean_fs"].notna()
    gdf_stats[valid_fs].plot(
        ax=ax3, column="mean_fs_capped",
        cmap=FS_CMAP, norm=norm_fs,
        edgecolor="#333", linewidth=0.6,
        legend=False,
    )
    set_sl_extent(ax3)
    add_district_labels(ax3, gdf_stats)
    sm3 = mcm.ScalarMappable(cmap=FS_CMAP, norm=norm_fs)
    sm3.set_array([])
    cb3 = fig.colorbar(sm3, ax=ax3, fraction=0.03, pad=0.02, shrink=0.8)
    cb3.ax.tick_params(colors=TEXT_WHITE, labelsize=8)
    cb3.set_label("Mean FS (capped at 4)", color=TEXT_WHITE, fontsize=9)
    unstable = gdf_stats[gdf_stats["mean_fs"] < 1.0]
    if len(unstable) > 0:
        for _, row in unstable.iterrows():
            try:
                cx, cy = row.geometry.centroid.x, row.geometry.centroid.y
                ax3.plot(cx, cy, "r*", markersize=10, zorder=5)
            except Exception:
                pass

    style_map_ax(ax4, "High + Very High Risk Area (%)")
    hvh_max = max(gdf_stats["pct_hvh"].max(), 1.0)
    norm_hvh = mcolors.Normalize(vmin=0, vmax=hvh_max)
    gdf_stats.plot(ax=ax4, color="#2a2a3a", edgecolor="#444", linewidth=0.5)
    valid_hvh = gdf_stats["pct_hvh"].notna()
    gdf_stats[valid_hvh].plot(
        ax=ax4, column="pct_hvh",
        cmap=HVH_CMAP, norm=norm_hvh,
        edgecolor="#333", linewidth=0.6,
        legend=False,
    )
    set_sl_extent(ax4)
    add_district_labels(ax4, gdf_stats)
    sm4 = mcm.ScalarMappable(cmap=HVH_CMAP, norm=norm_hvh)
    sm4.set_array([])
    cb4 = fig.colorbar(sm4, ax=ax4, fraction=0.03, pad=0.02, shrink=0.8,
                       format=mticker.PercentFormatter())
    cb4.ax.tick_params(colors=TEXT_WHITE, labelsize=8)
    cb4.set_label("% High + Very High", color=TEXT_WHITE, fontsize=9)

    total_px = sum(s["total_px"] for s in stats)
    n_d = len(stats)
    fig.suptitle(
        f"Landslide Susceptibility — Sri Lanka  |  {n_d} Districts  |  {total_px:,} pixels",
        color=TEXT_WHITE, fontsize=17, fontweight="bold", y=0.97,
    )
    fig.text(0.5, 0.005,
             "Method: MCE-AHP (Yalcin 2008, Pradhan 2010) | SINMAP FS (Pack 1998) | Phase 1",
             ha="center", color=TEXT_DIM, fontsize=8)

    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    gc.collect()


def make_risk_analysis(stats, out_path):
    ranked   = sorted(stats, key=lambda s: s["mean_score"], reverse=True)
    top10    = ranked[:10]
    total_px = sum(s["total_px"] for s in stats)

    fig = plt.figure(figsize=(26, 20), facecolor=BG)
    gs  = GridSpec(3, 3, figure=fig,
                   hspace=0.52, wspace=0.40,
                   left=0.06, right=0.97, top=0.93, bottom=0.05)

    ax_top   = fig.add_subplot(gs[0, :2])
    ax_fs    = fig.add_subplot(gs[0, 2])
    ax_heat  = fig.add_subplot(gs[1, :2])
    ax_curve = fig.add_subplot(gs[1, 2])
    ax_scat  = fig.add_subplot(gs[2, 0])
    ax_pie   = fig.add_subplot(gs[2, 1])
    ax_table = fig.add_subplot(gs[2, 2])

    for ax in [ax_top, ax_fs, ax_heat, ax_curve, ax_scat, ax_pie, ax_table]:
        dark_ax(ax)

    names10  = [s["district"] for s in top10]
    scores10 = [s["mean_score"] for s in top10]
    bar_cols = [RISK_COLORS[4] if sc >= 4 else RISK_COLORS[3] if sc >= 3
                else RISK_COLORS[2] if sc >= 2 else RISK_COLORS[1] for sc in scores10]
    bars = ax_top.barh(range(len(names10)), scores10, color=bar_cols,
                       edgecolor=BORDER, linewidth=0.5, height=0.65)
    ax_top.set_yticks(range(len(names10)))
    ax_top.set_yticklabels(names10, fontsize=11, color=TEXT_WHITE)
    ax_top.invert_yaxis()
    ax_top.set_xlabel("Mean Susceptibility Score (1–5)", fontsize=10)
    ax_top.set_title("🏆  Top-10 Highest-Risk Districts  (Mean Susceptibility Score)",
                     fontsize=13, fontweight="bold", color=TEXT_WHITE, pad=8)
    ax_top.set_xlim(0, 5.6)
    ax_top.axvline(3.0, color="#58a6ff", lw=1.2, ls="--", alpha=0.7, label="Score = 3 (Moderate)")
    ax_top.axvline(4.0, color="#ff6b6b", lw=1.2, ls="--", alpha=0.7, label="Score = 4 (High)")
    ax_top.legend(fontsize=8, framealpha=0.3, facecolor=BG, edgecolor=BORDER, labelcolor="white")
    ax_top.grid(axis="x", color=BORDER, linewidth=0.5, alpha=0.6)
    for i, (bar, sc) in enumerate(zip(bars, scores10)):
        ax_top.text(sc + 0.04, bar.get_y() + bar.get_height()/2,
                    f"{sc:.3f}", va="center", color=TEXT_WHITE, fontsize=10, fontweight="bold")
    rank_colors = ["#FFD700", "#C0C0C0", "#CD7F32"] + ["#6e7681"] * 7
    for i in range(len(names10)):
        ax_top.text(-0.38, i, f"#{i+1}", va="center", ha="center",
                    color=rank_colors[i], fontsize=10, fontweight="bold",
                    transform=ax_top.get_yaxis_transform())

    fs_sorted = sorted(stats, key=lambda s: s["mean_fs"])
    ax_fs.barh(range(len(fs_sorted)),
               [s["mean_fs"] for s in fs_sorted],
               color=[RISK_COLORS[4] if s["mean_fs"] < 1 else
                      RISK_COLORS[3] if s["mean_fs"] < 1.5 else
                      RISK_COLORS[2] if s["mean_fs"] < 2 else
                      RISK_COLORS[1] for s in fs_sorted],
               edgecolor=BORDER, linewidth=0.4, height=0.65)
    ax_fs.set_yticks(range(len(fs_sorted)))
    ax_fs.set_yticklabels([s["district"] for s in fs_sorted], fontsize=7.5, color=TEXT_WHITE)
    ax_fs.invert_yaxis()
    ax_fs.axvline(1.0, color="#ff6b6b", lw=1.5, ls="--", alpha=0.9, label="FS = 1.0")
    ax_fs.axvline(1.5, color="#f39c12", lw=1.0, ls="--", alpha=0.7, label="FS = 1.5")
    ax_fs.set_xlabel("Mean Factor of Safety", fontsize=9)
    ax_fs.set_title("⚠  Districts by Mean FS\n(most unstable → top)", fontsize=11,
                    fontweight="bold", color=TEXT_WHITE, pad=6)
    ax_fs.legend(fontsize=7.5, framealpha=0.3, facecolor=BG, edgecolor=BORDER, labelcolor="white")
    ax_fs.grid(axis="x", color=BORDER, linewidth=0.5, alpha=0.6)

    class_keys = ["pct_vl","pct_l","pct_m","pct_h","pct_vh"]
    matrix = np.array([[s[k] for k in class_keys] for s in ranked])
    im_heat = ax_heat.imshow(matrix.T, aspect="auto", cmap="RdYlGn_r",
                             vmin=0, vmax=60, interpolation="nearest")
    ax_heat.set_xticks(range(len(ranked)))
    ax_heat.set_xticklabels([s["district"] for s in ranked],
                            rotation=45, ha="right", fontsize=7, color=TEXT_WHITE)
    ax_heat.set_yticks(range(5))
    ax_heat.set_yticklabels(RISK_LABELS, fontsize=9, color=TEXT_WHITE)
    ax_heat.set_title("Risk Class Heatmap — Districts × Class  (% area, sorted by mean score)",
                      fontsize=11, fontweight="bold", color=TEXT_WHITE, pad=8)
    cb_h = plt.colorbar(im_heat, ax=ax_heat, fraction=0.012, pad=0.01)
    cb_h.ax.tick_params(colors=TEXT_WHITE, labelsize=7)
    cb_h.set_label("% Area", color=TEXT_WHITE, fontsize=8)
    for r in range(5):
        for c in range(len(ranked)):
            val = matrix[c, r]
            ax_heat.text(c, r, f"{val:.0f}", ha="center", va="center",
                         fontsize=5.5, color="white" if val > 30 else TEXT_DIM)

    all_scores = np.concatenate([s["_score_sample"] for s in stats if len(s["_score_sample"]) > 0])
    all_scores = all_scores[~np.isnan(all_scores)]
    all_sorted = np.sort(all_scores)[::-1]
    cum_pct = np.linspace(0, 100, len(all_sorted))
    ax_curve.plot(cum_pct, all_sorted, color="#58a6ff", lw=1.5)
    ax_curve.fill_between(cum_pct, all_sorted, alpha=0.12, color="#58a6ff")
    for threshold, color, label in [(4.0, "#c0392b", "High"), (3.0, "#f39c12", "Moderate")]:
        pct_above = 100.0 * np.sum(all_sorted >= threshold) / len(all_sorted)
        ax_curve.axhline(threshold, color=color, lw=1, ls="--", alpha=0.8)
        ax_curve.axvline(pct_above, color=color, lw=0.8, ls=":", alpha=0.7)
        ax_curve.text(pct_above + 1, threshold + 0.08,
                      f"{pct_above:.1f}%\n≥{label}", color=color, fontsize=7.5, fontweight="bold")
    ax_curve.set_xlabel("Cumulative % of Pixels", fontsize=9)
    ax_curve.set_ylabel("Susceptibility Score", fontsize=9)
    ax_curve.set_title("Cumulative Area-at-Risk Curve\n(national)", fontsize=11,
                       fontweight="bold", color=TEXT_WHITE, pad=6)
    ax_curve.set_xlim(0, 100); ax_curve.set_ylim(0.5, 5.5)
    ax_curve.grid(color=BORDER, linewidth=0.5, alpha=0.6)

    xs = [s["mean_score"] for s in stats]
    ys = [s["pct_hvh"] for s in stats]
    ax_scat.scatter(xs, ys,
                    c=[RISK_COLORS[4] if x >= 4 else RISK_COLORS[3] if x >= 3
                       else RISK_COLORS[2] if x >= 2 else RISK_COLORS[1] for x in xs],
                    s=85, edgecolors=BG, linewidths=0.8, zorder=3)
    for s in sorted(stats, key=lambda s: s["mean_score"]+s["pct_hvh"], reverse=True)[:7]:
        ax_scat.annotate(s["district"],
                         xy=(s["mean_score"], s["pct_hvh"]),
                         xytext=(5, 3), textcoords="offset points",
                         color=TEXT_WHITE, fontsize=6.5, fontweight="bold")
    if len(xs) > 2:
        z = np.polyfit(xs, ys, 1)
        xr = np.linspace(min(xs), max(xs), 100)
        ax_scat.plot(xr, np.poly1d(z)(xr), "--", color=TEXT_DIM, lw=1, alpha=0.7, label="Trend")
    ax_scat.set_xlabel("Mean Susceptibility Score", fontsize=9)
    ax_scat.set_ylabel("High + Very High Area (%)", fontsize=9)
    ax_scat.set_title("Mean Score vs High-Risk Area %", fontsize=11,
                      fontweight="bold", color=TEXT_WHITE, pad=6)
    ax_scat.grid(color=BORDER, linewidth=0.5, alpha=0.6)
    ax_scat.legend(fontsize=7.5, framealpha=0.3, facecolor=BG, edgecolor=BORDER, labelcolor="white")

    agg_counts = [sum(s[k] * s["total_px"] / 100.0 for s in stats)
                  for k in ["pct_vl","pct_l","pct_m","pct_h","pct_vh"]]
    agg_pcts = [100.0 * c / total_px for c in agg_counts]
    wedges, _, _ = ax_pie.pie(
        agg_counts, colors=RISK_COLORS,
        autopct=lambda p: f"{p:.1f}%" if p > 1.5 else "",
        startangle=140,
        wedgeprops={"edgecolor": BG, "linewidth": 1.5},
        textprops={"color": "white", "fontsize": 9},
    )
    ax_pie.set_title("National Risk Class\nComposition", fontsize=11,
                     fontweight="bold", color=TEXT_WHITE, pad=6)
    ax_pie.legend(wedges,
                  [f"{RISK_LABELS[i]}  ({agg_pcts[i]:.1f}%)" for i in range(5)],
                  loc="lower center", bbox_to_anchor=(0.5, -0.24),
                  fontsize=7.5, framealpha=0.2, facecolor=BG,
                  edgecolor=BORDER, labelcolor="white", ncol=2)

    ax_table.axis("off")
    ax_table.set_title("📋  District Risk League Table", fontsize=11,
                       fontweight="bold", color=TEXT_WHITE, pad=6)
    headers  = ["Rank", "District", "Score", "FS", "H+VH%"]
    col_x    = [0.01, 0.13, 0.50, 0.65, 0.80]
    col_w    = [0.12, 0.37, 0.15, 0.15, 0.16]
    row_h    = 0.063
    max_rows = min(13, len(ranked))

    for ci, (hdr, cx, cw) in enumerate(zip(headers, col_x, col_w)):
        ax_table.add_patch(mpatches.FancyBboxPatch(
            (cx, 0.97 - row_h), cw - 0.005, row_h - 0.004,
            boxstyle="round,pad=0.003", facecolor="#c0392b",
            edgecolor="none", transform=ax_table.transAxes))
        ax_table.text(cx + cw/2, 0.97 - row_h/2, hdr,
                      transform=ax_table.transAxes,
                      ha="center", va="center", color="white", fontsize=8, fontweight="bold")

    for ri, s in enumerate(ranked[:max_rows]):
        y  = 0.97 - (ri + 1) * row_h
        bg = "#3d1f1f" if ri == 0 else "#3d2b1f" if ri == 1 else \
             "#2d2b1f" if ri == 2 else "#1c2128" if ri % 2 == 0 else "#22272e"
        ax_table.add_patch(mpatches.FancyBboxPatch(
            (0.01, y), 0.98, row_h - 0.004,
            boxstyle="round,pad=0.003", facecolor=bg,
            edgecolor="none", transform=ax_table.transAxes))
        rk_col = ["#FFD700", "#C0C0C0", "#CD7F32"][ri] if ri < 3 else TEXT_DIM
        vals   = [f"#{ri+1}", s["district"][:16], f"{s['mean_score']:.3f}",
                  f"{s['mean_fs']:.2f}", f"{s['pct_hvh']:.1f}%"]
        fcolors= [rk_col, TEXT_WHITE, "#e67e22", "#2ecc71", "#c0392b"]
        for v, cx, cw, fc in zip(vals, col_x, col_w, fcolors):
            ax_table.text(cx + cw/2, y + row_h/2, v,
                          transform=ax_table.transAxes,
                          ha="center", va="center", color=fc, fontsize=7.5)
    if len(ranked) > max_rows:
        ax_table.text(0.5, 0.97 - (max_rows + 1.3) * row_h,
                      f"… +{len(ranked)-max_rows} more",
                      transform=ax_table.transAxes,
                      ha="center", color=TEXT_DIM, fontsize=7)

    fig.suptitle(
        f"Landslide Susceptibility — Cumulative National Analysis  |  "
        f"{len(stats)} Districts  |  {total_px:,} pixels",
        color=TEXT_WHITE, fontsize=16, fontweight="bold", y=0.97
    )
    fig.text(0.5, 0.002,
             "Method: MCE-AHP (Yalcin 2008) | SINMAP FS (Pack 1998) | Phase 1",
             ha="center", color=TEXT_DIM, fontsize=8)

    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    gc.collect()

def print_console_summary(stats):
    return

def main():
    districts = discover_districts(OUTPUT_BASE)
    if not districts:
        return
    stats = build_stats(districts, OUTPUT_BASE)
    if not stats:
        return

    print_console_summary(stats)

    dist_gdf = load_district_geodataframe(VILLAGE_SHP, DISTRICT_COL)

    gdf_stats = merge_stats_to_gdf(dist_gdf, stats)

    out1 = os.path.join(OUTPUT_BASE, "cumulative_susceptibility_overview.png")
    out2 = os.path.join(OUTPUT_BASE, "cumulative_risk_analysis.png")

    make_choropleth_maps(gdf_stats, stats, out1)

    del dist_gdf, gdf_stats
    gc.collect()

    make_risk_analysis(stats, out2)


if __name__ == "__main__":
    main()