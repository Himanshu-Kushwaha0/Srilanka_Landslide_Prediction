# Sri Lanka Landslide Risk — Web Application

## Project Structure

```
landslide_app/
├── app.py                  ← Flask backend (edit the 7 path variables at top)
├── requirements.txt
├── templates/
│   └── index.html          ← Full UI (served by Flask)
└── static/
    └── maps/               ← Auto-created: cached PNG maps
```

## Setup

### 1. Install dependencies
```bash
pip install flask flask-cors pandas geopandas matplotlib shapely
```

### 2. Configure paths in app.py
Open `app.py` and edit the 7 constants near the top:

```python
SHP_ROOT         = "/home/user/Documents/SriLanka/Bisag_Srilanka_Landslide_Prediction/Output/Susceptibility_Phase1_v1"
RAINFALL_CSV     = "/home/user/Documents/SriLanka/APP/Srilanka Rainfall Year wise/Srilanka Rainfall Year wise.csv"
LANDSLIDE_CSV    = "/home/user/Documents/SriLanka/Prediction Script/output_shapefiles/landslides_Sri_Lanka.csv"
OUTPUT_DIR       = "/home/user/Documents/SriLanka/Prediction Script/output_shapefiles"
MODEL_SCRIPT     = "/home/user/Documents/SriLanka/Prediction Script/landslide_model_v2_filtered.py"
VISUALISE_SCRIPT = "/home/user/Documents/SriLanka/Prediction Script/visualise_risk.py"
PYTHON_BIN       = "python3"
```

Based on your screenshots the actual paths are:
- SHP_ROOT     → `/home/user/Documents/SriLanka/Bisag_Srilanka_Landslide_Prediction/Output/Susceptibility_Phase1_v1`
- RAINFALL_CSV → `/home/user/Documents/SriLanka/APP/Srilanka Rainfall Year wise/Srilanka Rainfall Year wise.csv`
- LANDSLIDE_CSV→ `/home/user/Documents/SriLanka/Prediction Script/output_shapefiles/landslides_Sri_Lanka.csv`
- OUTPUT_DIR   → `/home/user/Documents/SriLanka/Prediction Script/output_shapefiles`
- MODEL_SCRIPT → `/home/user/Documents/SriLanka/Prediction Script/landslide_model_v3_yearwise.py`
  ⚠ Your file is named `landslide_model_v2_filtered.py` — update this path!
- VISUALISE_SCRIPT → `/home/user/Documents/SriLanka/Prediction Script/visualise_risk.py`

### 3. Run
```bash
cd landslide_app
python app.py
```
Then open: http://localhost:5000

## How to Use

### Static Tab
1. Select a district from the dropdown
2. Click "Load Susceptibility Map"
3. The map shows terrain susceptibility classes (Very Low → High)

### Dynamic Tab / Split View
1. Select a district
2. Set year range (default 1901–2023)
3. Click "Run Model for District" — this runs `landslide_model_v3_yearwise.py`
4. Wait for "Model complete ✓" (takes 30–120 seconds depending on year range)
5. Year chips appear in the sidebar — coloured by risk class
6. Click any year chip or select from the Year dropdown
7. Risk map PNG loads (rendered by `visualise_risk.py`)
8. Risk card shows: composite score, rainfall, WSI, trigger threshold

### Split View
Shows susceptibility (left) and risk map (right) side by side for the same district.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/districts` | GET | List all available districts |
| `/api/susceptibility?district=Kandy` | GET | Susceptibility map PNG |
| `/api/run_model` | POST | Start async model run |
| `/api/job_status?job_id=xxx` | GET | Poll job progress + logs |
| `/api/years?district=Kandy` | GET | List output years for district |
| `/api/risk_data?district=Kandy&year=2010` | GET | Risk attributes JSON |
| `/api/risk_map?district=Kandy&year=2010` | GET | Risk map PNG |
| `/api/risk_chart?district=Kandy` | GET | Year-wise summary chart PNG |

## Troubleshooting

**"No susceptibility SHP found for: Kandy"**
→ Check SHP_ROOT path. Each district must have a subfolder with `*susceptibility.shp` inside.

**Model run shows error immediately**
→ Check MODEL_SCRIPT path and PYTHON_BIN. Run `python3 --version` to confirm.

**Risk map not rendering**
→ Check VISUALISE_SCRIPT path. The app falls back to an inline renderer if the script fails.

**Colour chips not appearing**
→ Run the model first. Chips are coloured by reading the output CSV.
