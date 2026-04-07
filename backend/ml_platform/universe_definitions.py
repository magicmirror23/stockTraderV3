"""Versioned universe definitions and symbol tagging."""

from __future__ import annotations

from typing import Iterable

try:
    from backend.services.advanced_risk import SECTOR_MAP as _RISK_SECTOR_MAP
except Exception:  # pragma: no cover - defensive import fallback
    _RISK_SECTOR_MAP = {}


def _ordered_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        sym = str(raw).strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


# Current baseline list + 2 additional liquid large-caps => 52 symbols.
UNIVERSE_V1_CURRENT_52: list[str] = _ordered_unique(
    [
        "RELIANCE",
        "TCS",
        "HDFCBANK",
        "INFY",
        "ICICIBANK",
        "HINDUNILVR",
        "SBIN",
        "BHARTIARTL",
        "KOTAKBANK",
        "LT",
        "AXISBANK",
        "ITC",
        "BAJFINANCE",
        "ASIANPAINT",
        "MARUTI",
        "HCLTECH",
        "TITAN",
        "SUNPHARMA",
        "WIPRO",
        "ULTRACEMCO",
        "NESTLEIND",
        "BANKBARODA",
        "POWERGRID",
        "NTPC",
        "ONGC",
        "JSWSTEEL",
        "TATASTEEL",
        "ADANIPORTS",
        "TECHM",
        "INDUSINDBK",
        "BAJAJFINSV",
        "GRASIM",
        "CIPLA",
        "HDFCLIFE",
        "DRREDDY",
        "COALINDIA",
        "DIVISLAB",
        "BRITANNIA",
        "EICHERMOT",
        "APOLLOHOSP",
        "SBILIFE",
        "BPCL",
        "HEROMOTOCO",
        "TATACONSUM",
        "UPL",
        "HINDALCO",
        "BAJAJ_AUTO",
        "SHREECEM",
        "VEDL",
        "M_M",
        "ADANIENT",
        "TATAMOTORS",
    ]
)


