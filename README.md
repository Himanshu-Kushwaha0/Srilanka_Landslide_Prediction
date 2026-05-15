# Sri Lanka Landslide Prediction

## Setup (Windows / Ubuntu / macOS)

### 1) Create a virtual environment

#### Windows (PowerShell)
```bash
cd path\to\Srilanka_Landslide_Prediction
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

#### Ubuntu/Linux (bash)
```bash
cd /path/to/Srilanka_Landslide_Prediction
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

#### macOS (zsh/bash)
```bash
cd /path/to/Srilanka_Landslide_Prediction
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2) Install dependencies

```bash
python -m pip install -r requirements.txt
```

## Run (in order)

Run all scripts from the `Scripts` directory so relative path resolution is consistent.

### Windows (PowerShell) / Ubuntu/Linux (bash) / macOS (zsh/bash)
```bash
cd .\Scripts
python preprocessing.py
python phase1_susceptibility.py
python visualization_seperate.py
python visualization_merged.py
```

## Notes

- The scripts will prompt for district selection (e.g., `all`, `list`, or comma-separated district names).
- Runtime feedback is shown only via progress bars.