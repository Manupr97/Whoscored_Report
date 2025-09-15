from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import numpy as np
import re

from .paths import BASE_DIR, ESCUDOS_DIR, TEAM_CSV, PLAYERS_CSV
from .utils_io import read_csv_safe, iter_match_folders

# --- slugs según nombres que salen en tus CSV y cómo guardaste los escudos
SLUG_ALIASES = {
    "mallorca":"mallorca","real madrid":"realmadrid","athletic club":"athletic",
    "real betis":"betis","valencia":"valencia","deportivo alaves":"alaves",
    "real oviedo":"realoviedo","celta vigo":"celta","atletico":"atlmadrid",
    "rayo vallecano":"rayovallecano","barcelona":"barcelona","sevilla":"sevilla",
    "real sociedad":"realsociedad","espanyol":"espanyol","osasuna":"osasuna",
    "getafe":"getafe","levante":"levante","elche":"elche","villarreal":"villarreal",
    "girona":"girona",
}
def slug_from_teamname(team_name: str) -> str:
    key = re.sub(r"\s+", " ", team_name.strip().lower())
    return SLUG_ALIASES.get(key, key.replace(" ", ""))

def resolve_logo_path(slug: str) -> str | None:
    if not slug:
        return None

    candidates = {
        slug,
        slug.replace("-", ""),
        slug.replace("_", ""),
        slug.lower(),
    }
    # aliases mínimos ya cubiertos por SLUG_ALIASES via slug_from_teamname;
    # si tienes algún archivo con nombre distinto, añade aquí:
    extra = {
        "atlmadrid": ["atletico", "atletico-madrid"],
        "realmadrid": ["real-madrid"],
        "realsociedad": ["real-sociedad"],
        "realoviedo": ["real-oviedo"],
        "rayovallecano": ["rayo", "rayo-vallecano"],
        "alaves": ["deportivoalaves", "deportivo-alaves", "alavés", "deportivo-alavés"],
    }
    if slug in extra:
        candidates |= set(extra[slug])

    # Busca en ESCUDOS_DIR y subcarpetas (por si hay liga/temporada)
    # Windows no distingue mayúsculas, pero mantenemos extensiones comunes.
    for name in candidates:
        for ext in (".png", ".svg", ".jpg", ".jpeg"):
            p = (ESCUDOS_DIR / f"{name}{ext}")
            if p.exists():
                return str(p)
            # subcarpetas
            for sub in ESCUDOS_DIR.rglob(f"{name}{ext}"):
                return str(sub)
    return None

# Colores oficiales por team_id (tus 20)
TEAM_COLORS_BY_ID = {
    51: {"primary":"#D00000","secondary":"#1A1A1A"}, 52: {"primary":"#FFFFFF","secondary":"#1D1D1B"},
    53: {"primary":"#D00027","secondary":"#1A1A1A"}, 54: {"primary":"#009E49","secondary":"#FFFFFF"},
    55: {"primary":"#FF7900","secondary":"#000000"}, 60: {"primary":"#003DA5","secondary":"#FFFFFF"},
    61: {"primary":"#0057B8","secondary":"#FFD100"}, 62: {"primary":"#8EC6E8","secondary":"#E30613"},
    63: {"primary":"#D20A11","secondary":"#1B3D8E"}, 64: {"primary":"#E30613","secondary":"#FFFFFF"},
    65: {"primary":"#004D98","secondary":"#A50044"}, 67: {"primary":"#D00023","secondary":"#FFFFFF"},
    68: {"primary":"#005DA8","secondary":"#FFFFFF"}, 70: {"primary":"#00529F","secondary":"#FFFFFF"},
    131:{"primary":"#D0021B","secondary":"#003A70"}, 819:{"primary":"#005CB9","secondary":"#FFD200"},
    832:{"primary":"#132257","secondary":"#E41E20"}, 833:{"primary":"#1B5E20","secondary":"#FFFFFF"},
    839:{"primary":"#FDE100","secondary":"#1A1A1A"}, 2783:{"primary":"#D50032","secondary":"#FFFFFF"},
}