# Curated high-liquidity India equity pool used to derive v2/v3/v4 universes.
CURATED_NIFTY_200_POOL: list[str] = _ordered_unique(
    [
        "ADANIGREEN",
        "ADANIPOWER",
        "AMBUJACEM",
        "ABB",
        "ACC",
        "AUROPHARMA",
        "BHEL",
        "BOSCHLTD",
        "CANBK",
        "CHOLAFIN",
        "DABUR",
        "DLF",
        "DMART",
        "GAIL",
        "GODREJCP",
        "HAL",
        "HAVELLS",
        "ICICIPRULI",
        "IDFCFIRSTB",
        "INDIGO",
        "IOC",
        "JINDALSTEL",
        "LUPIN",
        "MOTHERSON",
        "NAUKRI",
        "OBEROIRLTY",
        "PATANJALI",
        "PFC",
        "PIDILITIND",
        "POLYCAB",
        "RECLTD",
        "SIEMENS",
        "SRF",
        "TVSMOTOR",
        "UNIONBANK",
        "VOLTAS",
        "ZYDUSLIFE",
        "ASHOKLEY",
        "MUTHOOTFIN",
        "BERGEPAINT",
        "BANDHANBNK",
        "BIOCON",
        "COLPAL",
        "CONCOR",
        "CUMMINSIND",
        "ESCORTS",
        "FEDERALBNK",
        "GLAND",
        "ABCAPITAL",
        "ABFRL",
        "ALKEM",
        "APLAPOLLO",
        "ASTRAL",
        "AUBANK",
        "BALKRISIND",
        "BATAINDIA",
        "BEL",
        "BHARATFORG",
        "CANFINHOME",
        "COROMANDEL",
        "DEEPAKNTR",
        "DELHIVERY",
        "DIXON",
        "EIDPARRY",
        "EMAMILTD",
        "EXIDEIND",
        "FORTIS",
        "FSL",
        "GUJGASLTD",
        "HINDPETRO",
        "IPCALAB",
        "IRCTC",
        "JUBLFOOD",
        "LAURUSLABS",
        "LICHSGFIN",
        "LTIM",
        "LALPATHLAB",
        "MARICO",
        "MCX",
        "METROPOLIS",
        "MPHASIS",
        "NAM_INDIA",
        "NMDC",
        "OFSS",
        "PAGEIND",
        "PERSISTENT",
        "PETRONET",
        "PIIND",
        "RAMCOCEM",
        "SAIL",
        "SYNGENE",
        "TATACHEM",
        "TATAPOWER",
        "TRENT",
        "WHIRLPOOL",
        "ZEEL",
        "INDHOTEL",
        "AARTIIND",
        "AJANTPHARM",
        "APLLTD",
        "ATUL",
        "BALRAMCHIN",
        "BLUEDART",
        "CAMPUS",
        "CDSL",
        "CENTURYTEX",
        "COFORGE",
        "CROMPTON",
        "DELTACORP",
        "EQUITASBNK",
        "ERIS",
        "FINEORG",
        "GMRINFRA",
        "GODREJIND",
        "GRINDWELL",
        "HFCL",
        "HONAUT",
        "HUDCO",
        "IEX",
        "IGL",
        "INDIAMART",
        "INOXWIND",
        "JBCHEPHARM",
        "JSWENERGY",
        "KEI",
        "KFINTECH",
        "LINDEIND",
        "MAHLOG",
        "MANKIND",
        "MAZDOCK",
        "NAVINFLUOR",
        "NCC",
        "NHPC",
        "OIL",
        "PAYTM",
        "PEL",
        "PHOENIXLTD",
        "PNB",
        "RBLBANK",
        "SBICARD",
        "SCHAEFFLER",
        "SKFINDIA",
        "SOLARINDS",
        "SONACOMS",
        "SUZLON",
        "TATATECH",
        "TRIDENT",
        "ABBOTINDIA",
        "ADANIWILMAR",
        "AKZOINDIA",
        "AMBER",
        "ANANDRATHI",
        "ANGELONE",
        "ASTERDM",
        "AWL",
        "BASF",
        "BAYERCROP",
        "BDL",
        "BEML",
        "BLS",
        "BLUESTARCO",
        "CARBORUNIV",
        "CASTROLIND",
        "CEATLTD",
        "CHENNPETRO",
        "CLEAN",
        "COCHINSHIP",
        "CYIENT",
        "DALBHARAT",
        "DATAPATTNS",
        "DEEPAKFERT",
        "DOMS",
        "ELGIEQUIP",
        "FIVE_STAR",
        "GICRE",
        "GILLETTE",
        "HAPPSTMNDS",
        "HATSUN",
        "HINDCOPPER",
        "HINDZINC",
        "IFBIND",
        "INDUSTOWER",
        "INTELLECT",
        "JMFINANCIL",
        "JUSTDIAL",
        "KAYNES",
        "KPITTECH",
        "LTFOODS",
        "MAPMYINDIA",
        "MASTEK",
        "MINDACORP",
        "NATCOPHARM",
        "NLCINDIA",
        "NYKAA",
        "OLECTRA",
        "PCBL",
        "PNCINFRA",
        "RADICO",
        "RAILTEL",
        "RATNAMANI",
        "ROUTE",
        "SAPPHIRE",
        "SAREGAMA",
        "SBFC",
        "SHOPERSTOP",
        "SUPREMEIND",
        "TANLA",
        "TIINDIA",
        "TIMKEN",
        "VGUARD",
        "WELSPUNLIV",
        "ZENSARTECH",
    ]
)


