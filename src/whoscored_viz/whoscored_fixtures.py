# whoscored_fixtures.py
# Scraper de fixtures de WhoScored: SOLO partidos FINALIZADOS
# - Abre fixtures, selecciona mes o recorre meses para un rango de fechas
# - Extrae solo partidos con marcador (dos spans numéricos) => finished
# - Enriquecer start_time desde match center
# - Evita duplicados por match_id al guardar

import re, time, json
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from unidecode import unidecode

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as W
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from urllib.parse import unquote, urlparse
from unidecode import unidecode

def _slug(s: str) -> str:
    s = unidecode(s or "")
    s = s.replace("/", "-").replace("\\", "-")
    return re.sub(r"[^A-Za-z0-9_\- ]+", "", s).strip().replace(" ", "_")

def infer_comp_season(fixtures_url: str, driver=None):
    """
    Intenta inferir (comp_slug, season_slug). Primero desde el DOM (título),
    si falla, desde el último segmento legible de la URL.
    """
    comp, season = None, None

    # 1) DOM (más fiable)
    if driver:
        try:
            # Título grande arriba; WhoScored suele tener cabezales con el nombre del torneo
            hdr = driver.find_element(By.CSS_SELECTOR, "h1, header h1, .tournament-header h1, .grid>h1")
            txt = (hdr.text or "").strip()
            # Ejemplos: "España - LaLiga 2025/2026"
            m = re.search(r"(.*?)-\s*(.+?)\s+(\d{4}[/\-]\d{4})", txt)
            if m:
                comp = m.group(2)
                season = m.group(3)
        except Exception:
            pass

    # 2) Fallback: último slug de la URL tras '/fixtures/'
    if not comp or not season:
        path = urlparse(fixtures_url).path
        # .../fixtures/<slug>
        m = re.search(r"/fixtures/([^/?#]+)", path)
        if m:
            tail = unquote(m.group(1))  # p.ej. "españa-laliga-2025-2026"
            parts = tail.split("-")
            # temporada: última o últimas dos partes con números
            # buscamos algo tipo 2025-2026 o 2024/2025
            for i in range(len(parts)-1, -1, -1):
                if re.match(r"^\d{4}([/\-])\d{4}$", parts[i]):
                    season = parts[i].replace("/", "-")
                    comp = "-".join([p for p in parts if p not in {parts[i]} and not re.match(r"^[A-Za-zÁÉÍÓÚáéíóúñÑ]{2,}$" and "", "")])
                    break
            if not season:
                # simple: coge las dos últimas piezas como 2025-2026
                m2 = re.search(r"(19|20)\d{2}[-/](19|20)\d{2}", tail)
                if m2:
                    season = m2.group(0).replace("/", "-")
            if not comp:
                # quita país si es el primer token (españa, england...)
                tokens = [t for t in parts if not re.match(r"^(espana|españa|england|italia|francia|alemania|alemania|portugal|france|italy|spain)$", unidecode(t.lower()))]
                comp = "-".join([t for t in tokens if not re.match(r"^(19|20)\d{2}$", t)])

    comp_slug = _slug(comp or "Competition")
    season_slug = _slug(season or "Season")
    return comp_slug, season_slug

def fixtures_base_dirs(out_root: Path, comp_slug: str, season_slug: str, month_key_str: str | None = None, range_label: str | None = None):
    """
    Devuelve (base_comp_season_dir, base_run_dir)
    - base_comp_season_dir: data/DataFixtures/<comp>/<season>
    - base_run_dir:         .../<YYYY-MM> o .../range_YYYYMMDD_YYYYMMDD
    """
    base_comp_season = out_root / "DataFixtures" / comp_slug / season_slug
    if month_key_str:
        run_dir = base_comp_season / month_key_str  # p.ej. 2025-08
    else:
        run_dir = base_comp_season / (range_label or "range")
    base_comp_season.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    return base_comp_season, run_dir

# ------------------ Config por defecto (puedes sobreescribir desde fuera) ------------------
BASE = "https://es.whoscored.com"
# LaLiga 25/26 fixtures:
FIXTURES_URL = (
    "https://es.whoscored.com/regions/206/tournaments/4/seasons/10803/"
    "stages/24622/fixtures/espa%C3%B1a-laliga-2025-2026"
)
SPANISH_ABBR = {"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,"jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12}

