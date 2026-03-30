"""
angel_client.py — AngelOne SmartAPI wrapper
============================================
Replaces ALL yfinance calls in scanner.py and trade_manager.py.

Setup:
  Set these environment variables (or edit the defaults below):
    ANGEL_API_KEY      → your AngelOne API key
    ANGEL_CLIENT_ID    → your client ID / login ID
    ANGEL_PASSWORD     → your login password
    ANGEL_TOTP_SECRET  → your TOTP secret (from AngelOne app 2FA setup)

Install:
  pip install smartapi-python pyotp
"""

import os
import pyotp
import pandas as pd
from datetime import datetime, timedelta
from SmartApi import SmartConnect

# ═══════════════════════════════════════════════════════════════
#  CREDENTIALS — set as environment variables or hardcode here
# ═══════════════════════════════════════════════════════════════
API_KEY     = os.environ.get("ANGEL_API_KEY",     "your_api_key")
CLIENT_ID   = os.environ.get("ANGEL_CLIENT_ID",   "your_client_id")
PASSWORD    = os.environ.get("ANGEL_PASSWORD",     "your_password")
TOTP_SECRET = os.environ.get("ANGEL_TOTP_SECRET", "your_totp_secret")


# ═══════════════════════════════════════════════════════════════
#  SYMBOL → TOKEN MAP  (NSE tokens for Nifty 200 stocks)
# ═══════════════════════════════════════════════════════════════
# Angel One uses numeric tokens instead of ticker symbols.
# To get the full updated list, download the instrument master:
# https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
# Filter: exch_seg == "NSE" and symbol == your stock name

