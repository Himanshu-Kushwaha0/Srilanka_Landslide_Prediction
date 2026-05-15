"""
Sri Lanka Landslide Risk Map Visualiser
========================================
Reads one or more LandslideRisk_YearWise_*.shp files and produces
publication-quality maps that match the PPT style shown:
  • Filled district polygons coloured by risk class
  • District name labels
  • Coordinate axes (lat/lon)
  • Clean legend

FIXES vs original:
  • risk_class column is now explicitly mapped to colours BEFORE plotting
  • Each polygon is plotted individually with facecolor set from the
    risk_class value — so QGIS/matplotlib never falls back to a default purple
  • linewidth=0  on all polygon plots → no black border lines / vertex dots
  • dissolve() called per (district, year, risk_class) before plotting so
    stacked duplicate geometries are collapsed into one shape per class

MODES
-----
1. SINGLE DISTRICT, ONE YEAR
   python visualise_risk.py
       --shp "/path/to/Kandy/LandslideRisk_YearWise_Kandy.shp"
       --year 2010

2. SINGLE DISTRICT, ALL YEARS  (grid of small multiples)
   python visualise_risk.py \\
       --shp output/Kandy/LandslideRisk_YearWise_Kandy.shp \\
       --all_years

3. MULTIPLE SHP FILES merged, one year
   python visualise_risk.py \\
       --shp output/Kandy/LandslideRisk_YearWise_Kandy.shp \\
              output/Nuwara_Eliya/LandslideRisk_YearWise_Nuwara_Eliya.shp \\
       --year 2010 --cumulative

4. MULTIPLE SHP FILES merged, all years  (grid)
   python visualise_risk.py \\
       --shp output/Kandy/LandslideRisk_YearWise_Kandy.shp \\
              output/Nuwara_Eliya/LandslideRisk_YearWise_Nuwara_Eliya.shp \\
       --all_years

OPTIONS
-------
  --shp          One or more shapefile paths (space-separated)
  --year         Calendar year to display (integer)
  --all_years    Plot every year as a small-multiples grid
  --cumulative   Merge all loaded SHPs into one island-wide map
  --out_dir      Folder for saved PNG files (default: ./risk_maps)
  --dpi          Output resolution (default: 150)
  --no_labels    Suppress district name labels
  --background   Optional full-Sri-Lanka boundary SHP for grey backdrop
"""

import os
import glob
import argparse
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe

warnings.filterwarnings('ignore')
matplotlib.rcParams['figure.facecolor'] = '#0d1b2a'

# ── Risk class colour scheme ──────────────────────────────────────────────────
# FILL colours — used for polygon facecolor
RISK_FILL = {
    'Low':       '#2ecc71',   # green
    'Moderate':  '#f39c12',   # amber
    'High':      '#e67e22',   # orange
    'Very High': '#c0392b',   # red
}

# EDGE colours — set to SAME as fill so no dark border line appears
# Setting linewidth=0 is the primary fix; matching edge is a backup.
RISK_EDGE = {
    'Low':       '#2ecc71',
    'Moderate':  '#f39c12',
    'High':      '#e67e22',
    'Very High': '#c0392b',
}

# Draw order — lowest risk first so higher risk renders on top
RISK_ORDER = ['Low', 'Moderate', 'High', 'Very High']

# Background / axes colours
BG_MAP    = '#0d1b2a'
BG_OCEAN  = '#1a2e45'
FG_AXES   = '#c8d8e8'
FG_TITLE  = '#ffffff'
EDGE_MISS = '#455a64'   # grey for districts with unknown risk class


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description='Sri Lanka Landslide Risk Map Visualiser'
    )
    p.add_argument('--shp', nargs='+', required=True,
                   help='One or more LandslideRisk_YearWise_*.shp paths')
    p.add_argument('--year', type=int, default=None,
                   help='Year to display (single-year mode)')
    p.add_argument('--all_years', action='store_true',
                   help='Produce a small-multiples grid for every year')
    p.add_argument('--cumulative', action='store_true',
                   help='Merge all loaded SHPs into one map')
    p.add_argument('--out_dir', default='./risk_maps',
                   help='Output folder for PNG files (default: ./risk_maps)')
    p.add_argument('--dpi', type=int, default=150,
                   help='Output resolution in DPI (default: 150)')
    p.add_argument('--no_labels', action='store_true',
                   help='Suppress district name labels')
    p.add_argument('--background', default=None,
                   help='Optional full-Sri-Lanka boundary SHP for grey backdrop')
    return p.parse_args()


