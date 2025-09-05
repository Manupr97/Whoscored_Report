# WhoScored – Pipeline de datos y visualizaciones

## Estructura
- `src/whoscored_viz/`: código fuente (preparación de datos y visualizaciones).
- `notebooks/`: notebooks de pruebas.
- `data/MatchCenter/`: **no versionado** (datos brutos por partido).
- `data/dictionaries/`: diccionarios ligeros (versionados).
- `assets/`: logos e identidad (escudos bajo LFS o ignorados).

## Setup
```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows
pip install -r requirements.txt