# ------------------ Driver factory ------------------
def make_driver(use_uc=True, headless=False):
    """Devuelve un driver Chrome. Intenta undetected-chromedriver y cae a webdriver-manager."""
    if use_uc:
        try:
            import undetected_chromedriver as uc
            opts = uc.ChromeOptions()
            for a in [
                "--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                "--window-size=1440,1000","--lang=es-ES",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ]: opts.add_argument(a)
            if headless: opts.add_argument("--headless=new")
            d = uc.Chrome(options=opts)
            d.set_page_load_timeout(45); d.implicitly_wait(5)
            return d
        except Exception:
            pass
    # Fallback Selenium
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    opts = webdriver.ChromeOptions()
    for a in [
        "--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
        "--window-size=1440,1000","--lang=es-ES",
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ]: opts.add_argument(a)
    if headless: opts.add_argument("--headless=new")
    d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    d.set_page_load_timeout(45); d.implicitly_wait(5)
    return d

def robust_click(drv, el):
    try:
        el.click(); return True
    except Exception:
        pass
    try:
        ActionChains(drv).move_to_element(el).pause(0.1).click(el).perform(); return True
    except Exception:
        pass
    try:
        drv.execute_script("arguments[0].click();", el); return True
    except Exception:
        return False

def accept_quantcast_if_present(driver):
    # Banner qc-cmp2 ("ACEPTO")
    try:
        for b in driver.find_elements(By.XPATH, "//button|//a"):
            t = (b.text or "").strip().lower()
            if t and any(k in t for k in ["acepto","aceptar","accept","agree","consent"]):
                if b.is_displayed() and robust_click(driver, b):
                    time.sleep(0.4); return True
        for css in [
            ".qc-cmp2-summary-buttons button",
            "#qc-cmp2-container .qc-cmp2-summary-buttons button",
            'button[aria-label*="Aceptar"]','button[aria-label*="accept"]'
        ]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, css)
                if el.is_displayed() and robust_click(driver, el):
                    time.sleep(0.4); return True
            except Exception:
                continue
    except Exception:
        pass
    return False

# ------------------ Navegación fixtures y mes ------------------
def open_fixtures(driver, fixtures_url=FIXTURES_URL):
    driver.get(fixtures_url)
    W(driver, 25).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class^="Accordion-module_accordion"]')))
    accept_quantcast_if_present(driver)

def open_calendar(driver):
    try:
        toggle = W(driver, 8).until(EC.element_to_be_clickable((By.CSS_SELECTOR, '#toggleCalendar, .toggleDatePicker')))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", toggle)
        robust_click(driver, toggle)
    except TimeoutException:
        # Fallback: clic sobre el texto del mes visible (e.g., "sep 2025")
        lbl = W(driver, 8).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(., ' 2025') and not(self::script)]")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", lbl)
        robust_click(driver, lbl)
    W(driver, 10).until(EC.visibility_of_element_located((By.ID, "datePicker")))

def select_month(driver, target_label):
    """
    target_label: p.ej. 'ago 2025'. Hace clic al <td> correspondiente en el grid del datePicker.
    """
    month_key = target_label.split()[0][:3].lower()  # 'ago'
    xpaths = [
        "//*[@id='datePicker']//tbody[contains(@class,'monthsTbody')]"
        f"//td[normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='{month_key}']",
        # fallback por nombre completo
        "//*[@id='datePicker']//tbody[contains(@class,'monthsTbody')]"
        "//td[normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='agosto']",
    ]
    month_td = None
    for xp in xpaths:
        try:
            month_td = driver.find_element(By.XPATH, xp); break
        except NoSuchElementException:
            continue
    if not month_td:
        raise RuntimeError(f"No encuentro el <td> del mes para '{target_label}'.")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", month_td)
    if not robust_click(driver, month_td):
        raise RuntimeError(f"No pude hacer clic en '{target_label}'.")
    time.sleep(0.6)  # refresco

def open_all_accordions(driver):
    for acc in driver.find_elements(By.CSS_SELECTOR, 'div[class^="Accordion-module_accordion"]'):
        try:
            opened = acc.find_elements(By.CSS_SELECTOR, 'div[class^="Accordion-module_childrenOpened"]')
            if not opened:
                hdr = acc.find_element(By.CSS_SELECTOR, 'div[class^="Accordion-module_header"]')
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", hdr)
                hdr.click(); time.sleep(0.15)
        except Exception:
            continue

# ------------------ Helpers de parsing ------------------
def month_key(label: str) -> str:
    """'ago 2025' -> '2025-08'"""
    lbl = label.lower().strip()
    parts = lbl.split()
    if len(parts) == 2 and parts[0][:3] in SPANISH_ABBR:
        m = SPANISH_ABBR[parts[0][:3]]
        y = int(parts[1])
        return f"{y:04d}-{m:02d}"
    return lbl.replace(" ", "-")

