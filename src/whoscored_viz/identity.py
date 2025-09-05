import pandas as pd
from .paths import TEAM_CSV

TEAM_IDENTITY = None

def _lazy_load():
    global TEAM_IDENTITY
    if TEAM_IDENTITY is None:
        TEAM_IDENTITY = pd.read_csv(TEAM_CSV).set_index("team_id")

def team_style(team_id: int, fallback_name: str = "") -> dict:
    _lazy_load()
    if team_id in TEAM_IDENTITY.index:
        row = TEAM_IDENTITY.loc[team_id]
    else:
        sel = TEAM_IDENTITY.reset_index()
        row = sel[sel["team_name"].str.lower()==fallback_name.lower()].iloc[0]
    return {
        "primary":   row["primary"] or "#2ecc71",
        "secondary": row["secondary"] or "#007bff",
        "logo":      row["logo_path"] if isinstance(row["logo_path"], str) else None,
        "slug":      row["slug"],
        "name":      row.get("team_name", ""),
    }