SYMBOL_TOKEN_MAP = {
    # ── Index ────────────────────────────────────────────────
    "NIFTY":       "99926000",   # Nifty 50 index

    # ── Nifty 200 stocks ─────────────────────────────────────
    "RELIANCE":    "2885",
    "HDFCBANK":    "1333",
    "INFY":        "1594",
    "ICICIBANK":   "4963",
    "TCS":         "11536",
    "SBIN":        "3045",
    "BHARTIARTL":  "10604",
    "WIPRO":       "3787",
    "AXISBANK":    "5900",
    "SUNPHARMA":   "3351",
    "TATAMOTORS":  "3456",
    "ADANIPORTS":  "15083",
    "POLYCAB":     "19843",
    "SIEMENS":     "3150",
    "ABB":         "13",
    "HINDALCO":    "1363",
    "TATASTEEL":   "3408",
    "COALINDIA":   "20374",
    "ONGC":        "2475",
    "NTPC":        "11630",
    "POWERGRID":   "14977",
    "BAJFINANCE":  "317",
    "BAJAJFINSV":  "16675",
    "MARUTI":      "10999",
    "TITAN":       "3506",
    "NESTLEIND":   "17963",
    "BRITANNIA":   "547",
    "ASIANPAINT":  "236",
    "PIDILITIND":  "2664",
    "BERGEPAINT":  "404",
    "APOLLOHOSP":  "157",
    "DRREDDY":     "881",
    "CIPLA":       "694",
    "DIVISLAB":    "10940",
    "LTIM":        "17818",
    "HCLTECH":     "7229",
    "TECHM":       "13538",
    "MPHASIS":     "4503",
    "COFORGE":     "11543",
    "ADANIPOWER":  "467",
    "TATAPOWER":   "3426",
    "TORNTPOWER":  "19913",
    "NHPC":        "20797",
    "INDUSINDBK":  "5258",
    "FEDERALBNK":  "1023",
    "AUBANK":      "21238",
    "IDFCFIRSTB":  "11184",
    "VOLTAS":      "3718",
    "CUMMINSIND":  "1901",
    "HAVELLS":     "9819",
    "IRCTC":       "13611",
    "CHOLAFIN":    "685",
    "MUTHOOTFIN":  "19234",
    "LTTS":        "18564",
    "PERSISTENT":  "18365",
    "TATACOMM":    "3419",
    "MOTHERSON":   "4204",
    "BOSCHLTD":    "529",
    "MRF":         "2277",
    "APOLLOTYRE":  "163",
    "HEROMOTOCO":  "1348",
    "EICHERMOT":   "910",
    "BALKRISIND":  "335",
    "JSWSTEEL":    "11723",
    "SAIL":        "2963",
    "NATIONALUM":  "2615",
    "VEDL":        "3063",
    "NMDC":        "15332",
    "GAIL":        "1098",
    "IOC":         "1624",
    "BPCL":        "526",
    "HPCL":        "1279",
    "TATACONSUM":  "3432",
    "GODREJCP":    "10099",
    "DABUR":       "772",
    "MARICO":      "4067",
    "COLPAL":      "718",
    "EMAMILTD":    "7277",
    "MCDOWELL-N":  "4506",
    "UBL":         "13706",
    "OBEROIRLTY":  "20242",
    "GODREJPROP":  "17875",
    "DLF":         "14732",
    "PRESTIGE":    "21336",
    "BRIGADE":     "4488",
    "INDIGO":      "11195",
    "CONCOR":      "4749",
    "RVNL":        "19301",
    "IRFC":        "20671",
    "KOTAKBANK":   "1922",
    "LT":          "11483",
    "M&M":         "2031",
    "BAJAJ-AUTO":  "16669",
    "GRASIM":      "1232",
    "TRENT":       "1964",
    "PAGEIND":     "14413",
    "BATAINDIA":   "371",
    "PHOENIXLTD":  "5101",
    "TORNTPHARM":  "3518",
    "ALKEM":       "19901",
    "VBL":         "19564",
    "SBICARD":     "21316",
    "HDFCAMC":     "19574",
    "CANFINHOME":  "18815",
    "MANAPPURAM":  "19819",
    "KPITTECH":    "21742",
    "TATAELXSI":   "3457",
    "CYIENT":      "1455",
    "BEL":         "383",
    "HAL":         "2303",
    "KEC":         "1873",
    "THERMAX":     "3480",
    "BHEL":        "438",
    "LAURUS":      "19234",
    "GLENMARK":    "1209",
    "IPCALAB":     "1618",
    "AJANTPHARM":  "20529",
    "NATCOPHARM":  "13553",
    "GRANULES":    "20908",
    "MANKIND":     "20241",
    "HDFCLIFE":    "467",
    "SBILIFE":     "21808",
    "ICICIGI":     "18652",
    "UTIAMC":      "20625",
    "NIPPONEAMC":  "21770",
    "PNBHOUSING":  "14978",
    "LICHSGFIN":   "1997",
    "RBLBANK":     "4503",
    "BANDHANBNK":  "17818",
    "SOBHA":       "14604",
    "MAHINDCIE":   "7493",
    "BLUESTARCO":  "488",
    "WHIRLPOOL":   "4752",
    "CROMPTON":    "17094",
    "ORIENTELEC":  "2532",
    "VGUARD":      "18027",
    "AMBER":       "21082",
    "DIXONTECH":   "20852",
    "RAILTEL":     "20560",
    "TIINDIA":     "21046",
    "SONACOMS":    "20999",
    "CRAFTSMAN":   "21302",
    "ENDURANCE":   "20966",
    "SPICEJET":    "3229",
    "BAJAJHFL":    "16675",
    "PAYTM":       "21048",
    "NYKAA":       "21090",
    "ZOMATO":      "20809",
    "DMART":       "19916",
}

# ═══════════════════════════════════════════════════════════════
#  SINGLETON SESSION
# ═══════════════════════════════════════════════════════════════
_smart_api = None


