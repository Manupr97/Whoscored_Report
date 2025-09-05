from pathlib import Path

BASE_DIR   = Path(r"C:\Users\manue\OneDrive\Escritorio\Proyecto WhoScored\data\MatchCenter\Competition\Season")
ESCUDOS_DIR= Path(r"C:\Users\manue\OneDrive\Escritorio\Proyecto WhoScored\Escudos\LaLiga")
OUT_DIR    = BASE_DIR.parent.parent / "dictionaries"   # ...\data\MatchCenter\dictionaries
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEAM_CSV    = OUT_DIR / "team_identity.csv"
PLAYERS_CSV = OUT_DIR / "players_master.csv"