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

import os, glob, json, subprocess, sys, threading, time
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['figure.max_open_warning'] = 50
matplotlib.rcParams['agg.path.chunksize'] = 1000
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory, Response
from flask_cors import CORS
from chatbot_flask_integration import setup_chatbot_routes
from functools import wraps
from time import time as get_time

# ══════════════════════════════════════════════════════════════════════════════
# ▶▶  CONFIGURE THESE PATHS FOR YOUR MACHINE  ◀◀
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHP_ROOT         = os.path.join(BASE_DIR, "DATA", "Susceptibility_Phase1_v1")
RAINFALL_CSV     = os.path.join(BASE_DIR, "Srilanka Rainfall Year wise", "Srilanka Rainfall year wise.csv")
LANDSLIDE_CSV    = os.path.join(BASE_DIR, "DATA", "landslides_Sri_Lanka.csv")
OUTPUT_DIR       = os.path.join(BASE_DIR, "Prediction Script", "output_shapefiles")
MODEL_SCRIPT     = os.path.join(BASE_DIR, "Prediction Script", "landslide_model_v2_filtered.py")
VISUALISE_SCRIPT = os.path.join(BASE_DIR, "Prediction Script", "visualise_risk.py")  
PYTHON_BIN       = sys.executable      # use current Python interpreter, including virtualenv
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
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-me-please')
CORS(app)
setup_chatbot_routes(app)

# In-memory job store  { job_id: { status, log, error } }
_jobs = {}
_jobs_lock = threading.Lock()
_model_running = False  # Global flag to prevent multiple model runs

# ─────────────────────────────────────────────────────────────────────────────
# Response Caching for Performance
# ─────────────────────────────────────────────────────────────────────────────
_response_cache = {}
_cache_timestamps = {}
CACHE_TTL = 300  # 5 minutes cache for API responses

