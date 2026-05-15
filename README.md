# Sri Lanka Landslide Prediction

![Star Constellation](star_constellation.png)

## Project Summary

Sri Lanka Landslide Prediction is a geographic information system (GIS) and machine learning-driven toolkit for assessing landslide susceptibility across Sri Lanka.

It includes:
- spatial preprocessing of elevation, hydrology, land cover, and geology
- district-level hazard and susceptibility mapping
- risk visualizations and chart generation
- a local Flask web app with chatbot-based risk exploration
- support for local and cloud large language models (LLMs)

This repository is intended as both a research-ready analysis pipeline and a demo-ready web application.

## Why this project exists

Landslides pose a serious threat in Sri Lanka, especially during monsoon seasons and in steep terrain. This project brings together GIS data, automated vulnerability analysis, and an interactive UI so users can:
- compare district-level risk
- inspect model outputs visually
- query the system using natural language
- extend the pipeline for new data, districts, or models

## What is included

- `Scripts/` — main project pipeline for preprocessing, susceptibility modeling, and visualization
- `APP/landslide_app/` — Flask web application and chatbot integration
- `Data/` — raw GIS and raster input datasets
- `Data_Preprocessed/` — cleaned and derived spatial outputs
- `Output/` — generated maps, charts, and result files
- `requirements.txt` — baseline dependencies
- `requirements_enhanced.txt` — extended dependencies for AI/chatbot and optimization features
- documentation with setup, API usage, and enhancement notes

## Architecture

1. Data ingestion
2. Preprocessing and feature creation
3. Susceptibility and risk analysis
4. Map and chart generation
5. Web app visualization and chatbot interaction

## Repository layout

- `APP/landslide_app/`
  - `app.py` — Flask application entry point
  - chatbot routes and API integration
  - static map assets and templates
- `Scripts/`
  - `preprocessing.py` — raw data processing
  - `phase1_susceptibility.py` — hazard analysis
  - `visualization_seperate.py` — generate individual maps
  - `visualization_merged.py` — combine visual outputs
- `Data/` — original GIS sources and raster layers
- `Data_Preprocessed/` — generated outputs used by analysis scripts
- `Output/` — final visual maps and reports

## Full Setup Guide

### 1) Clone repository

```bash
git clone https://github.com/Himanshu-Kushwaha0/Srilanka_Landslide_Prediction.git
cd Srilanka_Landslide_Prediction
```

### 2) Create a Python virtual environment

#### Windows (PowerShell)
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

#### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### 3) Install dependencies

For the base project:
```bash
python -m pip install -r requirements.txt
```

For the full AI-enabled project:
```bash
python -m pip install -r requirements_enhanced.txt
```

> Use `requirements_enhanced.txt` if you want Ollama, Hugging Face, or OpenAI chatbot support.

## Running the project

### 4) Preprocess data and build outputs

```bash
cd Scripts
python preprocessing.py
python phase1_susceptibility.py
python visualization_seperate.py
python visualization_merged.py
```

These scripts should be executed in order to ensure the full data workflow completes.

### 5) Start the web application

```bash
cd APP/landslide_app
python app.py
```

Open:

```text
http://localhost:5000
```

## Chatbot and Ollama instructions

This project supports a natural-language chatbot on the web app.

### Option 1: Mock chatbot mode (default)

No extra model setup is needed. It works for local testing and interface validation.

### Option 2: Local Ollama LLM

1. Install Ollama from https://ollama.ai
2. Start the Ollama service
3. Pull a model:

```bash
ollama pull mistral-7b
```

4. Serve the model if not already running:

```bash
ollama serve
```

5. Configure the web app to use Ollama

Update the chatbot configuration in `APP/landslide_app/app.py` or `chatbot_integration` settings to use:
- provider: `ollama`
- model: `mistral-7b`
- URL: `http://localhost:11434`

Example:

```python
configure_chatbot({
    'provider': 'ollama',
    'ollama_url': 'http://localhost:11434',
    'ollama_model': 'mistral-7b'
})
```

### Option 3: Hugging Face

1. Create a Hugging Face account
2. Generate an API token
3. Set environment variable:

```bash
export HF_API_KEY='your_token_here'
```

4. Use a Hugging Face model like:

```python
configure_chatbot({
    'provider': 'huggingface',
    'hf_model': 'mistralai/Mistral-7B-Instruct-v0.1'
})
```

### Option 4: OpenAI

1. Set your OpenAI key:

```bash
export OPENAI_API_KEY='sk_your_key_here'
```

2. Configure the app to use OpenAI provider.

## What users can do with this project

- run data preprocessing and GIS modeling locally
- generate district-based landslide susceptibility maps
- visualize risk outputs and charts
- use a chatbot to ask questions about results
- extend the app with new datasets, districts, or risk factors

## Important details

- The project is designed for local analysis and demonstration.
- GIS data volumes may be large; keep raw datasets outside Git if possible.
- If scripts fail due to missing inputs, update paths in `Scripts/paths_config.py`.
- The web app displays results from the processed `Data_Preprocessed/` and `Output/` folders.

## Documentation index

- `SETUP_AND_DEPLOYMENT_GUIDE.md` — complete installation and deployment steps
- `QUICKSTART.md` — rapid onboarding
- `API_DOCUMENTATION.md` — web API and chatbot endpoints
- `CHATBOT_INTEGRATION_GUIDE.md` — chatbot provider configuration
- `MANIFEST_AND_CHECKLIST.md` — project contents and tracking
- `OPTIMIZATION_PLAN.md` — performance improvements and design notes

## Troubleshooting

- Activate `.venv` before running scripts
- Install missing dependencies with `pip install -r requirements_enhanced.txt`
- Confirm Ollama is running for local chatbot mode
- Verify that required GIS files exist in `Data/` or `Data_Preprocessed/`

## Contribution

Contributions, bug fixes, and enhancements are welcome. Suggested improvements:
- add new district or hazard features
- add more interactive visual dashboards
- improve AI chatbot responses
- add deployment scripts for Docker or cloud

---

This repository is a complete landslide risk exploration toolkit for Sri Lanka, blending GIS analysis, predictive workflows, and AI-assisted interpretation.
