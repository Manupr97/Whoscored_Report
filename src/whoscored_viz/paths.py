# src/whoscored_viz/paths.py
from pathlib import Path
from decouple import config

def find_project_root(markers=["src", ".env"], max_hops=7):
    """Busca la raíz del proyecto"""
    p = Path.cwd()
    for _ in range(max_hops):
        if any((p / marker).exists() for marker in markers):
            return p
        p = p.parent
    # Fallback: usar la ubicación del archivo paths.py
    return Path(__file__).resolve().parents[2]

# Detectar raíz automáticamente
PROJECT_ROOT = find_project_root()

# Directorio base de datos desde .env o detectado automáticamente
BASE_DATA_DIR = Path(config('BASE_DATA_DIR', default=str(PROJECT_ROOT / 'data'))).resolve()

# Carpeta donde guardamos los partidos del MatchCenter
BASE_DIR = BASE_DATA_DIR / 'raw' / 'matchcenter'
MATCHCENTER_DIR = BASE_DIR  # Alias para el matchcenter

# AGREGAR ESTA LÍNEA QUE FALTA:
FIXTURES_DIR = BASE_DATA_DIR / 'raw' / 'fixtures'

# Carpeta de escudos (dentro de assets)
ESCUDOS_DIR  = PROJECT_ROOT / r"assets\Escudos\LaLiga"

# Carpeta donde guardaremos los diccionarios
OUT_DIR = BASE_DATA_DIR / 'dictionaries'
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEAM_CSV = OUT_DIR / 'team_identity.csv'
PLAYERS_CSV = OUT_DIR / 'players_master.csv'

print(f"[paths.py] PROJECT_ROOT: {PROJECT_ROOT}")
print(f"[paths.py] BASE_DATA_DIR: {BASE_DATA_DIR}")