def build_team_dictionary(max_matches: int = 10) -> pd.DataFrame:
    rows = []
    for i, (_, csv_dir) in enumerate(iter_match_folders(BASE_DIR)):
        if i >= max_matches:
            break

        # soportar que csv_dir sea archivo o carpeta
        from pathlib import Path
        csv_dir = Path(csv_dir)
        meta_csv = csv_dir if (csv_dir.is_file() and csv_dir.name == "match_meta.csv") else (csv_dir / "match_meta.csv")

        mm = read_csv_safe(meta_csv)
        if mm is not None and not mm.empty:
            cols = {c.strip().lower(): c for c in mm.columns}
            def col(*names):
                for n in names:
                    if n in cols:
                        return cols[n]
            hid = col("home_team_id","home_id","hometeamid")
            hnm = col("home_name","home_team_name","hometeamname","home")
            aid = col("away_team_id","away_id","awayteamid")
            anm = col("away_name","away_team_name","awayteamname","away")
            if all([hid, hnm, aid, anm]):
                for tid, tnm in [
                    (int(mm.iloc[0][hid]), str(mm.iloc[0][hnm])),
                    (int(mm.iloc[0][aid]), str(mm.iloc[0][anm])),
                ]:
                    slug   = slug_from_teamname(tnm)
                    colors = TEAM_COLORS_BY_ID.get(tid, {})
                    rows.append({
                        "team_id":  tid,
                        "team_name": tnm,
                        "slug": slug,
                        "logo_path": resolve_logo_path(slug) or "",
                        "primary":  colors.get("primary",""),
                        "secondary":colors.get("secondary",""),
                    })
            # pasamos al siguiente partido (no intentes JSON si ya hay CSV)
            continue

        # Fallback: JSON si no había CSV o estaba vacío
        json_path = csv_dir / "normalized" / "match_meta.json"
        if json_path.exists():
            import json
            data = json.loads(json_path.read_text(encoding="utf-8"))
            # el tuyo suele ser lista con un dict
            items = data if isinstance(data, list) else [data]
            for obj in items:
                for tid_key, tname_key in [("home_team_id","home_name"), ("away_team_id","away_name")]:
                    tid = obj.get(tid_key); tnm = obj.get(tname_key)
                    if tid and tnm:
                        tid = int(tid)
                        slug   = slug_from_teamname(tnm)
                        colors = TEAM_COLORS_BY_ID.get(tid, {})
                        rows.append({
                            "team_id":  tid,
                            "team_name": str(tnm),
                            "slug": slug,
                            "logo_path": resolve_logo_path(slug) or "",
                            "primary":  colors.get("primary",""),
                            "secondary":colors.get("secondary",""),
                        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No se pudieron extraer equipos de CSV/JSON.")

    df = (df.drop_duplicates("team_id")
            .sort_values("team_id")
            .reset_index(drop=True))

    if TEAM_CSV.exists():
        old = pd.read_csv(TEAM_CSV)
        if "team_id" in old.columns:
            df = (pd.concat([old, df], ignore_index=True)
                    .sort_values("team_id")
                    .drop_duplicates("team_id", keep="last")
                    .reset_index(drop=True))

    df.to_csv(TEAM_CSV, index=False, encoding="utf-8")
    return df

def build_players_dictionary() -> pd.DataFrame:
    acc = []
    from pathlib import Path
    for p in Path(BASE_DIR).rglob("csv/players.csv"):
        df = read_csv_safe(p)
        if df is None or df.empty: 
            continue
        cols = {c.strip().lower(): c for c in df.columns}
        def col(*names):
            for n in names:
                if n in cols: 
                    return cols[n]
        pid   = col("player_id","playerid","id")
        pname = col("player_name","name","player")
        tid   = col("team_id","teamid")
        tname = col("team_name","team")
        shirt = col("shirtnumber","shirtno","number","no")
        if not (pid and pname):
            continue

        tmp = pd.DataFrame({
            "player_id": pd.to_numeric(df[pid], errors="coerce").astype("Int64"),
            "player_name": df[pname].astype(str),
            "team_id": pd.to_numeric(df[tid], errors="coerce").astype("Int64") if tid else pd.Series([pd.NA]*len(df), dtype="Int64"),
            "team_name": df[tname].astype(str) if tname else "",
            "shirtNo": pd.to_numeric(df[shirt], errors="coerce").astype("Int64") if shirt else pd.Series([pd.NA]*len(df), dtype="Int64"),
        })
        acc.append(tmp)

    if not acc:
        df = pd.DataFrame(columns=["player_id","player_name","team_id","team_name","shirtNo"])
    else:
        df = pd.concat(acc, ignore_index=True)
        df = df.dropna(subset=["player_id"])
        df["player_id"] = df["player_id"].astype(int)
        df["name_len"] = df["player_name"].str.len()
        df = (df.sort_values(["player_id","name_len"], ascending=[True, False])
                .drop_duplicates("player_id", keep="first")
                .drop(columns=["name_len"])
                .reset_index(drop=True))

    if PLAYERS_CSV.exists():
        old = pd.read_csv(PLAYERS_CSV)
        if "player_id" in old.columns:
            df = (pd.concat([old, df], ignore_index=True)
                    .sort_values("player_id")
                    .drop_duplicates("player_id", keep="last")
                    .reset_index(drop=True))
    df.to_csv(PLAYERS_CSV, index=False, encoding="utf-8")
    return df

if __name__ == "__main__":
    t = build_team_dictionary(max_matches=10)
    p = build_players_dictionary()
    print(f"Equipos únicos: {t.team_id.nunique()} → {TEAM_CSV}")
    print(f"Jugadores únicos: {p.player_id.nunique()} → {PLAYERS_CSV}")