def cache_response(ttl=CACHE_TTL):
    """Decorator to cache GET responses based on URL and params."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Build cache key from URL and query parameters
            cache_key = f"{request.path}?{request.query_string.decode()}"
            current_time = get_time()
            
            # Check if cached and not expired
            if cache_key in _response_cache:
                if current_time - _cache_timestamps[cache_key] < ttl:
                    return _response_cache[cache_key]
                else:
                    # Cache expired, remove it
                    del _response_cache[cache_key]
                    del _cache_timestamps[cache_key]
            
            # Call original function and cache result
            result = f(*args, **kwargs)
            _response_cache[cache_key] = result
            _cache_timestamps[cache_key] = current_time
            return result
        return decorated_function
    return decorator

# ─────────────────────────────────────────────────────────────────────────────
# Startup checks
# ─────────────────────────────────────────────────────────────────────────────
def _check_required_files():
    """Verify all input files exist at startup."""
    issues = []
    for name, path in [
        ('SHP_ROOT', SHP_ROOT),
        ('RAINFALL_CSV', RAINFALL_CSV),
        ('LANDSLIDE_CSV', LANDSLIDE_CSV),
        ('OUTPUT_DIR', OUTPUT_DIR),
        ('MODEL_SCRIPT', MODEL_SCRIPT),
    ]:
        if not os.path.exists(path):
            issues.append(f"✗ {name}: {path}")
    if issues:
        print("⚠ MISSING FILES:")
        for issue in issues:
            print(f"  {issue}")
        return False
    print("[OK] All required files exist")
    return True

_STARTUP_OK = _check_required_files()

# ─────────────────────────────────────────────────────────────────────────────
# Static file helpers
# ─────────────────────────────────────────────────────────────────────────────
MAPS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'maps')
os.makedirs(MAPS_DIR, exist_ok=True)


def _normalize_district_name(name):
    return name.replace('_', ' ').strip().lower()


def _discover_districts():
    districts = {}
    if os.path.isdir(SHP_ROOT):
        pattern = os.path.join(SHP_ROOT, '**', '*susceptibility.shp')
        for path in glob.glob(pattern, recursive=True):
            folder = os.path.basename(os.path.dirname(path))
            fname = os.path.basename(path)
            display = (folder or fname.replace('_susceptibility.shp', '')).replace('_', ' ').strip().title()
            key = _normalize_district_name(display)
            districts[key] = {'display': display, 'susc_shp': path}
    return districts


_district_map = _discover_districts()


def _list_districts():
    districts = {info['display'] for info in _district_map.values()}
    if os.path.isdir(OUTPUT_DIR):
        for d in os.listdir(OUTPUT_DIR):
            full = os.path.join(OUTPUT_DIR, d)
            if os.path.isdir(full) and glob.glob(os.path.join(full, '*.shp')):
                districts.add(d.replace('_', ' ').strip().title())
    return sorted(districts)


def _get_district_info(district):
    return _district_map.get(_normalize_district_name(district))


# in-memory GeoDataFrame cache for faster repeated render requests (limited to 10 entries)
_gdf_cache = {}
_gdf_cache_order = []

def _load_gdf(path):
    if path in _gdf_cache:
        return _gdf_cache[path]
    gdf = gpd.read_file(path)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    
    # Limit cache size
    if len(_gdf_cache) >= 10:
        oldest = _gdf_cache_order.pop(0)
        del _gdf_cache[oldest]
    _gdf_cache[path] = gdf
    _gdf_cache_order.append(path)
    
    return gdf


def _choose_column(gdf, candidates):
    cols = {c.lower(): c for c in gdf.columns}
    for name in candidates:
        if name.lower() in cols:
            return cols[name.lower()]
    return None


def _normalize_risk_class(raw):
    if not isinstance(raw, str):
        return 'Low'
    r = raw.strip().lower()
    if 'very' in r and 'high' in r:
        return 'Very High'
    if 'high' in r:
        return 'High'
    if 'moderate' in r:
        return 'Moderate'
    return 'Low'


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
# API — list districts
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/districts')
@cache_response(ttl=3600)  # Cache for 1 hour - districts don't change often
def api_districts():
    """Return cached district list for faster API responses."""
    try:
        return jsonify(_list_districts())
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
        info = _get_district_info(district)
        if not info or 'susc_shp' not in info:
            return jsonify({'error': f'No susceptibility SHP found for: {district}'}), 404
        match = info['susc_shp']

        try:
            gdf = gpd.read_file(match)
            gdf.columns = [c.lower().strip() for c in gdf.columns]
            name_col = next((c for c in ['class_name','classname','class',
                                          'susc_class','suscept','label','name']
                              if c in gdf.columns), None)
            fig, ax = plt.subplots(1, 1, figsize=(7, 6), facecolor='#0d1b2a')
            ax.set_facecolor('#1a2e45')

            if name_col:
                gdf['_cls'] = gdf[name_col].astype(str).str.strip().str.lower()
                try:
                    dissolved = gdf.dissolve(by='_cls', as_index=False)
                except Exception:
                    dissolved = gdf
                for cls, fill in SUSC_FILL.items():
                    sub = dissolved[dissolved['_cls'] == cls]
                    if not sub.empty:
                        sub.plot(ax=ax, color=fill, edgecolor='none',
                                 linewidth=0, label=cls.title(), zorder=2, rasterized=True)
            else:
                gdf.plot(ax=ax, color='#4a90d9', edgecolor='none',
                         linewidth=0, zorder=2, rasterized=True)

            ax.set_title(f'{district} — Landslide Susceptibility',
                         fontsize=11, fontweight='bold', color='white', pad=8)
            ax.set_xlabel('Longitude', fontsize=8, color='#aaaaaa')
            ax.set_ylabel('Latitude',  fontsize=8, color='#aaaaaa')
            ax.tick_params(colors='#aaaaaa', labelsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor('#334455')
                spine.set_linewidth(0.5)

            patches = [mpatches.Patch(color=v, label=k.title())
                       for k, v in SUSC_FILL.items()]
            ax.legend(handles=patches, loc='lower right',
                      facecolor='#1a2e45', edgecolor='#334455',
                      labelcolor='white', fontsize=7)

            plt.tight_layout()
            plt.savefig(cache_path, dpi=60, bbox_inches='tight',
                        facecolor='#0d1b2a')
            plt.close()
        except Exception as e:
            plt.close('all')
            return jsonify({'error': str(e)}), 500

    return send_file(cache_path, mimetype='image/png')


# ─────────────────────────────────────────────────────────────────────────────
# API — run the prediction model (async job)
# ─────────────────────────────────────────────────────────────────────────────
def _output_exists_for_district(district):
    dist_safe = district.replace(' ', '_')
    shp_path  = os.path.join(OUTPUT_DIR, dist_safe,
                              f'LandslideRisk_YearWise_{dist_safe}.shp')
    csv_path  = os.path.join(OUTPUT_DIR, dist_safe,
                              f'LandslideRisk_YearWise_{dist_safe}.csv')
    return os.path.exists(shp_path) and os.path.exists(csv_path)


@app.route('/api/run_model', methods=['POST'])
def api_run_model():
    # Check if required files exist
    if not os.path.exists(RAINFALL_CSV):
        return jsonify({'error': f'Rainfall CSV not found: {RAINFALL_CSV}'}), 500
    if not os.path.exists(LANDSLIDE_CSV):
        return jsonify({'error': f'Landslide CSV not found: {LANDSLIDE_CSV}'}), 500
    
    data = request.get_json(force=True)
    districts = data.get('districts', [])
    year_start = data.get('year_start', None)
    year_end   = data.get('year_end',   None)

    if not districts:
        return jsonify({'error': 'districts list required'}), 400

    # Debug logging
    print(f"[DEBUG] Requested districts: {districts}")
    
    # ✓ CHECK CACHE FIRST — if output exists, return immediately
    all_exist = all(_output_exists_for_district(d) for d in districts)
    print(f"[DEBUG] All outputs exist: {all_exist}")
    
    if all_exist:
        job_id = str(int(time.time() * 1000))
        with _jobs_lock:
            _jobs[job_id] = {
                'status': 'done',
                'log': '[FAST] Results already computed — loading from cache!',
                'error': None,
            }
        print(f"[DEBUG] Returning cached result for job {job_id}")
        return jsonify({'job_id': job_id})

    global _model_running
    with _jobs_lock:
        if _model_running:
            return jsonify({'error': 'Model is already running. Please wait for the current job to complete.'}), 409
        _model_running = True

    print(f"[DEBUG] Starting model computation for districts: {districts}")
    job_id = str(int(time.time() * 1000))
    with _jobs_lock:
        _jobs[job_id] = {'status': 'running', 'log': 'Initializing model...\n', 'error': None}

    def run():
        global _model_running
        cmd = [
            PYTHON_BIN, '-u', MODEL_SCRIPT,
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
            with _jobs_lock:
                _jobs[job_id]['log'] += f"✓ Command: {' '.join(cmd[:6])}...\n"
            
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, bufsize=1,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'},
            )
            
            # Simple polling approach for subprocess output
            import time
            start_time = time.time()
            log = ''
            
            while proc.poll() is None:  # While process is still running
                # Read available output
                if proc.stdout:
                    line = proc.stdout.readline()
                    if line:
                        log += line
                        with _jobs_lock:
                            _jobs[job_id]['log'] = log
                
                # Check for timeout (30 minutes)
                if time.time() - start_time > 1800:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    with _jobs_lock:
                        _jobs[job_id]['status'] = 'error'
                        _jobs[job_id]['error'] = 'Model timed out after 30 minutes'
                    return
                
                time.sleep(0.1)  # Small delay to avoid busy waiting
            
            # Process finished - get any remaining output
            remaining_stdout, remaining_stderr = proc.communicate()
            if remaining_stdout:
                log += remaining_stdout
            if remaining_stderr:
                log += f"[STDERR] {remaining_stderr}"
            
            with _jobs_lock:
                _jobs[job_id]['log'] = log
            
            # Check return code
            if proc.returncode != 0:
                with _jobs_lock:
                    _jobs[job_id]['status'] = 'error'
                    _jobs[job_id]['error'] = f'Model failed (exit {proc.returncode}). Error: {remaining_stderr[:500]}'
                return
            
            with _jobs_lock:
                _jobs[job_id]['status'] = 'done'
                _jobs[job_id]['log'] += '\n✓ MODEL COMPLETED!'
                # Pre-render risk maps for all processed districts
                _pre_render_risk_maps(districts, year_start, year_end)
                
        except subprocess.TimeoutExpired:
            proc.kill()
            with _jobs_lock:
                _jobs[job_id]['status'] = 'error'
                _jobs[job_id]['error'] = 'Model took too long (>10 min) — killed'
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]['status'] = 'error'
                _jobs[job_id]['error'] = str(e)[:200]
        finally:
            global _model_running
            _model_running = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({'job_id': job_id})


@app.route('/api/model_status')
def api_model_status():
    """Check if the model is currently running."""
    global _model_running
    return jsonify({'model_running': _model_running})


@app.route('/api/job_status')
def api_job_status():
    job_id = request.args.get('job_id', '')
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({'error': 'job not found'}), 404
    
    # Return last 1000 chars of log to avoid huge responses
    safe_job = job.copy()
    if len(safe_job.get('log', '')) > 2000:
        safe_job['log'] = '...' + safe_job['log'][-1500:]
    return jsonify(safe_job)


# ─────────────────────────────────────────────────────────────────────────────
# API — list years available for a district (from output CSV)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/years')
@cache_response(ttl=300)  # Cache for 5 minutes
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
@cache_response(ttl=300)  # Cache for 5 minutes
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
# API — render risk map PNG
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

    out_dir = os.path.join(MAPS_DIR, dist_safe)
    os.makedirs(out_dir, exist_ok=True)
    out_png = os.path.join(out_dir, f'risk_map_{dist_safe}_{year}.png')

    if not os.path.exists(out_png):
        try:
            gdf = _load_gdf(shp_path)
            yr_col = _choose_column(gdf, ['year', 'yr'])
            if yr_col:
                gdf_yr = gdf[gdf[yr_col].astype(int) == int(year)].copy()
            else:
                gdf_yr = gdf.copy()

            if gdf_yr.empty:
                return jsonify({'error': f'No data for year {year}'}), 404

            _render_risk_map(gdf_yr, district, year, out_png)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return send_file(out_png, mimetype='image/png')


def _render_risk_map(gdf_yr, district, year, out_png):
    """Render a year-specific risk map directly in the Flask process."""
    # Simplify geometries to reduce rendering time
    gdf_yr = gdf_yr.copy()
    gdf_yr['geometry'] = gdf_yr['geometry'].simplify(tolerance=0.001, preserve_topology=True)
    
    fig, ax = plt.subplots(1, 1, figsize=(7, 6), facecolor='#0d1b2a')
    ax.set_facecolor('#1a2e45')

    rc_col = next((c for c in ['risk_class', 'riskclass', 'risk_clas'] if c in gdf_yr.columns), None)
    if rc_col is None:
        rc_col = _choose_column(gdf_yr, ['risk'])
    if rc_col and not gdf_yr.empty:
        gdf_yr['_risk_class'] = gdf_yr[rc_col].apply(_normalize_risk_class)
        try:
            gdf_plot = gdf_yr.dissolve(by=['_risk_class'], as_index=False)
        except Exception:
            gdf_plot = gdf_yr.copy()
        for rc in ['Low', 'Moderate', 'High', 'Very High']:
            sub = gdf_plot[gdf_plot['_risk_class'] == rc]
            if sub.empty:
                continue
            sub.plot(ax=ax, color=RISK_FILL[rc], edgecolor='none', linewidth=0, zorder=2, rasterized=True)
    elif not gdf_yr.empty:
        gdf_yr.plot(ax=ax, color='#888888', edgecolor='none', linewidth=0, zorder=2, rasterized=True)

    ax.set_title(f'{district} — Risk Map  |  {year}',
                 fontsize=11, fontweight='bold', color='white', pad=8)
    ax.set_xlabel('Longitude', fontsize=8, color='#aaaaaa')
    ax.set_ylabel('Latitude',  fontsize=8, color='#aaaaaa')
    ax.tick_params(colors='#aaaaaa', labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor('#334455')
        spine.set_linewidth(0.5)

    patches = [mpatches.Patch(color=v, label=k) for k, v in RISK_FILL.items()]
    ax.legend(handles=patches, loc='lower right',
              facecolor='#1a2e45', edgecolor='#334455',
              labelcolor='white', fontsize=7, framealpha=0.9)

    plt.tight_layout()
    fig.savefig(out_png, dpi=60, bbox_inches='tight', facecolor='#0d1b2a')
    plt.close(fig)


def _pre_render_risk_maps(districts, year_start, year_end):
    """Pre-render risk maps for all districts and years after model completion."""
    import concurrent.futures
    
    def render_district(district):
        dist_safe = district.replace(' ', '_')
        shp_path = os.path.join(OUTPUT_DIR, dist_safe, f'LandslideRisk_YearWise_{dist_safe}.shp')
        if not os.path.exists(shp_path):
            return
        
        try:
            gdf = _load_gdf(shp_path)
            years = sorted(gdf['year'].dropna().astype(int).unique().tolist())
            if year_start:
                years = [y for y in years if y >= int(year_start)]
            if year_end:
                years = [y for y in years if y <= int(year_end)]
            
            for year in years:
                out_dir = os.path.join(MAPS_DIR, dist_safe)
                os.makedirs(out_dir, exist_ok=True)
                out_png = os.path.join(out_dir, f'risk_map_{dist_safe}_{year}.png')
                if not os.path.exists(out_png):
                    yr_col = _choose_column(gdf, ['year', 'yr'])
                    if yr_col:
                        gdf_yr = gdf[gdf[yr_col].astype(int) == int(year)].copy()
                    else:
                        gdf_yr = gdf.copy()
                    
                    if not gdf_yr.empty:
                        _render_risk_map(gdf_yr, district, str(year), out_png)
        except Exception as e:
            print(f"Error pre-rendering maps for {district}: {e}")
    
    # Use thread pool to render multiple districts in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        executor.map(render_district, districts)


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
        fig, ax = plt.subplots(figsize=(12, 3.5), facecolor='#0d1b2a')
        ax.set_facecolor('#0d1b2a')

        for _, row in df.iterrows():
            ax.axvspan(row['year'] - 0.5, row['year'] + 0.5,
                       color=RISK_FILL.get(row.get('risk_class','Low'), '#888'),
                       alpha=0.35, zorder=1)

        ax.plot(df['year'], df['comp_risk'], color='white',
                lw=1.2, zorder=5, label='Composite Risk')

        if 'rf_mm' in df.columns:
            ax2 = ax.twinx()
            ax2.bar(df['year'], df['rf_mm'], color='#4a90d9',
                    alpha=0.25, label='Rainfall (mm)', zorder=2)
            ax2.set_ylabel('Rainfall (mm)', color='#4a90d9', fontsize=7)
            ax2.tick_params(axis='y', labelcolor='#4a90d9', labelsize=6)
            ax2.set_facecolor('#0d1b2a')
            if 'trig_rf' in df.columns:
                trig = df['trig_rf'].iloc[0]
                ax2.axhline(trig, color='#e74c3c', ls='--', lw=0.8,
                            label=f'Trigger: {trig:.0f} mm')

        ax.set_title(f'{district} \u2014 Year-Wise Risk',
                     fontsize=10, fontweight='bold', color='white')
        ax.set_ylabel('Risk (0\u20131)', color='white', fontsize=7)
        ax.set_xlabel('Year', color='#aaaaaa', fontsize=7)
        ax.set_ylim(0, 1.05)
        ax.tick_params(colors='#aaaaaa', labelsize=6)
        for spine in ax.spines.values():
            spine.set_edgecolor('#334455')
            spine.set_linewidth(0.5)

        patches = [mpatches.Patch(color=v, label=k, alpha=0.7)
                   for k, v in RISK_FILL.items()]
        ax.legend(handles=patches, loc='upper left',
                  facecolor='#1a2e45', edgecolor='#334455',
                  labelcolor='white', fontsize=6, title='Risk Class',
                  title_fontsize=6, framealpha=0.9)
        plt.tight_layout()
        plt.savefig(cache_path, dpi=80, bbox_inches='tight', facecolor='#0d1b2a')
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

    info = _get_district_info(district)
    if not info or 'susc_shp' not in info:
        return jsonify({'error': f'No susceptibility SHP found for: {district}'}), 404
    match = info['susc_shp']

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
    # Disable debug mode and auto-reloader for faster startup
    app.run(debug=False, port=5000, threaded=True, use_reloader=False)