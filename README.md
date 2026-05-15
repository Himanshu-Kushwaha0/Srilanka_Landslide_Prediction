# Sri Lanka Landslide Prediction

![Project Logo](APP/landslide_app/static/bisag_logo.png)

## Overview

Sri Lanka Landslide Prediction is a GIS-powered risk analysis system built to evaluate landslide susceptibility, generate risk maps, and deliver an interactive web-based chatbot for natural-language exploration.

This repository combines:
- spatial data preprocessing and hazard modeling
- raster/vector analysis for district-level susceptibility
- visualization scripts and map generation
- a Flask-based web app with chatbot support
- optimization and documentation for fast local setup

## Key Features

- Landslide susceptibility modeling for Sri Lanka
- Automated preprocessing of topography, hydrology, and land cover
- District-level risk mapping and chart generation
- Interactive web dashboard with land‑slide chatbot assistance
- Support for local and cloud LLM providers
- Strong documentation and optimized project structure

## Repository Structure

- `APP/landslide_app/` — Flask app, static assets, and chatbot integration
- `Data/` — raw geographic input data and GIS layers
- `Data_Preprocessed/` — derived spatial outputs and intermediate files
- `Output/` — generated maps, charts, and prediction outputs
- `Scripts/` — main processing scripts for preprocessing, susceptibility, and visualization
- `requirements.txt` — core Python dependencies
- `requirements_enhanced.txt` — enhanced dependency set for optimized and chatbot-enabled installs
- Documentation files: `SETUP_AND_DEPLOYMENT_GUIDE.md`, `QUICKSTART.md`, `API_DOCUMENTATION.md`, and more

## Quick Start

### 1) Clone the repository

```bash
git clone https://github.com/Himanshu-Kushwaha0/Srilanka_Landslide_Prediction.git
cd Srilanka_Landslide_Prediction
```

### 2) Create and activate a Python virtual environment

#### Windows (PowerShell)
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

#### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 3) Install dependencies

For the base install:
```bash
python -m pip install -r requirements.txt
```

For the enhanced setup with chatbot and optimizations:
```bash
python -m pip install -r requirements_enhanced.txt
```

## Run the Project

### Preprocessing and Analysis

Use the scripts in `Scripts/` to prepare data and generate outputs.

```bash
cd Scripts
python preprocessing.py
python phase1_susceptibility.py
python visualization_seperate.py
python visualization_merged.py
```

> Run these scripts in this order to ensure the project data pipeline completes successfully.

### Start the Web App

```bash
cd APP/landslide_app
python app.py
```

Open your browser at:

```text
http://localhost:5000
```

## Chatbot Support

The web application includes a chatbot interface for asking questions like:
- "What is landslide risk for Kandy?"
- "How was this susceptibility map generated?"
- "Which districts are most vulnerable?"

### Supported providers
- Mock response mode (default)
- Ollama (local LLM)
- Hugging Face
- OpenAI

See `CHATBOT_INTEGRATION_GUIDE.md` for setup details.

## Recommended Workflow

1. Prepare your environment and install dependencies.
2. Run preprocessing and susceptibility scripts.
3. Generate visualizations.
4. Launch the app and review maps in the browser.
5. Use the chatbot for interactive insights.

## Important Notes

- This repository is designed for local evaluation and visualization.
- Large GIS or raster datasets may increase runtime and storage needs.
- If you have missing data, review `Scripts/paths_config.py` to update dataset paths.

## Additional Documentation

- `SETUP_AND_DEPLOYMENT_GUIDE.md` — full setup instructions
- `QUICKSTART.md` — fast project onboarding
- `API_DOCUMENTATION.md` — API endpoints and usage
- `MANIFEST_AND_CHECKLIST.md` — project manifest and tracking
- `OPTIMIZATION_PLAN.md` — performance improvements and strategy

## Troubleshooting

- If the app fails to start, confirm the virtual environment is active.
- Ensure required packages are installed from `requirements.txt` or `requirements_enhanced.txt`.
- For GIS errors, verify source files are present in `Data/` and `Data_Preprocessed/`.

## Contribution

Contributions are welcome. If you want to extend the project, add new district analysis, improve chatbot responses, or enhance visualizations, please create a branch and submit a pull request.

---

Made for Sri Lanka landslide risk exploration with GIS modeling, predictive mapping, and interactive explanation.