def parse_date_from_day_label(day_label: str):
    """'viernes, sep 12 2025' -> date(2025,9,12)"""
    if not day_label:
        return None
    # extrae: 'sep', '12', '2025'
    m = re.search(r'(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{1,2})\s+(\d{4})', day_label.lower())
    if not m:
        return None
    mon = SPANISH_ABBR[m.group(1)]
    day = int(m.group(2))
    year = int(m.group(3))
    return date(year, mon, day)

def parse_scores_from_row(row, match_id=None):
    """
    Marcador desde #scoresBtn-{id} (dos spans -> local, visitante).
    Fallback: texto 'n - m' en anchor.
    """
    try:
        if match_id:
            div = row.find_element(By.CSS_SELECTOR, f"#scoresBtn-{match_id}")
        else:
            div = row.find_element(By.CSS_SELECTOR, "div[id^='scoresBtn-']")
        spans = div.find_elements(By.TAG_NAME, "span")
        nums = [int(s.text.strip()) for s in spans if (s.text or "").strip().isdigit()]
        if len(nums) >= 2:
            return nums[0], nums[1]
    except Exception:
        pass
    try:
        a = row.find_element(By.CSS_SELECTOR, 'a[id^="scoresBtn-"], a[href^="/matches/"]')
        m = re.search(r"(\d+)\s*[-–]\s*(\d+)", a.text or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None

def extract_match_from_row(row):
    """
    Devuelve SOLO partidos finalizados:
      - Si no hay marcador (dos números), descarta la fila.
    """
    # href + match_id
    try:
        a = row.find_element(By.CSS_SELECTOR, 'a[id^="scoresBtn-"], a[href^="/matches/"]')
        href = a.get_attribute("href") or a.get_attribute("data-href")
        if href and href.startswith("/"):
            href = BASE + href
    except Exception:
        return None

    match_id = None
    if href:
        m = re.search(r"/matches/(\d+)/", href)
        if m:
            match_id = m.group(1)
    if not match_id:
        return None

    # marcador (si no hay dos números, NO está finalizado -> descartar)
    sh, sa = parse_scores_from_row(row, match_id=match_id)
    if sh is None or sa is None:
        return None  # <-- filtro clave: solo finalizados

    # equipos
    home, away = None, None
    try:
        teams = row.find_elements(By.CSS_SELECTOR, 'div[class^="Match-module_teamName"] a')
        if len(teams) >= 2:
            home = teams[0].text.strip()
            away = teams[1].text.strip()
    except Exception:
        pass

    return {
        "home_name": home,
        "away_name": away,
        "home_name_clean": unidecode(home) if home else None,
        "away_name_clean": unidecode(away) if away else None,
        "match_id": match_id,
        "match_url": href,  # guardamos en JSON por si hiciera falta
        "match_centre_url": f"{BASE}/Matches/{match_id}/Live",
        "score_home": sh,
        "score_away": sa,
        "is_finished": True,
    }

# ------------------ Scrape de mes visible (SOLO finalizados) ------------------
def scrape_visible_month_finished(driver) -> pd.DataFrame:
    records = []
    accordions = driver.find_elements(By.CSS_SELECTOR, 'div[class^="Accordion-module_accordion"]')
    for acc in accordions:
        try:
            day_label = acc.find_element(By.CSS_SELECTOR, 'div[class^="Accordion-module_header"] span').text.strip()
        except Exception:
            day_label = None
        match_date = parse_date_from_day_label(day_label)

        rows_container = None
        for css in ('div[class^="Accordion-module_childrenOpened"]', 'div[class*="Accordion-module_children"]'):
            try:
                rows_container = acc.find_element(By.CSS_SELECTOR, css); break
            except Exception:
                continue
        if rows_container is None:
            continue

        rows = rows_container.find_elements(By.CSS_SELECTOR, 'div[class^="Match-module_match"] div[class^="Match-module_row"]')
        for r in rows:
            data = extract_match_from_row(r)
            if not data:
                continue  # <-- solo finalizados
            data["day_label"] = day_label
            data["match_date"] = match_date.isoformat() if match_date else None
            records.append(data)

    df = pd.DataFrame(records).drop_duplicates(subset=["match_id"])
    return df

# ------------------ Enriquecimiento desde match center (start_time) ------------------
def _text_or_none(el):
    try:
        t = (el.text or "").strip()
        return t or None
    except Exception:
        return None

def _extract_time(text):
    m = re.search(r'(^|\s)([01]?\d|2[0-3]):([0-5]\d)(\s|$)', text or "")
    return f"{m.group(2)}:{m.group(3)}" if m else None

def read_matchcenter_meta(driver, match_id):
    """Devuelve dict con start_time (HH:MM); no toca jornada aquí."""
    url = f"{BASE}/Matches/{match_id}/Live"
    driver.get(url)
    try:
        W(driver, 12).until(
            EC.any_of(
                EC.presence_of_element_located((By.ID, "match-header")),
                EC.presence_of_element_located((By.CSS_SELECTOR, f"#scoresBtn-{match_id}"))
            )
        )
    except TimeoutException:
        pass
    meta = {"start_time": None}
    try:
        hdr = driver.find_element(By.ID, "match-header")
        t = _text_or_none(hdr)
        if t:
            meta["start_time"] = _extract_time(t)
    except Exception:
        pass
    return meta

def enrich_start_time(driver, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "start_time" not in df.columns:
        df["start_time"] = None
    for i, row in df.iterrows():
        if df.at[i, "start_time"]:
            continue
        mid = row.get("match_id")
        if not mid:
            continue
        meta = read_matchcenter_meta(driver, str(mid))
        if meta.get("start_time"):
            df.at[i, "start_time"] = meta["start_time"]
        time.sleep(0.25)
    return df

# ------------------ Overrides de jornada (manual) ------------------
def apply_round_overrides(df: pd.DataFrame, csv_path="round_overrides.csv") -> pd.DataFrame:
    p = Path(csv_path)
    if not p.exists():
        # Asegurar que el directorio padre existe antes de crear el archivo
        p.parent.mkdir(parents=True, exist_ok=True)
        # crea plantilla vacía si no existe
        pd.DataFrame(columns=["match_id","match_round"]).to_csv(p, index=False, encoding="utf-8-sig")
        return df
    ov = pd.read_csv(p, dtype={"match_id": str})
    if ov.empty:
        return df
    df = df.copy()
    df["match_id"] = df["match_id"].astype(str)
    df = df.merge(ov, on="match_id", how="left", suffixes=("", "_ov"))
    if "match_round_ov" in df.columns:
        df["match_round"] = df["match_round_ov"].combine_first(df.get("match_round"))
        df.drop(columns=["match_round_ov"], inplace=True)
    return df

# ------------------ Guardado idempotente ------------------
def append_dedup_csv(df_new: pd.DataFrame, csv_path: Path, key="match_id") -> pd.DataFrame:
    """Anexa a CSV evitando duplicados por 'key'. Devuelve el DF resultante final."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        df_old = pd.read_csv(csv_path, dtype={key: str})
        df_all = pd.concat([df_old, df_new], ignore_index=True)
        df_all[key] = df_all[key].astype(str)
        df_all = df_all.drop_duplicates(subset=[key])
    else:
        df_all = df_new.copy()
    df_all.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return df_all

def to_json_records(df: pd.DataFrame, json_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(df.to_dict("records"), ensure_ascii=False, indent=2), encoding="utf-8")

# ------------------ Flujos de alto nivel ------------------
def scrape_month_finished(driver, month_label: str, out_dir: Path, league_slug="laliga_2025_26",
                          fixtures_url=FIXTURES_URL, save_json=True) -> pd.DataFrame:
    """
    Scrapea SOLO partidos finalizados del mes (month_label), enriquece hora y guarda
    bajo: DataFixtures/<comp>/<season>/<YYYY-MM>/{finished_matches.csv,json}
    y deja round_overrides.csv en DataFixtures/<comp>/<season>/
    """
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    open_fixtures(driver, fixtures_url)
    open_calendar(driver)
    select_month(driver, month_label)
    open_all_accordions(driver)

    # Inferir comp/season para la carpeta
    comp_slug, season_slug = infer_comp_season(fixtures_url, driver)
    month_key_str = month_key(month_label)

    base_comp_season, run_dir = fixtures_base_dirs(out_root, comp_slug, season_slug, month_key_str=month_key_str)

    df = scrape_visible_month_finished(driver)
    df = enrich_start_time(driver, df)
    # overrides por liga/temporada (un único CSV compartido)
    df = apply_round_overrides(df, base_comp_season / "round_overrides.csv")

    # CSV ligero y JSON completo
    csv_path  = run_dir / "finished_matches.csv"
    json_path = run_dir / "finished_matches.json"

    df_csv = df.copy()
    wanted = ["match_date","start_time","home_name","away_name","match_id","match_centre_url","score_home","score_away","is_finished","match_round"]
    wanted = [c for c in wanted if c in df_csv.columns]
    df_csv = df_csv[wanted]
    df_final = append_dedup_csv(df_csv, csv_path, key="match_id")

    if save_json:
        to_json_records(df, json_path)

    return df_final

def months_between(d1: date, d2: date):
    """Genera (año, mes) desde d1 hasta d2 inclusive."""
    y, m = d1.year, d1.month
    while (y < d2.year) or (y == d2.year and m <= d2.month):
        yield y, m
        m += 1
        if m == 13:
            m = 1; y += 1

def month_label_from_year_month(y, m):
    rev = {v:k for k,v in SPANISH_ABBR.items()}
    return f"{rev[m]} {y}"

def save_finished_matches_consolidated(df_new: pd.DataFrame, base_out: Path, comp_slug: str, season_slug: str) -> Path:
    """
    Guarda df_new en un único CSV consolidado:
      data/raw/fixtures/DataFixtures/<comp>/<season>/finished_matches.csv
    Si ya existe, concatena y deduplica por match_id, ordena por fecha/hora.
    """
    target_dir = base_out / "DataFixtures" / comp_slug / season_slug
    target_dir.mkdir(parents=True, exist_ok=True)

    target_csv = target_dir / "finished_matches.csv"
    if target_csv.exists():
        try:
            df_old = pd.read_csv(target_csv)
        except Exception:
            df_old = pd.DataFrame()
        frames = [df_old, df_new]
        df_all = pd.concat(frames, ignore_index=True)
    else:
        df_all = df_new.copy()

    # dedup/orden
    if "match_id" in df_all.columns:
        df_all = df_all.drop_duplicates(subset=["match_id"], keep="last")
    if {"match_date","start_time"}.issubset(df_all.columns):
        df_all = df_all.sort_values(["match_date","start_time"])

    # escritura atómica "segura"
    tmp = target_csv.with_suffix(".tmp.csv")
    df_all.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(target_csv)

    return target_csv

def scrape_range_finished(driver, start_date, end_date, out_dir,
                          comp_slug="laliga", season_slug="2025-2026",
                          save_json=True, fixtures_url=None):
    """
    Scrapea SOLO partidos finalizados entre [start_date, end_date], navegando mes a mes.
    Guarda consolidado en: DataFixtures/<comp>/<season>/finished_matches.csv (+ .json opcional)
    """
    # Asegura URL válida siempre
    url = fixtures_url or FIXTURES_URL
    if not isinstance(url, str) or not url.startswith("http"):
        raise ValueError(f"fixtures_url inválida: {url!r}. Revisa FIXTURES_URL.")
    
    # Manejo inteligente de out_dir
    if out_dir is None:
        try:
            from .paths import FIXTURES_DIR
            out_root = FIXTURES_DIR
        except ImportError:
            out_root = Path("data/raw/fixtures")  # fallback
    else:
        out_root = Path(out_dir)
    
    out_root.mkdir(parents=True, exist_ok=True)

    all_rows = []
    for y, m in months_between(start_date, end_date):
        mlab = month_label_from_year_month(y, m)  # 'sep 2025', etc.

        # Abrir fixtures del torneo/temporada correcto
        open_fixtures(driver, url)
        open_calendar(driver)
        select_month(driver, mlab)
        open_all_accordions(driver)

        # Extraer solo finalizados del mes visible y filtrar al rango
        df_m = scrape_visible_month_finished(driver)
        if "match_date" in df_m.columns:
            mask = df_m["match_date"].notna() & (
                pd.to_datetime(df_m["match_date"]).dt.date.between(start_date, end_date)
            )
            df_m = df_m.loc[mask]
        all_rows.append(df_m)

    df = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if df.empty:
        return df

    # Si no te pasan comp/season, infiérelos de la página/URL
    if not comp_slug or not season_slug:
        comp_slug, season_slug = infer_comp_season(url, driver)

    # Carpeta consolidada sin subcarpetas de rango
    base_comp_season = out_root / "DataFixtures" / comp_slug / season_slug
    base_comp_season.mkdir(parents=True, exist_ok=True)
    run_dir = base_comp_season

    # Enriquecer hora y aplicar overrides de jornada
    df = enrich_start_time(driver, df)
    df = apply_round_overrides(df, base_comp_season / "round_overrides.csv")

    # Guardado SIEMPRE con el mismo nombre
    csv_path  = run_dir / "finished_matches.csv"
    json_path = run_dir / "finished_matches.json"

    df_csv = df.copy()
    wanted = [
        "match_date","start_time","home_name","away_name","match_id",
        "match_centre_url","score_home","score_away","is_finished","match_round"
    ]
    df_csv = df_csv[[c for c in wanted if c in df_csv.columns]]

    df_final = append_dedup_csv(df_csv, csv_path, key="match_id")
    if save_json:
        to_json_records(df, json_path)

    return df_final