# ── Helpers ───────────────────────────────────────────────────────────────────
def normalise_risk(raw):
    """Map any raw risk string to one of the four canonical classes."""
    if not isinstance(raw, str):
        return 'Low'
    r = raw.strip().lower()
    if 'very' in r and 'high' in r:
        return 'Very High'
    if 'high'     in r:
        return 'High'
    if 'moderate' in r:
        return 'Moderate'
    return 'Low'


def normalise_col(gdf, possible_names):
    """Find a column by name case-insensitively."""
    cols_lower = {c.lower(): c for c in gdf.columns}
    for n in possible_names:
        if n.lower() in cols_lower:
            return cols_lower[n.lower()]
    return None


def load_and_merge_shp(shp_paths):
    """
    Load one or more shapefiles and return a single normalised GeoDataFrame.
    Key fix: risk_class is normalised to exactly one of the four canonical
    strings so the colour lookup always succeeds.
    """
    gdfs = []
    for path in shp_paths:
        expanded = glob.glob(path)
        if not expanded:
            expanded = [path]
        for p in expanded:
            try:
                g = gpd.read_file(p)
                g['_src'] = os.path.basename(p)
                gdfs.append(g)
                print(f"  ✓ Loaded {len(g):>5} rows  ←  {os.path.basename(p)}")
            except Exception as e:
                print(f"  [WARN] Cannot read {p}: {e}")

    if not gdfs:
        raise FileNotFoundError("No valid shapefiles loaded.")

    gdf = pd.concat(gdfs, ignore_index=True)

    # Ensure WGS-84
    if gdf.crs is None:
        gdf = gdf.set_crs('EPSG:4326')
    else:
        gdf = gdf.to_crs('EPSG:4326')

    # ── Rename columns to standard names ─────────────────────────────────
    col_aliases = {
        'district':   ['district'],
        'year':       ['year'],
        'risk_class': ['risk_class', 'riskclass', 'risk'],
        'comp_risk':  ['comp_risk', 'comp_yr', 'composite_risk', 'compscore'],
        'rf_mm':      ['rf_mm', 'rainfall_mm', 'rainfall'],
        'wsi':        ['wsi'],
        'trig_rf':    ['trig_rf', 'trigger_rf_mm'],
    }
    renames = {}
    for dst, candidates in col_aliases.items():
        src = normalise_col(gdf, candidates)
        if src and src != dst:
            renames[src] = dst
    if renames:
        gdf = gdf.rename(columns=renames)

    # Ensure all expected columns exist
    for col in ['district', 'year', 'risk_class', 'comp_risk', 'rf_mm', 'wsi', 'trig_rf']:
        if col not in gdf.columns:
            gdf[col] = None

    # ── Type coercion ─────────────────────────────────────────────────────
    gdf['year']      = pd.to_numeric(gdf['year'],      errors='coerce').astype('Int64')
    gdf['comp_risk'] = pd.to_numeric(gdf['comp_risk'], errors='coerce')
    gdf['rf_mm']     = pd.to_numeric(gdf['rf_mm'],     errors='coerce')
    gdf['wsi']       = pd.to_numeric(gdf['wsi'],       errors='coerce')

    # ── CRITICAL: normalise risk_class to canonical strings ───────────────
    # This is what makes the colour lookup work. Raw DBF values can have
    # trailing spaces, wrong casing, etc.
    gdf['risk_class'] = gdf['risk_class'].apply(normalise_risk)

    # ── Assign fill / edge colours as new columns ─────────────────────────
    # Storing them in the GDF means every subsequent plot call just reads
    # gdf['fill_color'] rather than doing a dict lookup per row.
    gdf['fill_color'] = gdf['risk_class'].apply(
        lambda x: RISK_FILL.get(x, '#455a64')   # grey fallback for unknown
    )
    gdf['edge_color'] = gdf['risk_class'].apply(
        lambda x: RISK_EDGE.get(x, '#455a64')
    )

    yrs = sorted(gdf['year'].dropna().unique())
    print(f"\n  Total rows   : {len(gdf)}")
    print(f"  Districts    : {sorted(gdf['district'].dropna().unique())}")
    print(f"  Year range   : {int(yrs[0])} – {int(yrs[-1])}  ({len(yrs)} years)")
    print(f"  Risk classes : {gdf['risk_class'].value_counts().to_dict()}")
    return gdf


