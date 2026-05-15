from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS_DIR = _HERE.parent


def _pick_root() -> Path:
    candidates = []
    for root in (_SCRIPTS_DIR.parents[1], _SCRIPTS_DIR.parents[2]):
        score = 0
        if (root / "Data").is_dir():
            score += 1
        if (root / "Preprocess_Data").is_dir():
            score += 1
        if (root / "output").is_dir():
            score += 1
        candidates.append((score, root))
    candidates.sort(key=lambda x: (x[0], len(str(x[1]))), reverse=True)
    best_score, best_root = candidates[0]
    return best_root


ROOT = _pick_root()

ROOT = ROOT / "Srilanka_Landslide_Prediction"

print(f"Root directory: {ROOT}")

LULC_SHP = str(ROOT / "Data" / "LULC" / "Landuse_Srilanka_GCS.shp")
VILLAGE_SHP = str(ROOT / "Data" / "Boundry" / "Village_Sri Lanka.shp")
DEM_PATH = str(ROOT / "Data" / "Sri_Lanka_SRTM_30m.tif")
FAULT_SHP = str(ROOT / "Data" / "Fault" / "Falut_Line_Sri_Lanka.shp")
RIVER_SHP = str(ROOT / "Data" / "River-Road" / "River_Line.shp")

TOPO_BASE = str(ROOT / "Preprocess_Data" / "Topo_Output")
HYDRO_BASE = str(ROOT / "Preprocess_Data" / "Hydro_Output")
SOIL_BASE = str(ROOT / "Preprocess_Data" / "Soil_Output")
VECTOR_BASE = str(ROOT / "Preprocess_Data" / "Vector_Output")

SUSCEPTIBILITY_PHASE1_OUTPUT_BASE = str(ROOT / "Data" / "Susceptibility_Phase1")

SOIL_CLAY_TIF = str(ROOT / "Data" / "soil" / "clay.tif")
SOIL_SAND_TIF = str(ROOT / "Data" / "soil" / "sand.tif")
SOIL_SILT_TIF = str(ROOT / "Data" / "soil" / "silt.tif")