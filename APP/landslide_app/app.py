"""
Sri Lanka Landslide Risk — Web Application Backend
====================================================
Flask server that:
  1. Serves the UI (index.html)
  2. /api/districts        → list all available districts from susceptibility SHPs
  3. /api/susceptibility   → render static susceptibility map PNG for a district
  4. /api/run_model        → run landslide_model_v3_yearwise.py for chosen districts
  5. /api/risk_map         → render year-wise risk map PNG via visualise_risk.py
  6. /api/years            → list available years for a district from SHP output
  7. /api/risk_data        → return JSON attributes for a district+year from CSV

PATHS (edit these to match your machine):
  SHP_ROOT    = path to Susceptibility_Phase1_v1 folder
  RAINFALL    = path to rainfall CSV
  LANDSLIDE   = path to landslides_Sri_Lanka.csv
  OUTPUT_DIR  = where model writes SHP output
  MODEL_SCRIPT    = path to landslide_model_v3_yearwise.py
  VISUALISE_SCRIPT= path to visualise_risk.py
"""

import os, glob, json, subprocess, threading, time
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory, Response
from flask_cors import CORS
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from chatbot_flask_integration import setup_chatbot_routes, configure_chatbot
    CHATBOT_AVAILABLE = True
except ImportError:
    CHATBOT_AVAILABLE = False
    print("[WARNING] Chatbot integration not available")

# ══════════════════════════════════════════════════════════════════════════════
# ▶▶  CONFIGURE THESE PATHS FOR YOUR MACHINE  ◀◀
# ══════════════════════════════════════════════════════════════════════════════
# BASE_DIR points to APP/ folder (parent of landslide_app/)
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHP_ROOT         = os.path.join(BASE_DIR, "DATA", "Susceptibility_Phase1_v1")
RAINFALL_CSV     = os.path.join(BASE_DIR, "Srilanka Rainfall Year wise", "Srilanka Rainfall year wise.csv")
LANDSLIDE_CSV    = os.path.join(BASE_DIR, "DATA", "landslides_Sri_Lanka.csv")
OUTPUT_DIR       = os.path.join(BASE_DIR, "Prediction Script", "output_shapefiles")
MODEL_SCRIPT     = os.path.join(BASE_DIR, "Prediction Script", "landslide_model_v2_filtered.py")
VISUALISE_SCRIPT = os.path.join(BASE_DIR, "Prediction Script", "visualise_risk.py")  
PYTHON_BIN       = sys.executable  # use current Python interpreter
# ══════════════════════════════════════════════════════════════════════════════

RISK_FILL = {
    'Low':       '#2ecc71',
    'Moderate':  '#f39c12',
    'High':      '#e67e22',
    'Very High': '#c0392b',
}
SUSC_FILL = {
    'very low':  '#27ae60',
    'low':       '#82e0aa',
    'moderate':  '#f39c12',
    'high':      '#c0392b',
    'very high': '#7b241c',
}

app = Flask(__name__)
app.secret_key = 'landslide-prediction-secret-key-2024'
CORS(app)

# Setup chatbot if available
if CHATBOT_AVAILABLE:
    try:
        configure_chatbot({'provider': 'mock'})
        setup_chatbot_routes(app)
        print("[OK] Chatbot routes registered")
    except Exception as e:
        print(f"[ERROR] Chatbot setup failed: {e}")

# In-memory job store  { job_id: { status, log, error } }
_jobs = {}
_jobs_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Static file helpers
# ─────────────────────────────────────────────────────────────────────────────
MAPS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'maps')
os.makedirs(MAPS_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Routes — UI
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)