# ── Core draw function ────────────────────────────────────────────────────────
def draw_risk_map(ax, gdf_year, title, bg_gdf=None, show_labels=True):
    """
    Draw one year's risk map onto ax.

    FIX EXPLANATION
    ---------------
    Original code called  gdf_year.plot(color=RISK_PALETTE[rc])
    which coloured ALL rows of the filtered subset the same colour — correct.
    BUT if gdf_year still had stacked duplicate geometries (123 polygons on
    top of each other for a single district) QGIS / matplotlib would render
    all their outlines, creating black dot/line artefacts.

    We fix this with TWO changes:
      1. dissolve()  — collapse duplicate geometries for the same
                        (district, risk_class) group into one shape.
                        This removes all stacking.
      2. linewidth=0 — no polygon border is drawn at all.
                        Even if a stray duplicate slips through, there is
                        no border line to create black artefacts.
    """
    ax.set_facecolor(BG_OCEAN)

    # ── Optional full-island grey backdrop ────────────────────────────────
    if bg_gdf is not None and not bg_gdf.empty:
        bg_gdf.plot(ax=ax, color='#1e3a5a', edgecolor='#2e5c8a',
                    linewidth=0.4, zorder=1)

    # ── FIX 1: dissolve stacked duplicate geometries ─────────────────────
    # Each (district, risk_class) pair gets exactly ONE polygon shape.
    # Without this, 123 identical polygons stack on top of each other and
    # their outlines render as black dots / lines.
    if not gdf_year.empty:
        try:
            gdf_plot = (
                gdf_year
                .dissolve(by=['district', 'risk_class'], as_index=False)
                .copy()
            )
            # Re-attach numeric summary columns (mean across dissolved rows)
            for num_col in ['comp_risk', 'rf_mm', 'wsi', 'trig_rf']:
                if num_col in gdf_year.columns:
                    agg = gdf_year.groupby(
                        ['district', 'risk_class']
                    )[num_col].mean().reset_index()
                    gdf_plot = gdf_plot.drop(
                        columns=[num_col], errors='ignore'
                    ).merge(agg, on=['district', 'risk_class'], how='left')
            # Re-assign colours after dissolve
            gdf_plot['fill_color'] = gdf_plot['risk_class'].apply(
                lambda x: RISK_FILL.get(x, '#455a64')
            )
        except Exception:
            # dissolve failed (e.g. invalid geometry) — use original
            gdf_plot = gdf_year.copy()
    else:
        gdf_plot = gdf_year.copy()

    # ── FIX 2: plot each risk class with explicit facecolor, linewidth=0 ──
    # Iterating by risk class in RISK_ORDER ensures low-risk draws first
    # (bottom) and high-risk draws on top, which is the correct visual order.
    for rc in RISK_ORDER:
        sub = gdf_plot[gdf_plot['risk_class'] == rc]
        if sub.empty:
            continue
        sub.plot(
            ax=ax,
            color=RISK_FILL[rc],      # explicit fill — no purple default
            edgecolor='none',          # NO edge line  → no black dots
            linewidth=0,               # belt-and-braces: zero width border
            zorder=2,
        )

    # Districts with unrecognised risk class → grey
    missing = gdf_plot[~gdf_plot['risk_class'].isin(RISK_ORDER)]
    if not missing.empty:
        missing.plot(ax=ax, color='#455a64', edgecolor='none',
                     linewidth=0, zorder=2)

    # ── District name + score labels ──────────────────────────────────────
    if show_labels and not gdf_plot.empty:
        for _, row in gdf_plot.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            try:
                cx = row.geometry.centroid.x
                cy = row.geometry.centroid.y
            except Exception:
                continue

            dist_name = str(row.get('district', ''))
            score_str = ''
            if 'comp_risk' in row.index and pd.notna(row.get('comp_risk')):
                score_str = f"\n{row['comp_risk']:.3f}"

            ax.text(
                cx, cy,
                dist_name + score_str,
                fontsize=6.5,
                ha='center', va='center',
                fontweight='bold',
                color='white',
                path_effects=[pe.withStroke(linewidth=2.0, foreground='black')],
                zorder=5,
                linespacing=1.3,
            )

    # ── Title ─────────────────────────────────────────────────────────────
    ax.set_title(title, fontsize=11, color=FG_TITLE,
                 fontweight='bold', pad=8, loc='center')

    # ── Axis cosmetics ────────────────────────────────────────────────────
    ax.tick_params(colors=FG_AXES, labelsize=7.5)
    for spine in ax.spines.values():
        spine.set_edgecolor('#2e5c8a')
        spine.set_linewidth(0.6)
    ax.set_xlabel('Longitude', fontsize=8, color=FG_AXES, labelpad=4)
    ax.set_ylabel('Latitude',  fontsize=8, color=FG_AXES, labelpad=4)

    # Auto-fit bounds with padding
    if not gdf_plot.empty:
        xmin, ymin, xmax, ymax = gdf_plot.total_bounds
        pad_x = max((xmax - xmin) * 0.08, 0.1)
        pad_y = max((ymax - ymin) * 0.08, 0.1)
        ax.set_xlim(xmin - pad_x, xmax + pad_x)
        ax.set_ylim(ymin - pad_y, ymax + pad_y)