def _build_universe_versions() -> dict[str, list[str]]:
    combined = _ordered_unique(UNIVERSE_V1_CURRENT_52 + CURATED_NIFTY_200_POOL)
    targets = {
        "universe_v1": 52,
        "universe_v2": 100,
        "universe_v3": 150,
        "universe_v4": 200,
    }
    versions: dict[str, list[str]] = {}
    for name, target in targets.items():
        if len(combined) < target:
            raise ValueError(f"Universe pool too small for {name} target={target}")
        if name == "universe_v1":
            versions[name] = UNIVERSE_V1_CURRENT_52[:]
        else:
            versions[name] = combined[:target]
    return versions


UNIVERSE_VERSION_SYMBOLS: dict[str, list[str]] = _build_universe_versions()

UNIVERSE_LABELS: dict[str, str] = {
    "universe_v1": "Current 52",
    "universe_v2": "Curated Liquid Nifty 100",
    "universe_v3": "Curated Liquid Nifty 150",
    "universe_v4": "Curated Liquid Nifty 200",
}


_EXTRA_SECTOR_MAP: dict[str, str] = {
    "ADANIGREEN": "Utilities",
    "ADANIPOWER": "Utilities",
    "AMBUJACEM": "Infrastructure",
    "ABB": "Capital Goods",
    "ACC": "Infrastructure",
    "AUROPHARMA": "Pharma",
    "BHEL": "Capital Goods",
    "BOSCHLTD": "Auto",
    "CANBK": "Banking",
    "CHOLAFIN": "Finance",
    "DABUR": "FMCG",
    "DLF": "Real Estate",
    "DMART": "Consumer",
    "HAL": "Defense",
    "HAVELLS": "Capital Goods",
    "ICICIPRULI": "Finance",
    "IDFCFIRSTB": "Banking",
    "INDIGO": "Transport",
    "JINDALSTEL": "Metals",
    "LUPIN": "Pharma",
    "MOTHERSON": "Auto",
    "NAUKRI": "Internet",
    "OBEROIRLTY": "Real Estate",
    "PFC": "Finance",
    "RECLTD": "Finance",
    "TVSMOTOR": "Auto",
    "UNIONBANK": "Banking",
    "ZYDUSLIFE": "Pharma",
    "INDHOTEL": "Consumer",
    "IEX": "Exchange",
    "CDSL": "Exchange",
    "MCX": "Exchange",
    "PAYTM": "Internet",
    "NYKAA": "Consumer",
    "TATATECH": "IT",
}


SECTOR_TAGS: dict[str, str] = {}
for key, value in _RISK_SECTOR_MAP.items():
    normalized_key = str(key).replace("-", "_").replace("&", "_").upper()
    SECTOR_TAGS[normalized_key] = value
for key, value in _EXTRA_SECTOR_MAP.items():
    SECTOR_TAGS[key.upper()] = value

INDUSTRY_GROUP_BY_SECTOR: dict[str, str] = {
    "Banking": "Financial Services",
    "Finance": "Financial Services",
    "IT": "Technology",
    "Internet": "Technology",
    "Oil & Gas": "Energy",
    "Utilities": "Energy",
    "Pharma": "Healthcare",
    "FMCG": "Consumer Staples",
    "Consumer": "Consumer Discretionary",
    "Auto": "Automobile",
    "Metals": "Materials",
    "Infrastructure": "Industrials",
    "Capital Goods": "Industrials",
    "Defense": "Industrials",
    "Real Estate": "Real Estate",
    "Transport": "Transportation",
    "Exchange": "Financial Infrastructure",
}


def get_universe_candidates(version: str) -> list[str]:
    key = str(version or "").strip().lower()
    if key not in UNIVERSE_VERSION_SYMBOLS:
        raise KeyError(f"Unknown universe version: {version}")
    return UNIVERSE_VERSION_SYMBOLS[key][:]


def get_symbol_tags(symbol: str) -> dict[str, str]:
    sym = str(symbol).strip().upper().replace("-", "_").replace("&", "_")
    sector = SECTOR_TAGS.get(sym, "Unknown")
    industry_group = INDUSTRY_GROUP_BY_SECTOR.get(sector, "Unknown")
    return {"sector": sector, "industry_group": industry_group}
