"""Uygulama yolları, lig sözlüğü ve veri kaynakları."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MODELS_DIR = ROOT / "models"
WEB_DIR = ROOT / "web"
FANTASY_ROOT = Path(os.environ.get("FANTASY_ROOT") or r"C:\Users\Arda\Desktop\Apps\Fantezi Ligi")
FANTASY_CACHE = DATA_DIR / "fantasy_last.json"

DATASET_BASE = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
HF_DATASET = "https://huggingface.co/datasets/ngeorgea/transfermarkt-player-scores/resolve/main"
TM_API_BASE = "https://transfermarkt-api.fly.dev"
TM_WEB = "https://www.transfermarkt.com"

PLAYERS_CSV = RAW_DIR / "players.csv"
CLUBS_CSV = RAW_DIR / "clubs.csv"
COMPETITIONS_CSV = RAW_DIR / "competitions.csv"
APPEARANCES_CSV = RAW_DIR / "appearances.csv"

PLAYERS_PARQUET = DATA_DIR / "players.parquet"
STATS_PARQUET = DATA_DIR / "player_stats.parquet"
UNIVERSE_PARQUET = DATA_DIR / "universe.parquet"
ENGINE_PATH = MODELS_DIR / "engine.joblib"
META_PATH = MODELS_DIR / "meta.json"
CACHE_SQLITE = DATA_DIR / "cache.sqlite"

ACTIVE_SEASON_FLOOR = 2023
MIN_VALUE_EUR = 50_000

FEATURED_LEAGUES = (
    "GB1",
    "ES1",
    "IT1",
    "L1",
    "FR1",
    "NL1",
    "PO1",
    "BE1",
    "TR1",
    "SA1",
)

CATALOG_LEAGUES = (
    "GB1",
    "ES1",
    "IT1",
    "L1",
    "FR1",
    "NL1",
    "PO1",
    "BE1",
    "TR1",
    "SC1",
    "A1",
    "C1",
    "DK1",
    "GR1",
    "PL1",
    "RU1",
    "UKR1",
    "TS1",
    "RO1",
    "SER1",
    "KR1",
    "SE1",
    "NO1",
    "BRA1",
    "ARG1",
    "MLS1",
    "MEX1",
    "COL1",
    "SA1",
    "JAP1",
    "RSK1",
    "AUS1",
)

TOP_LEAGUES = CATALOG_LEAGUES

LEAGUE_TIER = {
    "GB1": 1,
    "ES1": 1,
    "L1": 1,
    "IT1": 1,
    "FR1": 1,
    "NL1": 2,
    "PO1": 2,
    "BE1": 2,
    "TR1": 2,
    "SC1": 2,
    "A1": 2,
    "C1": 2,
    "DK1": 2,
    "GR1": 2,
    "PL1": 2,
    "RU1": 2,
    "UKR1": 2,
    "TS1": 3,
    "RO1": 3,
    "SER1": 3,
    "KR1": 3,
    "SE1": 3,
    "NO1": 3,
    "BRA1": 2,
    "ARG1": 2,
    "MLS1": 2,
    "MEX1": 2,
    "COL1": 3,
    "SA1": 2,
    "JAP1": 3,
    "RSK1": 3,
    "AUS1": 3,
    "BR1": 2,
    "AR1N": 2,
    "UA1": 2,
    "CZ1": 3,
    "HR1": 3,
    "RS1": 3,
    "JP1": 3,
}

LEAGUE_NAMES = {
    "GB1": "Premier League",
    "ES1": "LaLiga",
    "L1": "Bundesliga",
    "IT1": "Serie A",
    "FR1": "Ligue 1",
    "NL1": "Eredivisie",
    "PO1": "Liga Portugal",
    "BE1": "Pro League",
    "TR1": "Süper Lig",
    "SC1": "Scottish Premiership",
    "A1": "Bundesliga (Avusturya)",
    "C1": "Super League",
    "DK1": "Superliga",
    "GR1": "Super League (Yunanistan)",
    "PL1": "Ekstraklasa",
    "RU1": "Premier Lig (Rusya)",
    "UKR1": "Premier Lig (Ukrayna)",
    "TS1": "Chance Liga",
    "RO1": "Superliga (Romanya)",
    "SER1": "Süper Liga (Sırbistan)",
    "KR1": "HNL",
    "SE1": "Allsvenskan",
    "NO1": "Eliteserien",
    "BRA1": "Brasileirão",
    "ARG1": "Liga Profesional",
    "MLS1": "MLS",
    "MEX1": "Liga MX",
    "COL1": "Liga BetPlay",
    "SA1": "Suudi Pro Lig",
    "JAP1": "J1 League",
    "RSK1": "K League 1",
    "AUS1": "A-League",
}

LEAGUE_REGION = {
    "GB1": "Batı Avrupa",
    "ES1": "Batı Avrupa",
    "IT1": "Batı Avrupa",
    "L1": "Batı Avrupa",
    "FR1": "Batı Avrupa",
    "NL1": "Batı Avrupa",
    "PO1": "Batı Avrupa",
    "BE1": "Batı Avrupa",
    "SC1": "Batı Avrupa",
    "A1": "Batı Avrupa",
    "C1": "Batı Avrupa",
    "DK1": "Batı Avrupa",
    "TR1": "Doğu Avrupa",
    "GR1": "Doğu Avrupa",
    "PL1": "Doğu Avrupa",
    "RU1": "Doğu Avrupa",
    "UKR1": "Doğu Avrupa",
    "TS1": "Doğu Avrupa",
    "RO1": "Doğu Avrupa",
    "SER1": "Doğu Avrupa",
    "KR1": "Doğu Avrupa",
    "SE1": "İskandinavya",
    "NO1": "İskandinavya",
    "BRA1": "Amerika",
    "ARG1": "Amerika",
    "MLS1": "Amerika",
    "MEX1": "Amerika",
    "COL1": "Amerika",
    "SA1": "Asya",
    "JAP1": "Asya",
    "RSK1": "Asya",
    "AUS1": "Asya",
}

REGION_ORDER = (
    "Batı Avrupa",
    "Doğu Avrupa",
    "İskandinavya",
    "Amerika",
    "Asya",
)

TIER_LABEL = {
    1: "Birinci kademe",
    2: "İkinci kademe",
    3: "Üçüncü kademe",
    4: "Dış lig",
}

LEAGUE_COUNTRY = {
    "GB1": "İngiltere",
    "ES1": "İspanya",
    "IT1": "İtalya",
    "L1": "Almanya",
    "FR1": "Fransa",
    "NL1": "Hollanda",
    "PO1": "Portekiz",
    "BE1": "Belçika",
    "TR1": "Türkiye",
    "SC1": "İskoçya",
    "A1": "Avusturya",
    "C1": "İsviçre",
    "DK1": "Danimarka",
    "GR1": "Yunanistan",
    "PL1": "Polonya",
    "RU1": "Rusya",
    "UKR1": "Ukrayna",
    "TS1": "Çekya",
    "RO1": "Romanya",
    "SER1": "Sırbistan",
    "KR1": "Hırvatistan",
    "SE1": "İsveç",
    "NO1": "Norveç",
    "BRA1": "Brezilya",
    "ARG1": "Arjantin",
    "MLS1": "ABD",
    "MEX1": "Meksika",
    "COL1": "Kolombiya",
    "SA1": "Suudi Arabistan",
    "JAP1": "Japonya",
    "RSK1": "Güney Kore",
    "AUS1": "Avustralya",
}

LEAGUE_FLAG = {
    "GB1": "gb",
    "ES1": "es",
    "IT1": "it",
    "L1": "de",
    "FR1": "fr",
    "NL1": "nl",
    "PO1": "pt",
    "BE1": "be",
    "TR1": "tr",
    "SC1": "gb-sct",
    "A1": "at",
    "C1": "ch",
    "DK1": "dk",
    "GR1": "gr",
    "PL1": "pl",
    "RU1": "ru",
    "UKR1": "ua",
    "TS1": "cz",
    "RO1": "ro",
    "SER1": "rs",
    "KR1": "hr",
    "SE1": "se",
    "NO1": "no",
    "BRA1": "br",
    "ARG1": "ar",
    "MLS1": "us",
    "MEX1": "mx",
    "COL1": "co",
    "SA1": "sa",
    "JAP1": "jp",
    "RSK1": "kr",
    "AUS1": "au",
}

LEAGUE_MARK = {
    "GB1": "ENG",
    "ES1": "ESP",
    "IT1": "ITA",
    "L1": "GER",
    "FR1": "FRA",
    "NL1": "NED",
    "PO1": "POR",
    "BE1": "BEL",
    "TR1": "TUR",
    "SC1": "SCO",
    "A1": "AUT",
    "C1": "SUI",
    "DK1": "DEN",
    "GR1": "GRE",
    "PL1": "POL",
    "RU1": "RUS",
    "UKR1": "UKR",
    "TS1": "CZE",
    "RO1": "ROU",
    "SER1": "SRB",
    "KR1": "CRO",
    "SE1": "SWE",
    "NO1": "NOR",
    "BRA1": "BRA",
    "ARG1": "ARG",
    "MLS1": "USA",
    "MEX1": "MEX",
    "COL1": "COL",
    "SA1": "KSA",
    "JAP1": "JPN",
    "RSK1": "KOR",
    "AUS1": "AUS",
}

POSITION_TR = {
    "Goalkeeper": "Kaleci",
    "Defender": "Defans",
    "Midfield": "Orta saha",
    "Attack": "Forvet",
}

SUB_POSITION_TR = {
    "Goalkeeper": "Kaleci",
    "Centre-Back": "Stoper",
    "Left-Back": "Sol bek",
    "Right-Back": "Sağ bek",
    "Defensive Midfield": "Defansif orta saha",
    "Central Midfield": "Merkez orta saha",
    "Attacking Midfield": "Ofansif orta saha",
    "Left Midfield": "Sol kanat orta saha",
    "Right Midfield": "Sağ kanat orta saha",
    "Left Winger": "Sol kanat",
    "Right Winger": "Sağ kanat",
    "Centre-Forward": "Santrafor",
    "Second Striker": "İkinci forvet",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
