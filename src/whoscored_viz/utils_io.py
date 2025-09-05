from pathlib import Path
import pandas as pd

def read_csv_safe(path: Path) -> pd.DataFrame | None:
    if not path.exists(): return None
    trials = [
        dict(sep=",", encoding="utf-8"),
        dict(sep=";", encoding="utf-8"),
        dict(sep=",", encoding="latin-1"),
        dict(sep=";", encoding="latin-1"),
        dict(sep=",", encoding="cp1252"),
        dict(sep=";", encoding="cp1252"),
    ]
    for kw in trials:
        try: return pd.read_csv(path, **kw)
        except Exception: pass
    return None

def iter_match_folders(base: Path):
    for folder in sorted(base.glob("*")):
        csv_dir = folder / "csv"
        if folder.is_dir() and csv_dir.exists():
            yield folder, csv_dir
