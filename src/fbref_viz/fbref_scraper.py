#!/usr/bin/env python3
"""
Script para extraer datos limpios de jugadores de las 5 grandes ligas europeas desde FBRef.
Genera dos CSVs: uno para jugadores de campo y otro para porteros.

Autor: Analista de datos deportivos
Fecha: 2025
"""

import os
import time
import hashlib
import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup, Comment
from typing import List, Optional

# Importar el sistema de paths del proyecto
try:
    from .paths import BASE_DATA_DIR
    OUTDIR = BASE_DATA_DIR / "raw" / "fbref"
except ImportError:
    # Fallback si no se puede importar (ejecución directa)
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).resolve().parents[2]  # subir 2 niveles desde src/fbref_viz/
    OUTDIR = PROJECT_ROOT / "data" / "raw" / "fbref"

# ---- Parámetros del proyecto ----
SEASON = "2025-2026"
RANDOM_SEED = 42

# Crear directorio de salida
OUTDIR.mkdir(parents=True, exist_ok=True)

# =============================
# FUNCIONES DE DESCARGA Y EXTRACCIÓN
# =============================

def fetch_html(url: str,
               tries: int = 3,
               backoff: float = 1.5,
               timeout: int = 20,
               headers: Optional[dict] = None) -> str:
    """Descarga HTML con reintentos exponenciales."""
    headers = headers or {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            time.sleep(backoff ** (i + 1))
    raise RuntimeError(f"No se pudo descargar la página: {last_err}")

def extract_table_html(html: str, table_id: str) -> str:
    """Devuelve el HTML de <table id=table_id>. Busca visible y dentro de comentarios HTML."""
    soup = BeautifulSoup(html, "lxml")
    # 1) visible
    t = soup.find("table", id=table_id)
    if t:
        return str(t)
    # 2) comentada
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        inner = BeautifulSoup(c, "lxml")
        t2 = inner.find("table", id=table_id)
        if t2:
            return str(t2)
    # 3) contenedor con ese id que contenga una tabla
    cont = soup.find(id=table_id)
    if cont:
        t3 = cont.find("table")
        if t3:
            return str(t3)
    raise ValueError(f"No se encontró la tabla/contenedor id='{table_id}'.")

def extract_table_html_multi(html: str, candidate_ids: List[str]) -> str:
    """Prueba múltiples ids candidatos y devuelve la primera tabla encontrada."""
    for tid in candidate_ids:
        try:
            return extract_table_html(html, tid)
        except Exception:
            continue
    raise ValueError(f"No se encontró ninguna tabla con ids: {candidate_ids}")

def table_html_to_df(table_html: str, exclude_stats: Optional[List[str]] = None) -> pd.DataFrame:
    """Parsea un <table> de FBref a DataFrame."""
    exclude_stats = list(exclude_stats or [])
    soup = BeautifulSoup(table_html, "lxml")
    table = soup.find("table")
    thead = table.find("thead")
    header_cells = thead.find_all("tr")[-1].find_all(["th", "td"])
    headers = [(c.get("data-stat") or c.get_text(strip=True)) for c in header_cells]
    headers = [h for h in headers if h and h not in exclude_stats]

    data = []
    for tr in table.find("tbody").find_all("tr"):
        # Saltar filas cabecera dentro del body
        if "class" in tr.attrs and "thead" in tr["class"]:
            continue
        row = {}
        for td in tr.find_all(["td", "th"]):
            stat = td.get("data-stat")
            if not stat or stat in exclude_stats:
                continue
            row[stat] = td.get_text(strip=True)
        # Añadir solo si hay contenido real
        if any(str(v).strip() for v in row.values()):
            data.append(row)

    df = pd.DataFrame(data)
    # Asegurar que están todas las columnas esperadas en orden
    for c in headers:
        if c not in df.columns:
            df[c] = pd.NA
    return df[headers]

def _slice_from_first_upper(x: str):
    """Devuelve la subcadena desde la primera mayúscula."""
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if not s:
        return np.nan
    for i, ch in enumerate(s):
        if ch.isupper():
            return s[i:].strip()
    return np.nan

# =============================
# FUNCIONES DE LIMPIEZA
# =============================

def _clean_common(df: pd.DataFrame,
                  pct_cols: Optional[List[str]] = None,
                  fill_nat: bool = True,
                  fill_numeric_na_with_zero: bool = True) -> pd.DataFrame:
    """Limpieza común de datos."""
    pct_cols = pct_cols or []
    df = df.copy()

    # Texto
    if "comp_level" in df.columns:
        df["comp_level"] = df["comp_level"].apply(_slice_from_first_upper)
    if "nationality" in df.columns:
        df["nationality"] = df["nationality"].apply(_slice_from_first_upper)
        if fill_nat:
            df["nationality"] = df["nationality"].fillna("UNK")

    text_cols = [c for c in ["player","nationality","position","team","comp_level"] if c in df.columns]

    # Porcentajes → número
    for c in pct_cols:
        if c in df.columns:
            s = (
                df[c].astype(str)
                     .str.replace("%","", regex=False)
                     .str.replace(",", ".", regex=False)
                     .str.replace(r"[^\d\.\-]", "", regex=True)
                     .str.strip()
                     .replace({"": np.nan, "nan": np.nan, "NaN": np.nan})
            )
            df[c] = pd.to_numeric(s, errors="coerce")

    # Resto numéricas
    for c in df.columns:
        if c in text_cols or c in pct_cols:
            continue
        if df[c].dtype == "object":
            s = (
                df[c].astype(str)
                     .str.replace(",", "", regex=False)
                     .str.replace(r"[^\d\.\-\+]", "", regex=True)
                     .str.replace("+", "", regex=False)
                     .str.strip()
                     .replace({"": np.nan, "nan": np.nan, "NaN": np.nan})
            )
            df[c] = pd.to_numeric(s, errors="coerce")

    if fill_numeric_na_with_zero:
        num_cols = df.select_dtypes(include=["number"]).columns
        df[num_cols] = df[num_cols].fillna(0)

    # Filas válidas
    if "player" in df.columns:
        df = df[df["player"].astype(str).str.strip().ne("")]

    return df

# =============================
# FUNCIONES DE EXTRACCIÓN POR CATEGORÍA
# =============================

def get_fbref_big5_stats_stints(
    url: str = "https://fbref.com/en/comps/Big5/stats/players/Big-5-European-Leagues-Stats",
    table_id: str = "stats_standard",
    exclude_stats: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extrae estadísticas estándar de jugadores."""
    exclude_stats = list(exclude_stats or ["ranker", "matches"])

    html = fetch_html(url)
    tbl_html = extract_table_html(html, table_id)
    df = table_html_to_df(tbl_html, exclude_stats=exclude_stats)
    df = _clean_common(df)

    # Renombrado al español
    rename_dict = {
        'player': 'jugador',
        'nationality': 'nacionalidad',
        'position': 'posicion',
        'team': 'equipo',
        'comp_level': 'competicion',
        'age': 'edad',
        'birth_year': 'año_nacimiento',
        'games': 'partidos_jugados',
        'games_starts': 'partidos_titular',
        'minutes': 'minutos',
        'minutes_90s': 'partidos_completos_90',
        'goals': 'goles',
        'assists': 'asistencias',
        'goals_assists': 'goles_asistencias',
        'goals_pens': 'goles_sin_penalti',
        'pens_made': 'penales_anotados',
        'pens_att': 'penales_intentados',
        'cards_yellow': 'tarjetas_amarillas',
        'cards_red': 'tarjetas_rojas',
        'xg': 'xg',
        'npxg': 'npxg',
        'xg_assist': 'xg_asistencias',
        'npxg_xg_assist': 'npxg_xg_asistencias',
        'progressive_carries': 'conducciones_progresivas',
        'progressive_passes': 'pases_progresivos',
        'progressive_passes_received': 'pases_progresivos_recibidos',
        'goals_per90': 'goles_por90',
        'assists_per90': 'asistencias_por90',
        'goals_assists_per90': 'goles_asistencias_por90',
        'goals_pens_per90': 'goles_penalti_por90',
        'goals_assists_pens_per90': 'goles_asistencias_penalti_por90',
        'xg_per90': 'xg_por90',
        'xg_assist_per90': 'xg_asistencias_por90',
        'xg_xg_assist_per90': 'xg_xg_asistencias_por90',
        'npxg_per90': 'npxg_por90',
        'npxg_xg_assist_per90': 'npxg_xg_asistencias_por90',
    }
    df.rename(columns={k: v for k, v in rename_dict.items() if k in df.columns}, inplace=True)

    # Orden cómodo
    first_cols = [c for c in ['jugador', 'nacionalidad', 'posicion', 'equipo', 'competicion'] if c in df.columns]
    df = df[first_cols + [c for c in df.columns if c not in first_cols]]
    df = df[df['jugador'].astype(str).str.strip().ne("")].reset_index(drop=True)

    return df

def get_fbref_big5_shooting(
    url: str = "https://fbref.com/en/comps/Big5/shooting/players/Big-5-European-Leagues-Stats",
    table_id: str = "stats_shooting",
    exclude_stats: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extrae estadísticas de tiro."""
    exclude_stats = list(exclude_stats or ["ranker","matches"])

    html = fetch_html(url)
    tbl_html = extract_table_html(html, table_id)
    df = table_html_to_df(tbl_html, exclude_stats=exclude_stats)

    df = _clean_common(
        df,
        pct_cols=["shots_on_target_pct", "goals_per_shot", "goals_per_shot_on_target", "npxg_per_shot"]
    )

    # Renombrado ES
    rename = {
        'player':'jugador','nationality':'nacionalidad','position':'posicion','team':'equipo','comp_level':'competicion',
        'age':'edad','birth_year':'año_nacimiento','minutes_90s':'partidos_completos_90',
        'goals':'goles','shots':'tiros','shots_on_target':'tiros_a_puerta','shots_on_target_pct':'porc_tiros_a_puerta',
        'shots_per90':'tiros_por90','shots_on_target_per90':'tiros_a_puerta_por90',
        'goals_per_shot':'goles_por_tiro','goals_per_shot_on_target':'goles_por_tiro_a_puerta',
        'average_shot_distance':'dist_media_tiro','shots_free_kicks':'tiros_libres',
        'pens_made':'penales_anotados','pens_att':'penales_intentados',
        'xg':'xg','npxg':'npxg','npxg_per_shot':'npxg_por_tiro',
        'xg_net':'xg_neto','npxg_net':'npxg_neto'
    }
    df.rename(columns={k:v for k,v in rename.items() if k in df.columns}, inplace=True)

    first = [c for c in ['jugador','nacionalidad','posicion','equipo','competicion'] if c in df.columns]
    return df[first + [c for c in df.columns if c not in first]]

def get_fbref_big5_passing_all(
    url_pass: str = "https://fbref.com/en/comps/Big5/passing/players/Big-5-European-Leagues-Stats",
    url_past: str = "https://fbref.com/en/comps/Big5/passing_types/players/Big-5-European-Leagues-Stats",
    table_id_pass: str = "stats_passing",
    table_id_past: str = "stats_passing_types",
    exclude_stats: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extrae estadísticas de pases y tipos de pases."""
    exclude_stats = list(exclude_stats or ["ranker","matches"])
    keys = ["player","team","comp_level"]

    # Passing
    df_pass = table_html_to_df(extract_table_html(fetch_html(url_pass), table_id_pass), exclude_stats)
    df_pass = _clean_common(df_pass, pct_cols=["passes_pct","passes_pct_short","passes_pct_medium","passes_pct_long"])

    # Passing types
    df_past = table_html_to_df(extract_table_html(fetch_html(url_past), table_id_past), exclude_stats)
    df_past = _clean_common(df_past)

    # Dedupe types
    if "minutes_90s" in df_past.columns:
        df_past = (df_past.sort_values("minutes_90s", ascending=False)
                          .drop_duplicates(keys, keep="first"))

    cols_add = [c for c in df_past.columns if c not in keys and c not in df_pass.columns]
    df = df_pass.merge(df_past[keys + cols_add], on=keys, how="left")

    # Renombrado ES
    rename_pass = {
        'player':'jugador','nationality':'nacionalidad','position':'posicion','team':'equipo','comp_level':'competicion',
        'age':'edad','birth_year':'año_nacimiento','minutes_90s':'partidos_completos_90',
        'passes_completed':'pases_completados','passes':'pases','passes_pct':'porc_precision_pase',
        'passes_total_distance':'dist_total_pases','passes_progressive_distance':'dist_progresiva_pases',
        'passes_completed_short':'pases_cortos_completados','passes_short':'pases_cortos','passes_pct_short':'porc_precision_pase_corto',
        'passes_completed_medium':'pases_medios_completados','passes_medium':'pases_medios','passes_pct_medium':'porc_precision_pase_medio',
        'passes_completed_long':'pases_largos_completados','passes_long':'pases_largos','passes_pct_long':'porc_precision_pase_largo',
        'assists':'asistencias','xg_assist':'xg_asistencias','pass_xa':'xa_modelado','xg_assist_net':'xg_asistencias_neto',
        'assisted_shots':'tiros_asistidos','passes_into_final_third':'pases_tercio_final',
        'passes_into_penalty_area':'pases_area','crosses_into_penalty_area':'centros_area',
        'progressive_passes':'pases_progresivos'
    }
    rename_past = {
        'passes_live':'pases_en_juego','passes_dead':'pases_balon_parado','passes_free_kicks':'pases_tiro_libre',
        'through_balls':'pases_al_hueco','passes_switches':'cambios_de_juego','crosses':'centros',
        'throw_ins':'saques_de_banda','corner_kicks':'saques_de_esquina','corner_kicks_in':'esquinas_hacia_adentro',
        'corner_kicks_out':'esquinas_hacia_fuera','corner_kicks_straight':'esquinas_rectas',
        'passes_offsides':'pases_fuera_de_juego','passes_blocked':'pases_bloqueados'
    }
    df.rename(columns={**{k:v for k,v in rename_pass.items() if k in df.columns},
                       **{k:v for k,v in rename_past.items() if k in df.columns}}, inplace=True)

    first = [c for c in ['jugador','nacionalidad','posicion','equipo','competicion'] if c in df.columns]
    return df[first + [c for c in df.columns if c not in first]]

def get_fbref_big5_misc_defense_all(
    url_misc: str = "https://fbref.com/en/comps/Big5/misc/players/Big-5-European-Leagues-Stats",
    url_def:  str = "https://fbref.com/en/comps/Big5/defense/players/Big-5-European-Leagues-Stats",
    table_id_misc: str = "stats_misc",
    candidate_ids_def: List[str] = ["stats_defense","div_stats_defense"],
    exclude_stats: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extrae estadísticas misceláneas y defensivas."""
    exclude_stats = list(exclude_stats or ["ranker","matches"])
    keys = ["player","team","comp_level"]

    # misc
    df_misc = table_html_to_df(extract_table_html(fetch_html(url_misc), table_id_misc), exclude_stats)
    df_misc = _clean_common(df_misc, pct_cols=["aerials_won_pct"])

    # defense
    df_def  = table_html_to_df(extract_table_html_multi(fetch_html(url_def), candidate_ids_def), exclude_stats)
    df_def  = _clean_common(df_def, pct_cols=["challenge_tackles_pct"])

    if "minutes_90s" in df_def.columns:
        df_def = (df_def.sort_values("minutes_90s", ascending=False)
                        .drop_duplicates(keys, keep="first"))

    cols_add = [c for c in df_def.columns if c not in keys and c not in df_misc.columns]
    df = df_misc.merge(df_def[keys + cols_add], on=keys, how="left")

    # Renombrado ES
    rename_misc = {
        'player':'jugador','nationality':'nacionalidad','position':'posicion','team':'equipo','comp_level':'competicion',
        'age':'edad','birth_year':'año_nacimiento','minutes_90s':'partidos_completos_90',
        'cards_yellow':'tarjetas_amarillas','cards_red':'tarjetas_rojas','cards_yellow_red':'doble_amarilla',
        'fouls':'faltas_cometidas','fouled':'faltas_recibidas','offsides':'fueras_de_juego',
        'crosses':'centros','interceptions':'intercepciones','tackles_won':'entradas_ganadas',
        'pens_won':'penaltis_ganados','pens_conceded':'penaltis_concedidos','own_goals':'autogoles',
        'ball_recoveries':'recuperaciones','aerials_won':'duelos_aereos_ganados','aerials_lost':'duelos_aereos_perdidos',
        'aerials_won_pct':'porc_duelos_aereos_ganados'
    }
    rename_def = {
        'tackles':'entradas','tackles_def_3rd':'entradas_tercio_defensivo','tackles_mid_3rd':'entradas_tercio_medio',
        'tackles_att_3rd':'entradas_tercio_ofensivo','challenge_tackles':'regates_parados',
        'challenges':'regates_enfrentados','challenge_tackles_pct':'porc_regates_parados',
        'challenges_lost':'regates_no_parados','blocks':'bloqueos','blocked_shots':'tiros_bloqueados',
        'blocked_passes':'pases_bloqueados','tackles_interceptions':'entradas_mas_intercepciones',
        'clearances':'despejes','errors':'errores'
    }
    df.rename(columns={**{k:v for k,v in rename_misc.items() if k in df.columns},
                       **{k:v for k,v in rename_def.items() if k in df.columns}}, inplace=True)

    first = [c for c in ['jugador','nacionalidad','posicion','equipo','competicion'] if c in df.columns]
    return df[first + [c for c in df.columns if c not in first]]

def get_fbref_big5_possession(
    url: str = "https://fbref.com/en/comps/Big5/possession/players/Big-5-European-Leagues-Stats",
    table_id: str = "stats_possession",
    exclude_stats: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extrae estadísticas de posesión."""
    exclude_stats = list(exclude_stats or ["ranker","matches"])

    df = table_html_to_df(extract_table_html(fetch_html(url), table_id), exclude_stats)
    df = _clean_common(df, pct_cols=["take_ons_won_pct","take_ons_tackled_pct"])

    rename = {
        'player':'jugador','nationality':'nacionalidad','position':'posicion','team':'equipo','comp_level':'competicion',
        'age':'edad','birth_year':'año_nacimiento','minutes_90s':'partidos_completos_90',
        'touches':'toques','touches_def_pen_area':'toques_area_propia','touches_def_3rd':'toques_tercio_defensivo',
        'touches_mid_3rd':'toques_tercio_medio','touches_att_3rd':'toques_tercio_ofensivo',
        'touches_att_pen_area':'toques_area_rival','touches_live_ball':'toques_en_juego',
        'take_ons':'regates_intentados','take_ons_won':'regates_exitosos','take_ons_won_pct':'porc_regates_exitosos',
        'take_ons_tackled':'regates_no_exitosos','take_ons_tackled_pct':'porc_regates_no_exitosos',
        'carries':'conducciones','carries_distance':'distancia_conducciones',
        'carries_progressive_distance':'distancia_conducciones_progresivas',
        'progressive_carries':'conducciones_progresivas','carries_into_final_third':'conducciones_tercio_final',
        'carries_into_penalty_area':'conducciones_area','miscontrols':'malos_controles',
        'dispossessed':'perdidas','passes_received':'pases_recibidos',
        'progressive_passes_received':'pases_progresivos_recibidos'
    }
    df.rename(columns={k:v for k,v in rename.items() if k in df.columns}, inplace=True)

    first = [c for c in ['jugador','nacionalidad','posicion','equipo','competicion'] if c in df.columns]
    return df[first + [c for c in df.columns if c not in first]]

def get_fbref_big5_gk(
    url_basic: str = "https://fbref.com/en/comps/Big5/keepers/players/Big-5-European-Leagues-Stats",
    url_adv:   str = "https://fbref.com/en/comps/Big5/keepersadv/players/Big-5-European-Leagues-Stats",
    id_basic:  str = "stats_keeper",
    id_adv:    str = "stats_keeper_adv",
    exclude_stats: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Extrae estadísticas de porteros."""
    exclude_stats = list(exclude_stats or ["ranker","matches"])
    keys = ["player","team","comp_level"]

    # basic
    df_b = table_html_to_df(extract_table_html(fetch_html(url_basic), id_basic), exclude_stats)
    df_b = _clean_common(df_b, pct_cols=["gk_save_pct","gk_clean_sheets_pct","gk_pens_save_pct"])

    # advanced
    df_a = table_html_to_df(extract_table_html(fetch_html(url_adv), id_adv), exclude_stats)
    df_a = _clean_common(df_a, pct_cols=[
        "gk_psnpxg_per_shot_on_target_against","gk_psxg_net_per90",
        "gk_pct_passes_launched","gk_pct_goal_kicks_launched","gk_crosses_stopped_pct"
    ])

    if "minutes_90s" in df_a.columns:
        df_a = (df_a.sort_values("minutes_90s", ascending=False)
                      .drop_duplicates(keys, keep="first"))

    cols_add = [c for c in df_a.columns if c not in keys and c not in df_b.columns]
    df = df_b.merge(df_a[keys + cols_add], on=keys, how="left")

    # Renombrado ES
    rename_b = {
        'player':'jugador','nationality':'nacionalidad','position':'posicion','team':'equipo','comp_level':'competicion',
        'age':'edad','birth_year':'año_nacimiento','gk_minutes':'minutos','minutes_90s':'partidos_completos_90',
        'gk_games':'pj','gk_games_starts':'titular',
        'gk_goals_against':'goles_en_contra','gk_goals_against_per90':'goles_contra_por90',
        'gk_shots_on_target_against':'tiros_a_puerta_en_contra','gk_saves':'paradas',
        'gk_save_pct':'porc_paradas','gk_wins':'victorias','gk_ties':'empates','gk_losses':'derrotas',
        'gk_clean_sheets':'porterias_cero','gk_clean_sheets_pct':'porc_porterias_cero',
        'gk_pens_att':'penales_recibidos','gk_pens_allowed':'penales_concedidos',
        'gk_pens_saved':'penales_parados','gk_pens_missed':'penales_fallados','gk_pens_save_pct':'porc_penales_parados'
    }
    rename_a = {
        'gk_goals_against':'goles_en_contra_adv',
        'gk_pens_allowed':'penales_concedidos_adv',
        'gk_free_kick_goals_against':'goles_falta_directa_en_contra',
        'gk_corner_kick_goals_against':'goles_corners_en_contra',
        'gk_own_goals_against':'autogoles_en_contra',
        'gk_psxg':'psxg_en_contra',
        'gk_psnpxg_per_shot_on_target_against':'psnpxg_por_tiro_en_contra',
        'gk_psxg_net':'psxg_neto','gk_psxg_net_per90':'psxg_neto_por90',
        'gk_passes_completed_launched':'pases_largos_completados','gk_passes_launched':'pases_largos',
        'gk_passes_pct_launched':'porc_pases_largos_completados',
        'gk_passes':'pases_totales','gk_passes_throws':'saques_con_la_mano',
        'gk_pct_passes_launched':'porc_pases_lanzados',
        'gk_passes_length_avg':'long_media_pase',
        'gk_goal_kicks':'saques_de_porteria','gk_pct_goal_kicks_launched':'porc_saques_largos',
        'gk_goal_kick_length_avg':'long_media_saque',
        'gk_crosses':'centros_defendidos','gk_crosses_stopped':'centros_atrapados',
        'gk_crosses_stopped_pct':'porc_centros_atrapados',
        'gk_def_actions_outside_pen_area':'acciones_fuera_del_area',
        'gk_def_actions_outside_pen_area_per90':'acciones_fuera_del_area_por90',
        'gk_avg_distance_def_actions':'dist_media_acciones_fuera_area'
    }
    df.rename(columns={**{k:v for k,v in rename_b.items() if k in df.columns},
                       **{k:v for k,v in rename_a.items() if k in df.columns}}, inplace=True)
    
    # Fix porcentajes GK: recomputar y sanear en [0, 100]
    # 1) Porcentaje porterías a cero = (CS / PJ) * 100
    if {"pj", "porterias_cero"} <= set(df.columns):
        df["porc_porterias_cero"] = np.where(
            df["pj"] > 0,
            (df["porterias_cero"] / df["pj"]) * 100.0,
            0.0
        )

    # 2) Porcentaje de paradas = (Paradas / Tiros a puerta en contra) * 100
    if {"paradas", "tiros_a_puerta_en_contra"} <= set(df.columns):
        df["porc_paradas"] = np.where(
            df["tiros_a_puerta_en_contra"] > 0,
            (df["paradas"] / df["tiros_a_puerta_en_contra"]) * 100.0,
            0.0
        )

    # 3) Porcentaje penales parados = (Penales parados / Penales recibidos) * 100
    if {"penales_parados", "penales_recibidos"} <= set(df.columns):
        df["porc_penales_parados"] = np.where(
            df["penales_recibidos"] > 0,
            (df["penales_parados"] / df["penales_recibidos"]) * 100.0,
            0.0
        )

    # 4) "Clip" de TODOS los porcentajes a [0, 100] por seguridad
    pct_cols = [c for c in df.columns if c.startswith("porc_") or c.endswith("_pct")]
    if pct_cols:
        df[pct_cols] = df[pct_cols].clip(lower=0, upper=100)

    first = [c for c in ['jugador','nacionalidad','posicion','equipo','competicion'] if c in df.columns]
    return df[first + [c for c in df.columns if c not in first]]

# =============================
# FUNCIONES DE PROCESAMIENTO Y MERGE
# =============================

KEYS = ["jugador", "equipo", "competicion"]

def merge_new_cols(left: pd.DataFrame, right: pd.DataFrame, keys=KEYS) -> pd.DataFrame:
    """Merge 'right' en 'left' solo con columnas que aún no existen (evita duplicados)."""
    new_cols = [c for c in right.columns if c not in keys and c not in left.columns]
    return left.merge(right[keys + new_cols], on=keys, how="left")

def dedupe_on_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Si existe 'partidos_completos_90', conserva por stint la fila con mayor valor; si no, drop_duplicates."""
    if "partidos_completos_90" in df.columns:
        return (df.sort_values("partidos_completos_90", ascending=False)
                  .drop_duplicates(KEYS, keep="first"))
    return df.drop_duplicates(KEYS, keep="first")

def add_stint_id(df: pd.DataFrame) -> pd.DataFrame:
    """Crea un ID único por stint a partir de (jugador|equipo|competicion|season)."""
    df = df.copy()
    for col in ["jugador","equipo","competicion","season"]:
        if col not in df.columns:
            raise ValueError(f"Falta columna requerida para stint_id: {col}")
    df["stint_id"] = (
        df["jugador"].astype(str) + "|" +
        df["equipo"].astype(str) + "|" +
        df["competicion"].astype(str) + "|" +
        df["season"].astype(str)
    ).apply(lambda s: hashlib.md5(s.encode()).hexdigest())
    return df

def validate_data(df: pd.DataFrame, name: str):
    """Validación básica de calidad de datos."""
    print(f"\n=== VALIDACIÓN: {name} ===")
    print(f"Shape: {df.shape}")
    
    # Duplicados
    if "stint_id" in df.columns:
        dups = df["stint_id"].duplicated().sum()
        print(f"Duplicados por stint_id: {dups}")
    
    # Columnas críticas con NaN
    critical_cols = ["jugador", "equipo", "competicion"]
    for col in critical_cols:
        if col in df.columns:
            nan_count = df[col].isna().sum()
            print(f"NaN en {col}: {nan_count}")
    
    # Distribución por competición
    if "competicion" in df.columns:
        print("\nDistribución por competición:")
        print(df["competicion"].value_counts())
    
    # Estadísticas básicas de minutos
    if "minutos" in df.columns:
        print(f"\nMinutos - Min: {df['minutos'].min()}, Max: {df['minutos'].max()}, Media: {df['minutos'].mean():.1f}")

# =============================
# FUNCIÓN PRINCIPAL
# =============================

def main():
    """Función principal que ejecuta todo el proceso de extracción."""
    print(f"Iniciando extracción de datos FBRef para temporada {SEASON}")
    print(f"Guardando en directorio: {OUTDIR}")
    
    try:
        # 1. Extraer todas las categorías
        print("\n1. Extrayendo estadísticas estándar...")
        df_stints = get_fbref_big5_stats_stints().assign(season=SEASON)
        
        print("2. Extrayendo estadísticas de tiro...")
        df_shoot = get_fbref_big5_shooting().assign(season=SEASON)
        
        print("3. Extrayendo estadísticas de pases...")
        df_pass_all = get_fbref_big5_passing_all().assign(season=SEASON)
        
        print("4. Extrayendo estadísticas de posesión...")
        df_pos = get_fbref_big5_possession().assign(season=SEASON)
        
        print("5. Extrayendo estadísticas misceláneas y defensivas...")
        df_miscd = get_fbref_big5_misc_defense_all().assign(season=SEASON)
        
        print("6. Extrayendo estadísticas de porteros...")
        df_gk = get_fbref_big5_gk().assign(season=SEASON)
        
        # 2. Procesar datos de jugadores de campo
        print("\n7. Procesando datos de jugadores de campo...")
        
        # Ancla base con stats standard
        base = dedupe_on_keys(df_stints)
        
        # Deduplicar el resto
        shoot = dedupe_on_keys(df_shoot)
        pall = dedupe_on_keys(df_pass_all)
        misd = dedupe_on_keys(df_miscd)
        poss = dedupe_on_keys(df_pos)
        
        # Merges incrementales
        outfield_master = (base
            .pipe(merge_new_cols, shoot)
            .pipe(merge_new_cols, pall)
            .pipe(merge_new_cols, misd)
            .pipe(merge_new_cols, poss)
        )
        
        # Excluir porteros
        if "posicion" in outfield_master.columns:
            outfield_master = outfield_master[
                ~outfield_master["posicion"].astype(str).str.contains(r"\bGK\b", na=False)
            ]
        
        # Añadir stint_id y limpiar
        outfield_master = add_stint_id(outfield_master).reset_index(drop=True)
        
        # 3. Procesar datos de porteros
        print("8. Procesando datos de porteros...")
        goalkeepers_master = dedupe_on_keys(df_gk)
        goalkeepers_master = add_stint_id(goalkeepers_master).reset_index(drop=True)
        
        # 4. Validar datos
        validate_data(outfield_master, "JUGADORES DE CAMPO")
        validate_data(goalkeepers_master, "PORTEROS")

        # 5. Guardar CSVs
        print("\n9. Guardando archivos CSV...")

        outfield_file = OUTDIR / f"jugadores_campo_{SEASON.replace('-', '_')}.csv"
        goalkeepers_file = OUTDIR / f"porteros_{SEASON.replace('-', '_')}.csv"

        # MÉTODO ROBUSTO CON MANEJO DE ERRORES:
        def safe_csv_write(df, filepath, description):
            """Escribe CSV con múltiples intentos y verificación"""
            methods = [
                lambda: df.to_csv(filepath, index=False, encoding='utf-8'),
                lambda: df.to_csv(str(filepath), index=False, encoding='utf-8'), 
                lambda: df.to_csv(filepath, index=False, encoding='utf-8-sig'),
                lambda: df.to_csv(filepath, index=False),
                lambda: df.to_csv(filepath, index=False, encoding='latin-1'),
            ]
            
            for i, method in enumerate(methods, 1):
                try:
                    print(f"   Intentando método {i} para {description}...")
                    method()
                    
                    # Verificación inmediata
                    if Path(filepath).exists() and Path(filepath).stat().st_size > 0:
                        size = Path(filepath).stat().st_size
                        print(f"   ✅ {description} guardado: {filepath}")
                        print(f"      Tamaño: {size:,} bytes")
                        return True
                    else:
                        print(f"   ⚠️ Método {i} no creó archivo válido")
                        
                except Exception as e:
                    print(f"   ❌ Método {i} falló: {e}")
                    continue
            
            print(f"   💀 TODOS los métodos fallaron para {description}")
            return False

        # Intentar guardar con método robusto
        success_outfield = safe_csv_write(outfield_master, outfield_file, "Jugadores de campo")
        success_goalkeepers = safe_csv_write(goalkeepers_master, goalkeepers_file, "Porteros")

        # Verificación final
        print(f"\n=== RESULTADO FINAL ===")
        if success_outfield and success_goalkeepers:
            print(f"✅ Ambos archivos guardados exitosamente")
            print(f"✓ Total jugadores de campo: {len(outfield_master)}")
            print(f"✓ Total porteros: {len(goalkeepers_master)}")
        else:
            print(f"❌ Hubo problemas guardando archivos")
            if not success_outfield:
                print(f"   - Jugadores de campo: FALLO")
            if not success_goalkeepers:
                print(f"   - Porteros: FALLO")
            
            # Guardar en ubicación alternativa
            fallback_dir = Path.home() / "Desktop"
            print(f"\n🔄 Intentando guardar en ubicación alternativa: {fallback_dir}")
            
            try:
                alt_outfield = fallback_dir / f"jugadores_campo_{SEASON.replace('-', '_')}.csv"
                alt_goalkeepers = fallback_dir / f"porteros_{SEASON.replace('-', '_')}.csv"
                
                outfield_master.to_csv(alt_outfield, index=False, encoding='utf-8')
                goalkeepers_master.to_csv(alt_goalkeepers, index=False, encoding='utf-8')
                
                print(f"✅ Guardado alternativo exitoso:")
                print(f"   → {alt_outfield}")
                print(f"   → {alt_goalkeepers}")
                
            except Exception as e:
                print(f"❌ Incluso el guardado alternativo falló: {e}")

        print(f"\n=== DIAGNÓSTICO ADICIONAL ===")
        print(f"DataFrame outfield_master:")
        print(f"  - Tipo: {type(outfield_master)}")
        print(f"  - Shape: {outfield_master.shape}")
        print(f"  - Memoria: {outfield_master.memory_usage(deep=True).sum() / 1024 / 1024:.1f} MB")
        # Verificar columnas con caracteres problemáticos
        problematic_cols = []
        for c in outfield_master.columns:
            if outfield_master[c].dtype == 'object':
                try:
                    if outfield_master[c].str.contains('[\x00-\x1f]', na=False).any():
                        problematic_cols.append(c)
                except:
                    pass
        print(f"  - Columnas problemáticas: {problematic_cols}")

        return outfield_master, goalkeepers_master
        
    except Exception as e:
        print(f"❌ Error durante la extracción: {str(e)}")
        raise

if __name__ == "__main__":
    # Configurar pandas para mejor visualización
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 140)
    pd.set_option("display.max_colwidth", 120)
    
    # Ejecutar proceso principal
    jugadores_campo, porteros = main()