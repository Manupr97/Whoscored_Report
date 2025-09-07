# src/whoscored_viz/paths.py
from pathlib import Path
from decouple import config

# Directorio base de datos desde .env o valor por defecto
BASE_DATA_DIR = Path(config('BASE_DATA_DIR', default='./data')).resolve()

# Carpeta donde guardamos los partidos del MatchCenter
BASE_DIR = BASE_DATA_DIR / 'raw' / 'matchcenter'

# Carpeta de escudos (dentro de assets)
ESCUDOS_DIR = Path(__file__).resolve().parents[2] / 'assets' / 'Escudos'

# Carpeta donde guardaremos los diccionarios
OUT_DIR = BASE_DATA_DIR / 'dictionaries'
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEAM_CSV = OUT_DIR / 'team_identity.csv'
PLAYERS_CSV = OUT_DIR / 'players_master.csv'