def add_legend(fig, ax, gdf_year, loc='lower left'):
    """Add risk-class legend with district counts."""
    counts  = gdf_year['risk_class'].value_counts()
    patches = []
    for rc in RISK_ORDER:
        cnt = counts.get(rc, 0)
        patches.append(
            mpatches.Patch(
                facecolor=RISK_FILL[rc],
                edgecolor=RISK_EDGE[rc],
                linewidth=0.8,
                label=f'{rc}  ({cnt})',
            )
        )
    leg = ax.legend(
        handles=patches,
        loc=loc,
        frameon=True,
        framealpha=0.85,
        facecolor='#0d1b2a',
        edgecolor='#2e5c8a',
        fontsize=8,
        title='Risk Class',
        title_fontsize=8.5,
        labelcolor=FG_AXES,
    )
    leg.get_title().set_color(FG_TITLE)
    return leg


def add_info_box(ax, gdf_year, year):
    """Small statistics box in the top-right corner."""
    if gdf_year.empty:
        return
    rf_mean  = gdf_year['rf_mm'].mean()
    wsi_mean = gdf_year['wsi'].mean()
    n_dist   = gdf_year['district'].nunique()
    lines    = [f"Year      : {year}", f"Districts : {n_dist}"]
    if pd.notna(rf_mean):
        lines.append(f"Avg RF    : {rf_mean:.0f} mm")
    if pd.notna(wsi_mean):
        lines.append(f"Avg WSI   : {wsi_mean:.4f}")

    ax.text(
        0.99, 0.99, '\n'.join(lines),
        transform=ax.transAxes,
        ha='right', va='top',
        fontsize=7.5, color=FG_AXES,
        fontfamily='monospace',
        bbox=dict(
            boxstyle='round,pad=0.4',
            facecolor='#0d1b2a',
            edgecolor='#2e5c8a',
            alpha=0.85,
        ),
        zorder=10,
    )


# ── MODE 1 / 3 — Single year ──────────────────────────────────────────────────
def plot_single_year(gdf, year, out_dir, dpi,
                     show_labels=True, cumulative=False, bg_gdf=None):
    gdf_yr = gdf[gdf['year'] == year].copy()
    if gdf_yr.empty:
        print(f"  [WARN] No data for year {year}")
        return

    districts = sorted(gdf_yr['district'].dropna().unique())
    tag   = 'AllDistricts' if cumulative else '_'.join(
        d.replace(' ', '') for d in districts)
    title = (f"Landslide Risk Class — {year}\n"
             f"Sri Lanka  |  {', '.join(districts)}")

    fig, ax = plt.subplots(
        figsize=(8, 11),
        facecolor=BG_MAP,
        subplot_kw={'facecolor': BG_OCEAN},
    )
    fig.subplots_adjust(left=0.10, right=0.95, top=0.93, bottom=0.07)

    draw_risk_map(ax, gdf_yr, title, bg_gdf=bg_gdf, show_labels=show_labels)
    add_legend(fig, ax, gdf_yr, loc='lower left')
    add_info_box(ax, gdf_yr, year)

    fname = os.path.join(out_dir, f'risk_map_{tag}_{year}.png')
    fig.savefig(fname, dpi=dpi, bbox_inches='tight', facecolor=BG_MAP)
    print(f"  Saved: {fname}")
    plt.show()
    plt.close(fig)