# ─────────────────────────────────────────────────────────────────────────────
# API — health check
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/health')
@app.route('/api/health')
def api_health():
    """Simple health endpoint for the app and required file checks."""
    try:
        files = {
            'SHP_ROOT': SHP_ROOT,
            'RAINFALL_CSV': RAINFALL_CSV,
            'LANDSLIDE_CSV': LANDSLIDE_CSV,
            'OUTPUT_DIR': OUTPUT_DIR,
            'MODEL_SCRIPT': MODEL_SCRIPT,
            'VISUALISE_SCRIPT': VISUALISE_SCRIPT,
        }
        missing = [name for name, path in files.items() if not os.path.exists(path)]
        status = 'ok' if not missing else 'degraded'
        return jsonify({
            'status': status,
            'missing_files': missing,
            'checked_files': list(files.keys()),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# API — list districts
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/districts')
def api_districts():
    """Scan SHP_ROOT for district folders and return sorted list."""
    try:
        # Two discovery methods: (a) district subfolders with *susceptibility.shp
        shp_files = glob.glob(
            os.path.join(SHP_ROOT, '**', '*susceptibility.shp'), recursive=True
        )
        districts = set()
        for s in shp_files:
            folder = os.path.basename(os.path.dirname(s))
            if folder and folder.lower() not in ('', '.', 'output', 'susceptibility_phase1_v1'):
                districts.add(folder.replace('_', ' ').title())
        # Also check output_dir for already-processed districts
        if os.path.isdir(OUTPUT_DIR):
            for d in os.listdir(OUTPUT_DIR):
                full = os.path.join(OUTPUT_DIR, d)
                if os.path.isdir(full):
                    shps = glob.glob(os.path.join(full, '*.shp'))
                    if shps:
                        districts.add(d.replace('_', ' ').title())
        return jsonify(sorted(districts))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# API — render STATIC susceptibility map for a district
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/susceptibility')
def api_susceptibility():
    district = request.args.get('district', '').strip()
    if not district:
        return jsonify({'error': 'district param required'}), 400

    cache_name = f"susc_{district.replace(' ', '_')}.png"
    cache_path = os.path.join(MAPS_DIR, cache_name)

    if not os.path.exists(cache_path):
        # Find the susceptibility SHP for this district
        pattern = os.path.join(SHP_ROOT, '**', '*susceptibility.shp')
        shp_files = glob.glob(pattern, recursive=True)
        match = None
        for s in shp_files:
            folder = os.path.basename(os.path.dirname(s))
            fname  = os.path.basename(s)
            candidate = (folder or fname.replace('_susceptibility.shp','')
                         ).replace('_', ' ').title()
            if candidate.lower() == district.lower():
                match = s
                break
        if not match:
            return jsonify({'error': f'No susceptibility SHP found for: {district}'}), 404

        try:
            gdf = gpd.read_file(match)
            gdf.columns = [c.lower().strip() for c in gdf.columns]
            name_col = next((c for c in ['class_name','classname','class',
                                          'susc_class','suscept','label','name']
                              if c in gdf.columns), None)
            fig, ax = plt.subplots(1, 1, figsize=(8, 7), facecolor='#0d1b2a')
            ax.set_facecolor('#1a2e45')

            if name_col:
                gdf['_cls'] = gdf[name_col].str.strip().str.lower()
                for cls, fill in SUSC_FILL.items():
                    sub = gdf[gdf['_cls'] == cls]
                    if not sub.empty:
                        sub.plot(ax=ax, color=fill, edgecolor='none',
                                 linewidth=0, label=cls.title(), zorder=2)
            else:
                gdf.plot(ax=ax, color='#4a90d9', edgecolor='none',
                         linewidth=0, zorder=2)

            ax.set_title(f'{district} — Landslide Susceptibility',
                         fontsize=13, fontweight='bold', color='white', pad=10)
            ax.set_xlabel('Longitude', fontsize=9, color='#aaaaaa')
            ax.set_ylabel('Latitude',  fontsize=9, color='#aaaaaa')
            ax.tick_params(colors='#aaaaaa', labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor('#334455')

            patches = [mpatches.Patch(color=v, label=k.title())
                       for k, v in SUSC_FILL.items()]
            ax.legend(handles=patches, loc='lower right',
                      facecolor='#1a2e45', edgecolor='#334455',
                      labelcolor='white', fontsize=8)

            plt.tight_layout()
            plt.savefig(cache_path, dpi=130, bbox_inches='tight',
                        facecolor='#0d1b2a')
            plt.close()
        except Exception as e:
            plt.close('all')
            return jsonify({'error': str(e)}), 500

    return send_file(cache_path, mimetype='image/png')


# ─────────────────────────────────────────────────────────────────────────────
# API — run the prediction model (async job)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/run_model', methods=['POST'])
def api_run_model():
    data = request.get_json(force=True)
    districts = data.get('districts', [])
    year_start = data.get('year_start', None)
    year_end   = data.get('year_end',   None)

    if not districts:
        return jsonify({'error': 'districts list required'}), 400

    job_id = str(int(time.time() * 1000))
    with _jobs_lock:
        _jobs[job_id] = {'status': 'running', 'log': '', 'error': None}

    def run():
        cmd = [
            PYTHON_BIN, MODEL_SCRIPT,
            '--shp_root',  SHP_ROOT,
            '--rainfall',  RAINFALL_CSV,
            '--landslide', LANDSLIDE_CSV,
            '--out_dir',   OUTPUT_DIR,
            '--districts', *districts,
        ]
        if year_start:
            cmd += ['--year_start', str(year_start)]
        if year_end:
            cmd += ['--year_end', str(year_end)]

        try:
            # Set UTF-8 encoding for subprocess to handle Unicode in model output
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env=env,
            )
            log = ''
            for line in proc.stdout:
                log += line
                with _jobs_lock:
                    _jobs[job_id]['log'] = log
            proc.wait()
            with _jobs_lock:
                if proc.returncode == 0:
                    _jobs[job_id]['status'] = 'done'
                else:
                    _jobs[job_id]['status'] = 'error'
                    _jobs[job_id]['error']  = f'Exit code {proc.returncode}'
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]['status'] = 'error'
                _jobs[job_id]['error']  = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({'job_id': job_id})


@app.route('/api/job_status')
def api_job_status():
    job_id = request.args.get('job_id', '')
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job not found'}), 404
    return jsonify(job)


# ─────────────────────────────────────────────────────────────────────────────
# API — list years available for a district (from output CSV)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/years')
def api_years():
    district = request.args.get('district', '').strip()
    if not district:
        return jsonify({'error': 'district param required'}), 400

    dist_safe = district.replace(' ', '_')
    csv_path  = os.path.join(OUTPUT_DIR, dist_safe,
                             f'LandslideRisk_YearWise_{dist_safe}.csv')
    if not os.path.exists(csv_path):
        return jsonify([])

    try:
        df = pd.read_csv(csv_path)
        years = sorted(df['year'].dropna().astype(int).unique().tolist())
        return jsonify(years)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# API — return JSON attributes for a district + year
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/risk_data')
def api_risk_data():
    district = request.args.get('district', '').strip()
    year     = request.args.get('year', '').strip()
    if not district or not year:
        return jsonify({'error': 'district and year required'}), 400

    dist_safe = district.replace(' ', '_')
    csv_path  = os.path.join(OUTPUT_DIR, dist_safe,
                             f'LandslideRisk_YearWise_{dist_safe}.csv')
    if not os.path.exists(csv_path):
        return jsonify({'error': f'No data found — run model first for {district}'}), 404

    try:
        df  = pd.read_csv(csv_path)
        row = df[df['year'].astype(int) == int(year)]
        if row.empty:
            return jsonify({'error': f'No data for year {year}'}), 404
        rec = row.iloc[0].where(pd.notnull(row.iloc[0]), None).to_dict()
        return jsonify(rec)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# API — render risk map PNG (calls visualise_risk.py)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/risk_map')
def api_risk_map():
    district = request.args.get('district', '').strip()
    year     = request.args.get('year', '').strip()
    if not district or not year:
        return jsonify({'error': 'district and year required'}), 400

    dist_safe = district.replace(' ', '_')
    shp_path  = os.path.join(OUTPUT_DIR, dist_safe,
                              f'LandslideRisk_YearWise_{dist_safe}.shp')
    if not os.path.exists(shp_path):
        return jsonify({'error': f'SHP not found — run model first for {district}'}), 404

    out_dir   = os.path.join(MAPS_DIR, dist_safe)
    os.makedirs(out_dir, exist_ok=True)
    out_png   = os.path.join(out_dir, f'risk_map_{dist_safe}_{year}.png')

    if not os.path.exists(out_png):
        cmd = [
            PYTHON_BIN, VISUALISE_SCRIPT,
            '--shp', shp_path,
            '--year', year,
            '--out_dir', out_dir,
            '--dpi', '130',
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                return jsonify({'error': result.stderr or result.stdout}), 500
        except subprocess.TimeoutExpired:
            return jsonify({'error': 'Visualisation timed out (>120s)'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        # visualise_risk.py names the file risk_map_<district>_<year>.png
        # inside out_dir — find it
        candidates = glob.glob(os.path.join(out_dir, f'*{year}*.png'))
        if not candidates:
            candidates = glob.glob(os.path.join(out_dir, '*.png'))
        if candidates:
            # Rename to our expected name
            os.rename(candidates[0], out_png)
        else:
            # Fall back: render with inline matplotlib
            try:
                gdf = gpd.read_file(shp_path)
                gdf.columns = [c.lower().strip() for c in gdf.columns]
                yr_col = 'year' if 'year' in gdf.columns else None
                if yr_col:
                    gdf_yr = gdf[gdf[yr_col].astype(int) == int(year)]
                else:
                    gdf_yr = gdf
                _render_risk_map(gdf_yr, district, year, out_png)
            except Exception as e:
                return jsonify({'error': str(e)}), 500

    return send_file(out_png, mimetype='image/png')


def _render_risk_map(gdf_yr, district, year, out_png):
    """Inline fallback renderer — used if visualise_risk.py produces no file."""
    fig, ax = plt.subplots(1, 1, figsize=(8, 7), facecolor='#0d1b2a')
    ax.set_facecolor('#1a2e45')

    rc_col = next((c for c in ['risk_class','riskclass','risk_clas'] if c in gdf_yr.columns), None)
    if rc_col and not gdf_yr.empty:
        gdf_yr = gdf_yr.dissolve(by=[rc_col], as_index=False)
        for _, row in gdf_yr.iterrows():
            rc   = str(row.get(rc_col, 'Low')).strip()
            fill = RISK_FILL.get(rc, '#888888')
            gpd.GeoDataFrame([row], geometry='geometry', crs=gdf_yr.crs).plot(
                ax=ax, color=fill, edgecolor='none', linewidth=0, zorder=2
            )
    else:
        if not gdf_yr.empty:
            gdf_yr.plot(ax=ax, color='#888888', edgecolor='none',
                        linewidth=0, zorder=2)

    ax.set_title(f'{district} — Risk Map  |  Year {year}',
                 fontsize=13, fontweight='bold', color='white', pad=10)
    ax.set_xlabel('Longitude', fontsize=9, color='#aaaaaa')
    ax.set_ylabel('Latitude',  fontsize=9, color='#aaaaaa')
    ax.tick_params(colors='#aaaaaa', labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor('#334455')

    patches = [mpatches.Patch(color=v, label=k) for k, v in RISK_FILL.items()]
    ax.legend(handles=patches, loc='lower right',
              facecolor='#1a2e45', edgecolor='#334455',
              labelcolor='white', fontsize=8)

    plt.tight_layout()
    plt.savefig(out_png, dpi=130, bbox_inches='tight', facecolor='#0d1b2a')
    plt.close()


# ─────────────────────────────────────────────────────────────────────────────
# API — full-district risk chart PNG (all years summary)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/risk_chart')
def api_risk_chart():
    district = request.args.get('district', '').strip()
    if not district:
        return jsonify({'error': 'district param required'}), 400

    dist_safe  = district.replace(' ', '_')
    csv_path   = os.path.join(OUTPUT_DIR, dist_safe,
                               f'LandslideRisk_YearWise_{dist_safe}.csv')
    if not os.path.exists(csv_path):
        return jsonify({'error': 'No data — run model first'}), 404

    cache_name = f'risk_chart_{dist_safe}.png'
    cache_path = os.path.join(MAPS_DIR, cache_name)

    try:
        df = pd.read_csv(csv_path).sort_values('year')
        fig, ax = plt.subplots(figsize=(14, 4), facecolor='#0d1b2a')
        ax.set_facecolor('#0d1b2a')

        for _, row in df.iterrows():
            ax.axvspan(row['year'] - 0.5, row['year'] + 0.5,
                       color=RISK_FILL.get(row.get('risk_class','Low'), '#888'),
                       alpha=0.35, zorder=1)

        ax.plot(df['year'], df['comp_risk'], color='white',
                lw=1.5, zorder=5, label='Composite Risk')

        if 'rf_mm' in df.columns:
            ax2 = ax.twinx()
            ax2.bar(df['year'], df['rf_mm'], color='#4a90d9',
                    alpha=0.25, label='Rainfall (mm)', zorder=2)
            ax2.set_ylabel('Rainfall (mm)', color='#4a90d9', fontsize=8)
            ax2.tick_params(axis='y', labelcolor='#4a90d9', labelsize=7)
            ax2.set_facecolor('#0d1b2a')
            if 'trig_rf' in df.columns:
                trig = df['trig_rf'].iloc[0]
                ax2.axhline(trig, color='#e74c3c', ls='--', lw=1,
                            label=f'Trigger: {trig:.0f} mm')

        ax.set_title(f'{district} — Year-Wise Risk Summary (1901–2023)',
                     fontsize=11, fontweight='bold', color='white')
        ax.set_ylabel('Composite Risk (0–1)', color='white', fontsize=8)
        ax.set_xlabel('Year', color='#aaaaaa', fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.tick_params(colors='#aaaaaa', labelsize=7)
        for spine in ax.spines.values():
            spine.set_edgecolor('#334455')

        patches = [mpatches.Patch(color=v, label=k, alpha=0.7)
                   for k, v in RISK_FILL.items()]
        ax.legend(handles=patches, loc='upper left',
                  facecolor='#1a2e45', edgecolor='#334455',
                  labelcolor='white', fontsize=7, title='Risk Class',
                  title_fontsize=7)
        plt.tight_layout()
        plt.savefig(cache_path, dpi=120, bbox_inches='tight', facecolor='#0d1b2a')
        plt.close()
    except Exception as e:
        plt.close('all')
        return jsonify({'error': str(e)}), 500

    return send_file(cache_path, mimetype='image/png')


# ─────────────────────────────────────────────────────────────────────────────
# API — susceptibility as GeoJSON (for Leaflet)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/susceptibility_geojson')
def api_susceptibility_geojson():
    """Return susceptibility shapefile as GeoJSON for the Leaflet frontend."""
    district = request.args.get('district', '').strip()
    if not district:
        return jsonify({'error': 'district param required'}), 400

    # Find the susceptibility SHP for this district
    pattern   = os.path.join(SHP_ROOT, '**', '*susceptibility.shp')
    shp_files = glob.glob(pattern, recursive=True)
    match = None
    for s in shp_files:
        folder    = os.path.basename(os.path.dirname(s))
        fname     = os.path.basename(s)
        candidate = (folder or fname.replace('_susceptibility.shp', '')
                     ).replace('_', ' ').title()
        if candidate.lower() == district.lower():
            match = s
            break

    if not match:
        return jsonify({'error': f'No susceptibility SHP found for: {district}'}), 404

    try:
        gdf = gpd.read_file(match)
        # Normalise column names
        gdf.columns = [c.lower().strip() for c in gdf.columns]
        # Reproject to WGS-84 for Leaflet
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        # Keep only essential columns to minimise payload
        keep = [c for c in ['class_name', 'classname', 'class', 'susc_class',
                              'suscept', 'label', 'name', 'geometry']
                if c in gdf.columns]
        gdf = gdf[keep]
        geojson_str = gdf.to_json()
        return Response(geojson_str, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# API — risk map as GeoJSON (for Leaflet)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/risk_geojson')
def api_risk_geojson():
    """Return year-wise risk shapefile as GeoJSON for the Leaflet frontend."""
    district = request.args.get('district', '').strip()
    year     = request.args.get('year', '').strip()
    if not district or not year:
        return jsonify({'error': 'district and year required'}), 400

    dist_safe = district.replace(' ', '_')
    shp_path  = os.path.join(OUTPUT_DIR, dist_safe,
                              f'LandslideRisk_YearWise_{dist_safe}.shp')
    if not os.path.exists(shp_path):
        return jsonify({'error': f'SHP not found — run model first for {district}'}), 404

    try:
        gdf = gpd.read_file(shp_path)
        gdf.columns = [c.lower().strip() for c in gdf.columns]

        # Filter to requested year
        yr_col = next((c for c in ['year', 'yr'] if c in gdf.columns), None)
        if yr_col:
            gdf = gdf[gdf[yr_col].astype(int) == int(year)]

        if gdf.empty:
            return jsonify({'error': f'No features for year {year}'}), 404

        # Reproject to WGS-84
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Keep only essential columns
        essential = ['risk_class', 'riskclass', 'risk_clas',
                     'rf_mm', 'wsi', 'comp_risk', 'trig_rf', 'year', 'geometry']
        keep = [c for c in essential if c in gdf.columns]
        gdf  = gdf[keep]

        geojson_str = gdf.to_json()
        return Response(geojson_str, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("  Sri Lanka Landslide Risk — Web App")
    print("  Open:  http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, port=5000, threaded=True)