def get_smart_api() -> SmartConnect:
    """
    Returns an authenticated SmartConnect session.
    Authenticates once and reuses the session (singleton pattern).
    """
    global _smart_api
    if _smart_api is not None:
        return _smart_api

    obj   = SmartConnect(api_key=API_KEY)
    totp  = pyotp.TOTP(TOTP_SECRET).now()
    session = obj.generateSession(CLIENT_ID, PASSWORD, totp)

    if not session or session.get("status") is False:
        raise RuntimeError(f"Angel One login failed: {session}")

    _smart_api = obj
    print("  ✅ Angel One authenticated successfully")
    return _smart_api


# ═══════════════════════════════════════════════════════════════
#  CANDLE DATA  (replaces yf.download)
# ═══════════════════════════════════════════════════════════════
def get_candle_data(symbol: str,
                    exchange: str = "NSE",
                    interval: str = "ONE_DAY",
                    days: int = 730) -> pd.DataFrame:
    """
    Fetch OHLCV candle data from Angel One SmartAPI.

    Parameters
    ----------
    symbol   : NSE symbol e.g. "RELIANCE", "HDFCBANK", "NIFTY"
    exchange : "NSE" for equities and indices
    interval : "ONE_DAY" | "ONE_WEEK" | "ONE_HOUR" | "FIFTEEN_MINUTE" etc.
    days     : Number of calendar days of history to fetch

    Returns
    -------
    pd.DataFrame with columns [Open, High, Low, Close, Volume]
    Index = DatetimeIndex (tz-naive)
    """
    smart = get_smart_api()

    token = SYMBOL_TOKEN_MAP.get(symbol)
    if token is None:
        raise ValueError(
            f"Token not found for symbol '{symbol}'. "
            f"Add it to SYMBOL_TOKEN_MAP in angel_client.py"
        )

    to_date   = datetime.now()
    from_date = to_date - timedelta(days=days)

    params = {
        "exchange":    exchange,
        "symboltoken": token,
        "interval":    interval,
        "fromdate":    from_date.strftime("%Y-%m-%d %H:%M"),
        "todate":      to_date.strftime("%Y-%m-%d %H:%M"),
    }

    resp = smart.getCandleData(params)

    if not resp or resp.get("status") is False or not resp.get("data"):
        raise RuntimeError(
            f"Candle data fetch failed for {symbol}: {resp}"
        )

    # Angel One returns: [timestamp, open, high, low, close, volume]
    rows = resp["data"]
    df = pd.DataFrame(
        rows,
        columns=["Datetime", "Open", "High", "Low", "Close", "Volume"]
    )
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    df.set_index("Datetime", inplace=True)
    df = df.astype(float)
    df.index = df.index.tz_localize(None)   # remove tz info to match yfinance behaviour
    df.sort_index(inplace=True)
    df.dropna(inplace=True)

    return df


# ═══════════════════════════════════════════════════════════════
#  LTP (Last Traded Price)  (replaces yf.download for current price)
# ═══════════════════════════════════════════════════════════════
def get_ltp(symbol: str, exchange: str = "NSE") -> dict:
    """
    Get last traded price, day high, and day low for a symbol.

    Parameters
    ----------
    symbol   : NSE symbol e.g. "RELIANCE"
    exchange : "NSE"

    Returns
    -------
    dict with keys: "ltp" (float), "high" (float), "low" (float)
    """
    smart = get_smart_api()

    token = SYMBOL_TOKEN_MAP.get(symbol)
    if token is None:
        raise ValueError(
            f"Token not found for symbol '{symbol}'. "
            f"Add it to SYMBOL_TOKEN_MAP in angel_client.py"
        )

    resp = smart.ltpData(exchange, symbol, token)

    if not resp or resp.get("status") is False:
        raise RuntimeError(f"LTP fetch failed for {symbol}: {resp}")

    data = resp.get("data", {})
    return {
        "ltp":  float(data.get("ltp",  0)),
        "high": float(data.get("high", 0)),
        "low":  float(data.get("low",  0)),
    }