# ── MODE 2 / 5 — All years grid ───────────────────────────────────────────────
def plot_all_years(gdf, out_dir, dpi,
                   show_labels=True, cumulative=False, bg_gdf=None):
    years = sorted(gdf['year'].dropna().unique())
    n     = len(years)
    if n == 0:
        print("  [WARN] No years found.")
        return

    ncols = min(6, n)
    nrows = int(np.ceil(n / ncols))
    fig_w = ncols * 3.4
    fig_h = nrows * 4.5 + 0.8

    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=(fig_w, fig_h),
        facecolor=BG_MAP,
        subplot_kw={'facecolor': BG_OCEAN},
    )
    fig.subplots_adjust(hspace=0.35, wspace=0.12,
                        left=0.04, right=0.97,
                        top=0.95, bottom=0.04)
    axes_flat = np.array(axes).flatten()

    districts_all = sorted(gdf['district'].dropna().unique())
    tag = 'AllDistricts' if cumulative else '_'.join(
        d.replace(' ', '') for d in districts_all)

    fig.suptitle(
        f'Sri Lanka Landslide Risk — Year-Wise  |  '
        f'{"All Districts" if cumulative else ", ".join(districts_all)}',
        fontsize=12, color=FG_TITLE, fontweight='bold', y=0.98,
    )

    for i, yr in enumerate(years):
        ax     = axes_flat[i]
        gdf_yr = gdf[gdf['year'] == yr]
        draw_risk_map(ax, gdf_yr, str(int(yr)),
                      bg_gdf=bg_gdf, show_labels=show_labels)
        add_info_box(ax, gdf_yr, int(yr))

    # Hide unused subplot slots
    for j in range(n, len(axes_flat)):
        axes_flat[j].set_visible(False)

    # Shared legend at bottom
    patches = [
        mpatches.Patch(
            facecolor=RISK_FILL[rc],
            edgecolor=RISK_EDGE[rc],
            linewidth=0.8,
            label=rc,
        )
        for rc in RISK_ORDER
    ]
    fig.legend(
        handles=patches,
        loc='lower center', ncol=len(RISK_ORDER),
        frameon=True, framealpha=0.85,
        facecolor='#0d1b2a', edgecolor='#2e5c8a',
        fontsize=9, labelcolor=FG_AXES,
        title='Risk Class', title_fontsize=9.5,
        bbox_to_anchor=(0.5, 0.01),
    )

    fname = os.path.join(out_dir, f'risk_map_{tag}_ALL_YEARS.png')
    fig.savefig(fname, dpi=dpi, bbox_inches='tight', facecolor=BG_MAP)
    print(f"  Saved: {fname}")
    plt.show()
    plt.close(fig)


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    print("=" * 65)
    print("Sri Lanka Landslide Risk Map Visualiser")
    print("=" * 65)

    print(f"\nLoading {len(args.shp)} shapefile(s)…")
    gdf = load_and_merge_shp(args.shp)

    bg_gdf = None
    if args.background:
        try:
            bg_gdf = gpd.read_file(args.background).to_crs('EPSG:4326')
            print(f"  Background SHP loaded: {args.background}")
        except Exception as e:
            print(f"  [WARN] Background SHP failed: {e}")

    show_labels = not args.no_labels
    print()

    if args.all_years:
        print("Mode: ALL YEARS (small-multiples grid)")
        plot_all_years(gdf, args.out_dir, args.dpi,
                       show_labels=show_labels,
                       cumulative=args.cumulative,
                       bg_gdf=bg_gdf)

    elif args.year is not None:
        print(f"Mode: SINGLE YEAR ({args.year})"
              + ("  [cumulative]" if args.cumulative else ""))
        plot_single_year(gdf, args.year, args.out_dir, args.dpi,
                         show_labels=show_labels,
                         cumulative=args.cumulative,
                         bg_gdf=bg_gdf)

    else:
        latest = int(gdf['year'].dropna().max())
        print(f"No --year specified — defaulting to latest year: {latest}")
        plot_single_year(gdf, latest, args.out_dir, args.dpi,
                         show_labels=show_labels,
                         cumulative=args.cumulative,
                         bg_gdf=bg_gdf)

    print("\nDone.  Maps saved to:", args.out_dir)


if __name__ == '__main__':
    main()