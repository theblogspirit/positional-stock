"""
scanner.py — VCP Live Scanner (AngelOne API Edition)
=====================================================
Identical logic to the original scanner_v2.py with one change:
  - yfinance REMOVED
  - AngelOne SmartAPI used for all market data

Improvements retained from v2:
  1. Dynamic ADX based on market regime
  2. NEUTRAL regime blocked
  3. Choppy market detection (EMA50 slope)
  4. RSI 65-70 danger zone blocked
  5. MIN_SCORE = 13

Run: python scanner.py
"""

import pandas as pd
import pandas_ta as ta
import time, io, requests, warnings
from datetime import datetime
warnings.filterwarnings("ignore")

# ── AngelOne data client (replaces yfinance) ─────────────────
from angel_client import get_candle_data

from telegram_bot import send_entry_alert, send_no_signal_alert
from trade_manager import add_trade


# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════

# ── Signal quality ───────────────────────────────────────────
MIN_SCORE         = 13.0    # only 66-70% WR setups qualify

# ── Trade management ─────────────────────────────────────────
MAX_HOLD_DAYS     = 70
ATR_MULTIPLIER_SL = 2.5
RR_RATIO_T1       = 2.5
RR_RATIO_T2       = 5.0
MAX_RISK_PCT      = 0.11

# ── Liquidity ────────────────────────────────────────────────
LIQUIDITY_MIN_CR  = 5

# ── VCP filters ──────────────────────────────────────────────
VCP_VOL_MIN       = 2.0
VCP_BASE_DAYS     = 7
VCP_BASE_RANGE    = 0.12
VCP_BASE_MIN      = 0.05
VCP_VOL_DRYUP     = 0.90
VCP_RSI_MIN       = 45
VCP_RSI_MAX       = 75
MAX_RUN_60D       = 0.40
MIN_RS_VS_NIFTY   = 0.00

# ── Dynamic ADX ──────────────────────────────────────────────
ADX_STRONG_BULL   = 28      # stricter in strong bull (73% WR)
ADX_BULLISH       = 25      # standard in normal bull

# ── Choppy detection ─────────────────────────────────────────
EMA50_SLOPE_MIN   = 0.3     # EMA50 must move >0.3% over 10 days

# ── Capital ──────────────────────────────────────────────────
CAPITAL           = 100_000
RISK_PER_TRADE    = 0.04    # 4% risk = ₹4,000 per trade


# ═══════════════════════════════════════════════════════════════
#  UNIVERSE  (plain NSE symbols — no .NS suffix for Angel One)
# ═══════════════════════════════════════════════════════════════
def fetch_nifty200():
    """
    Fetches live Nifty 200 list from NSE.
    Returns plain symbols (e.g. "RELIANCE") for AngelOne API.
    Falls back to hardcoded list if NSE fetch fails.
    """
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer":    "https://www.nseindia.com/",
    }
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(1)
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code == 200 and len(r.content) > 500:
            df      = pd.read_csv(io.StringIO(r.content.decode("utf-8")))
            # Angel One uses plain symbols — NO .NS suffix
            symbols = [str(row["Symbol"]).strip() for _, row in df.iterrows()]
            print(f"  Live Nifty 200 fetched: {len(symbols)} stocks")
            return symbols
    except Exception as e:
        print(f"  NSE fetch failed ({e}), using fallback list")

    # Fallback list — plain symbols (no .NS)
    return [
        "RELIANCE","HDFCBANK","INFY","ICICIBANK","TCS",
        "SBIN","BHARTIARTL","WIPRO","AXISBANK","SUNPHARMA",
        "TATAMOTORS","ADANIPORTS","POLYCAB","SIEMENS","ABB",
        "HINDALCO","TATASTEEL","COALINDIA","ONGC","NTPC",
        "POWERGRID","BAJFINANCE","BAJAJFINSV","MARUTI","TITAN",
        "NESTLEIND","BRITANNIA","ASIANPAINT","PIDILITIND","BERGEPAINT",
        "APOLLOHOSP","DRREDDY","CIPLA","DIVISLAB","LTIM",
        "HCLTECH","TECHM","MPHASIS","COFORGE","ADANIPOWER",
        "TATAPOWER","TORNTPOWER","NHPC","INDUSINDBK","FEDERALBNK",
        "AUBANK","IDFCFIRSTB","VOLTAS","CUMMINSIND","HAVELLS",
        "IRCTC","CHOLAFIN","MUTHOOTFIN","LTTS","PERSISTENT",
        "TATACOMM","MOTHERSON","BOSCHLTD","MRF","APOLLOTYRE",
        "HEROMOTOCO","EICHERMOT","BALKRISIND","JSWSTEEL","SAIL",
        "NATIONALUM","VEDL","NMDC","GAIL","IOC",
        "BPCL","HPCL","TATACONSUM","GODREJCP","DABUR",
        "MARICO","COLPAL","EMAMILTD","MCDOWELL-N","UBL",
        "OBEROIRLTY","GODREJPROP","DLF","PRESTIGE","BRIGADE",
        "INDIGO","CONCOR","RVNL","IRFC","KOTAKBANK",
        "LT","M&M","BAJAJ-AUTO","GRASIM","TRENT",
        "PAGEIND","BATAINDIA","PHOENIXLTD","TORNTPHARM","ALKEM",
        "VBL","SBICARD","HDFCAMC","CANFINHOME","MANAPPURAM",
        "KPITTECH","TATAELXSI","CYIENT","BEL","HAL",
        "KEC","THERMAX","BHEL","LAURUS","GLENMARK",
        "IPCALAB","AJANTPHARM","NATCOPHARM","GRANULES","MANKIND",
        "HDFCLIFE","SBILIFE","ICICIGI","UTIAMC","NIPPONEAMC",
        "PNBHOUSING","LICHSGFIN","RBLBANK","BANDHANBNK",
        "SOBHA","MAHINDCIE","BLUESTARCO","WHIRLPOOL",
        "CROMPTON","ORIENTELEC","VGUARD","AMBER","DIXONTECH",
        "RAILTEL","TIINDIA","SONACOMS","CRAFTSMAN","ENDURANCE",
        "SPICEJET","BAJAJHFL","PAYTM","NYKAA","ZOMATO","DMART",
    ]


# ═══════════════════════════════════════════════════════════════
#  MARKET REGIME  (uses AngelOne instead of yfinance)
# ═══════════════════════════════════════════════════════════════
def get_market_regime():
    """
    Returns: (regime, nifty_r60, adx_threshold, ema50_val, ema200_val, price)

    Regimes:
      STRONG_BULL : Price > EMA50 > EMA200  AND  EMA50 rising  → ADX = 28
      BULLISH     : Price > EMA50  AND  EMA50 rising           → ADX = 25
      CHOPPY      : Price > EMA50  BUT  EMA50 slope is flat    → NO TRADES
      BEARISH     : Price < EMA50                              → NO TRADES
      NEUTRAL     : Default fallback                           → NO TRADES
    """
    try:
        # ── Fetch Nifty 50 data via AngelOne (symbol="NIFTY") ──
        nifty = get_candle_data("NIFTY", exchange="NSE", interval="ONE_DAY", days=730)

        if len(nifty) < 210:
            return "NEUTRAL", 0.0, ADX_BULLISH, 0, 0, 0

        close = nifty["Close"].squeeze().dropna()

        ema50      = ta.ema(close, 50)
        ema200     = ta.ema(close, 200)
        price      = float(close.iloc[-1])
        ema50_now  = float(ema50.iloc[-1])
        ema50_ago  = float(ema50.iloc[-11])   # 10 days ago
        ema200_now = float(ema200.iloc[-1])
        r60        = float((price / close.iloc[-60]) - 1)

        # EMA50 slope: % change over last 10 trading days
        ema50_slope = ((ema50_now - ema50_ago) / ema50_ago) * 100

        # ── Regime logic ─────────────────────────────────────
        if price < ema50_now:
            regime        = "BEARISH"
            adx_threshold = ADX_BULLISH

        elif abs(ema50_slope) < EMA50_SLOPE_MIN:
            regime        = "CHOPPY"
            adx_threshold = ADX_BULLISH

        elif price > ema50_now > ema200_now and ema50_slope > 0:
            regime        = "STRONG_BULL"
            adx_threshold = ADX_STRONG_BULL

        elif price > ema50_now and ema50_slope > 0:
            regime        = "BULLISH"
            adx_threshold = ADX_BULLISH

        else:
            regime        = "NEUTRAL"
            adx_threshold = ADX_BULLISH

        return regime, r60, adx_threshold, ema50_now, ema200_now, price

    except Exception as e:
        print(f"  Regime error: {e}")
        return "NEUTRAL", 0.0, ADX_BULLISH, 0, 0, 0


# ═══════════════════════════════════════════════════════════════
#  POSITION SIZE
# ═══════════════════════════════════════════════════════════════
def calculate_position(entry, sl):
    risk_per_share = entry - sl
    if risk_per_share <= 0:
        return 0, 0
    shares         = int((CAPITAL * RISK_PER_TRADE) / risk_per_share)
    position_value = shares * entry
    return shares, round(position_value, 0)


# ═══════════════════════════════════════════════════════════════
#  VCP SIGNAL DETECTION  (uses AngelOne instead of yfinance)
# ═══════════════════════════════════════════════════════════════
def detect_vcp_signal(symbol, market_trend, nifty_r60, adx_threshold):
    """
    symbol         : plain NSE symbol e.g. "RELIANCE"
    adx_threshold  : 28 in STRONG_BULL, 25 in BULLISH
    """
    try:
        # ── Fetch 3 years of daily OHLCV via AngelOne ────────
        df = get_candle_data(symbol, exchange="NSE", interval="ONE_DAY", days=1095)

        if df.empty or len(df) < 200:
            return None
        if any(c not in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
            return None
        df.index = pd.to_datetime(df.index)

        # ── Daily indicators ──────────────────────────────────
        df["EMA20"]     = ta.ema(df["Close"], 20)
        df["EMA50"]     = ta.ema(df["Close"], 50)
        df["EMA200"]    = ta.ema(df["Close"], 200)
        df["RSI"]       = ta.rsi(df["Close"], 14)
        df["ATR"]       = ta.atr(df["High"], df["Low"], df["Close"], 14)
        adx_df          = ta.adx(df["High"], df["Low"], df["Close"], 14)
        df              = pd.concat([df, adx_df], axis=1)
        df["OBV"]       = ta.obv(df["Close"], df["Volume"])
        df["OBV_EMA20"] = ta.ema(df["OBV"], 20)
        df["OBV_EMA50"] = ta.ema(df["OBV"], 50)
        df["AvgVol20"]  = df["Volume"].rolling(20).mean()
        df["AvgVol40"]  = df["Volume"].rolling(40).mean()
        df.dropna(inplace=True)

        if len(df) < 60:
            return None

        curr     = df.iloc[-1]
        adx_cols = [c for c in df.columns if "ADX_14" in c]
        if not adx_cols:
            return None

        adx_val   = float(curr[adx_cols[0]])
        rsi       = float(curr["RSI"])
        entry     = float(curr["Close"])
        ema20     = float(curr["EMA20"])
        ema50     = float(curr["EMA50"])
        ema200    = float(curr["EMA200"])
        avg_vol   = float(df["AvgVol20"].iloc[-2])
        vol_surge = float(curr["Volume"]) / avg_vol if avg_vol > 0 else 0

        # ── Weekly indicators ─────────────────────────────────
        weekly = df.resample("W").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
        if len(weekly) < 50:
            return None
        weekly["W_EMA20"]   = ta.ema(weekly["Close"], 20)
        weekly["W_EMA50"]   = ta.ema(weekly["Close"], 50)
        weekly["W_OBV"]     = ta.obv(weekly["Close"], weekly["Volume"])
        weekly["W_OBV_EMA"] = ta.ema(weekly["W_OBV"], 20)
        weekly.dropna(inplace=True)
        if len(weekly) < 5:
            return None

        w_curr   = weekly.iloc[-1]
        w_ema20  = float(w_curr["W_EMA20"])
        w_ema50  = float(w_curr["W_EMA50"])
        w_obv_up = float(w_curr["W_OBV"]) > float(w_curr["W_OBV_EMA"])

        # ══════════════════════════════════════════════════════
        #  FILTER BLOCK 1 — Trend & Liquidity
        # ══════════════════════════════════════════════════════
        if avg_vol * entry < LIQUIDITY_MIN_CR * 1e7:    return None
        if entry < ema200:                               return None
        if entry < w_ema50:                              return None
        if w_ema20 < w_ema50:                            return None

        # Dynamic ADX threshold (28 in STRONG_BULL, 25 in BULLISH)
        if adx_val < adx_threshold:                      return None

        # RSI filter with danger zone blocked
        if rsi < VCP_RSI_MIN:                            return None
        if rsi > VCP_RSI_MAX:                            return None
        if 65.0 < rsi < 70.0:                            return None   # danger zone

        stock_r60 = float((entry / df["Close"].iloc[-60]) - 1)
        if stock_r60 < nifty_r60 + MIN_RS_VS_NIFTY:     return None
        if stock_r60 > MAX_RUN_60D:                      return None
        if not w_obv_up:                                 return None
        if float(curr["OBV"]) < float(curr["OBV_EMA50"]): return None

        # ══════════════════════════════════════════════════════
        #  FILTER BLOCK 2 — Base Quality
        # ══════════════════════════════════════════════════════
        base         = df.iloc[-VCP_BASE_DAYS-1:-1]
        if len(base) < VCP_BASE_DAYS:                    return None
        base_high    = float(base["High"].max())
        base_low     = float(base["Low"].min())
        base_range   = (base_high - base_low) / base_low
        if base_range > VCP_BASE_RANGE:                  return None
        if base_range < VCP_BASE_MIN:                    return None
        avg_vol_40   = float(df["AvgVol40"].iloc[-2])
        avg_vol_base = float(base["Volume"].mean())
        vol_ratio    = avg_vol_base / avg_vol_40 if avg_vol_40 > 0 else 999
        if vol_ratio > VCP_VOL_DRYUP:                    return None

        # ══════════════════════════════════════════════════════
        #  FILTER BLOCK 3 — Breakout Quality
        # ══════════════════════════════════════════════════════
        if entry <= base_high:                           return None
        if vol_surge < VCP_VOL_MIN:                      return None
        if 5.0 <= vol_surge < 7.0:                       return None   # gap filter

        day_range = float(curr["High"]) - float(curr["Low"])
        close_pos = 0.0
        if day_range > 0:
            close_pos = (entry - float(curr["Low"])) / day_range
            if close_pos < 0.5:                          return None   # weak close

        if not (ema20 > ema200):                         return None

        last_20      = df.tail(20)
        green_vol    = last_20[last_20["Close"] > last_20["Open"]]["Volume"].sum()
        red_vol      = last_20[last_20["Close"] < last_20["Open"]]["Volume"].sum() or 1
        buy_pressure = float(green_vol / red_vol)
        if buy_pressure < 1.2:                           return None

        # ══════════════════════════════════════════════════════
        #  SCORING
        # ══════════════════════════════════════════════════════
        score = 5.0

        if   base_range < 0.05: score += 3.0
        elif base_range < 0.08: score += 2.0
        elif base_range < 0.10: score += 1.0
        elif base_range < 0.12: score += 0.5

        if   vol_ratio < 0.60:  score += 2.0
        elif vol_ratio < 0.70:  score += 1.5
        elif vol_ratio < 0.80:  score += 1.0
        elif vol_ratio < 0.90:  score += 0.5

        if   vol_surge >= 5.0:  score += 2.0
        elif vol_surge >= 4.0:  score += 1.5
        elif vol_surge >= 3.5:  score += 1.0
        elif vol_surge >= 3.0:  score += 0.5
        elif vol_surge >= 2.0:  score += 0.25

        if   adx_val >= 50:     score += 3.0
        elif adx_val >= 45:     score += 2.5
        elif adx_val >= 40:     score += 2.0
        elif adx_val >= 38:     score += 1.5
        elif adx_val >= 35:     score += 1.0
        elif adx_val >= 33:     score += 0.5
        elif adx_val >= 28:     score += 0.25

        if w_obv_up:             score += 1.5

        if   buy_pressure >= 3.0: score += 2.0
        elif buy_pressure >= 2.5: score += 1.5
        elif buy_pressure >= 2.0: score += 1.0
        elif buy_pressure >= 1.5: score += 0.5
        elif buy_pressure >= 1.2: score += 0.25

        if ema20 > ema50 > ema200:           score += 1.0
        if w_ema20 > w_ema50:                score += 0.5
        if stock_r60 > nifty_r60 + 0.10:    score += 1.0
        elif stock_r60 > nifty_r60 + 0.05:  score += 0.5
        if market_trend == "STRONG_BULL":    score += 0.5

        if score < MIN_SCORE:                            return None

        # ══════════════════════════════════════════════════════
        #  SL & TARGETS
        # ══════════════════════════════════════════════════════
        atr_val = float(curr["ATR"])
        sl_atr  = entry - ATR_MULTIPLIER_SL * atr_val
        sl_base = base_low * 0.99
        sl_pct  = entry * (1 - MAX_RISK_PCT)
        sl      = round(max(sl_atr, sl_base, sl_pct), 1)
        risk    = entry - sl

        if risk <= 0:
            return None
        if risk / entry > MAX_RISK_PCT:
            sl   = round(entry * (1 - MAX_RISK_PCT), 1)
            risk = entry - sl

        target1 = round(entry + risk * RR_RATIO_T1, 1)
        target2 = round(entry + risk * RR_RATIO_T2, 1)
        shares, position_val = calculate_position(entry, sl)

        sl_pct_val = round((entry - sl) / entry * 100, 1)

        return {
            "ticker":        symbol,
            "entry":         round(entry, 1),
            "sl":            sl,
            "target1":       target1,
            "target2":       target2,
            "atr":           round(atr_val, 2),
            "score":         round(score, 1),
            "rsi":           round(rsi, 1),
            "adx":           round(adx_val, 1),
            "adx_threshold": adx_threshold,
            "vol_surge":     round(vol_surge, 1),
            "base_range":    round(base_range * 100, 1),
            "vol_dryup":     round(vol_ratio, 2),
            "buy_pressure":  round(buy_pressure, 1),
            "close_pos":     round(close_pos, 2),
            "stock_r60":     round(stock_r60 * 100, 1),
            "market":        market_trend,
            "shares":        shares,
            "position_val":  position_val,
            "risk_amt":      round(shares * (entry - sl), 0),
            "sl_pct":        sl_pct_val,
        }

    except Exception as e:
        print(f"    Error {symbol}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  MAIN SCAN
# ═══════════════════════════════════════════════════════════════
def run_scan():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print("=" * 62)
    print(f"  VCP SCANNER — AngelOne Edition — {now}")
    print("=" * 62)

    # ── Step 1: Check market regime ───────────────────────────
    print("\n  Checking market regime...")
    regime, nifty_r60, adx_threshold, ema50, ema200, price = get_market_regime()

    # ── Regime display ────────────────────────────────────────
    regime_emoji = {
        "STRONG_BULL": "🚀",
        "BULLISH":     "✅",
        "CHOPPY":      "⚠️ ",
        "BEARISH":     "❌",
        "NEUTRAL":     "⚠️ ",
    }.get(regime, "❓")

    print(f"\n  {regime_emoji} Market Regime  : {regime}")
    print(f"  Nifty Price    : ₹{price:,.0f}")
    print(f"  EMA 50         : ₹{ema50:,.0f}  "
          f"({'above' if price > ema50 else 'BELOW'} price)")
    print(f"  EMA 200        : ₹{ema200:,.0f}  "
          f"({'above' if price > ema200 else 'below'} price)")
    print(f"  Nifty 60d ret  : {round(nifty_r60*100,1)}%")
    print(f"  ADX threshold  : {adx_threshold} "
          f"({'strict — STRONG_BULL' if adx_threshold == 28 else 'standard — BULLISH'})")
    print(f"  Min Score      : {MIN_SCORE}")
    print(f"  Capital        : ₹{CAPITAL:,.0f}")
    print(f"  Risk/trade     : {int(RISK_PER_TRADE*100)}% = ₹{int(CAPITAL*RISK_PER_TRADE):,}")

    # ── Step 2: Regime gate ───────────────────────────────────
    NO_TRADE_REGIMES = ("BEARISH", "NEUTRAL", "CHOPPY")

    if regime in NO_TRADE_REGIMES:
        reason_map = {
            "BEARISH": (
                "Nifty is below EMA50. Market is in downtrend.\n"
                "All breakouts likely to fail. Protecting capital."
            ),
            "CHOPPY": (
                "Nifty is above EMA50 BUT EMA50 slope is flat.\n"
                "Market is sideways/choppy. Breakouts fail in choppy markets.\n"
                "Wait for EMA50 to start rising again."
            ),
            "NEUTRAL": (
                "Market regime unclear. Mixed signals.\n"
                "Not worth the risk. Waiting for clarity."
            ),
        }
        reason = reason_map.get(regime, "Market not suitable for trading.")

        print(f"\n  ══════════════════════════════════════════")
        print(f"  {regime_emoji}  NO TRADES TODAY — {regime}")
        print(f"  {reason}")
        print(f"  ══════════════════════════════════════════")

        if regime == "BEARISH":
            gap = price - ema50
            print(f"\n  📊 Recovery watch:")
            print(f"     Nifty needs to gain ₹{abs(gap):,.0f} to reach EMA50 (₹{ema50:,.0f})")
            print(f"     Once price closes ABOVE EMA50 for 2-3 days → BULLISH regime")
            print(f"     Once EMA50 > EMA200 and both rising → STRONG_BULL regime")
        elif regime == "CHOPPY":
            print(f"\n  📊 Recovery watch:")
            print(f"     EMA50 needs to start sloping upward consistently")
            print(f"     Current EMA50: ₹{ema50:,.0f} — watch for it to rise day by day")

        msg = (
            f"{regime_emoji} <b>NO TRADES — {regime}</b>\n\n"
            f"{reason}\n\n"
            f"<b>Market data:</b>\n"
            f"Nifty     : ₹{price:,.0f}\n"
            f"EMA50     : ₹{ema50:,.0f}\n"
            f"EMA200    : ₹{ema200:,.0f}\n"
            f"Nifty 60d : {round(nifty_r60*100,1)}%\n"
            f"ADX min   : {adx_threshold} (not used today)"
        )
        try:
            from telegram_bot import send_message
            send_message(msg)
        except:
            pass
        return

    # ── Step 3: Scan stocks ───────────────────────────────────
    stocks  = fetch_nifty200()
    signals = []
    total   = len(stocks)
    print(f"\n  Scanning {total} stocks "
          f"(regime={regime}, ADX≥{adx_threshold}, score≥{MIN_SCORE})...\n")

    for i, symbol in enumerate(stocks):
        print(f"  [{i+1:>3}/{total}] {symbol:<22}", end=" ", flush=True)
        sig = detect_vcp_signal(symbol, regime, nifty_r60, adx_threshold)
        if sig:
            signals.append(sig)
            print(
                f"✅ Score:{sig['score']}  ADX:{sig['adx']}≥{adx_threshold}  "
                f"Vol:{sig['vol_surge']}x  RSI:{sig['rsi']}  "
                f"Shares:{sig['shares']}"
            )
        else:
            print("—")
        time.sleep(0.3)   # be gentle on the API

    # ── Step 4: Results ───────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  SCAN COMPLETE — {len(signals)} signal(s) found")
    print(f"  Regime: {regime}  |  ADX threshold: {adx_threshold}  "
          f"|  Min score: {MIN_SCORE}")
    print(f"{'='*62}\n")

    if not signals:
        send_no_signal_alert()
        print("  No signals today. Telegram notified.")
        return

    # Sort by score descending
    signals.sort(key=lambda x: x["score"], reverse=True)

    # ── Step 5: Print + alert each signal ─────────────────────
    for sig in signals:
        reward_t1 = round(sig["shares"] * (sig["target1"] - sig["entry"]), 0)
        reward_t2 = round(sig["shares"] * (sig["target2"] - sig["entry"]), 0)

        if sig["score"] >= 16:    badge = "🔥 ELITE"
        elif sig["score"] >= 14:  badge = "⭐ STRONG"
        elif sig["score"] >= 13:  badge = "✅ GOOD"
        else:                     badge = "📋 STANDARD"

        print(f"  {badge} — {sig['ticker']}")
        print(f"  ┌─────────────────────────────────────────────────┐")
        print(f"  │ Entry  : ₹{sig['entry']:<10}  SL : ₹{sig['sl']} (-{sig['sl_pct']}%)")
        print(f"  │ T1     : ₹{sig['target1']:<10}  T2 : ₹{sig['target2']}")
        print(f"  │ Shares : {sig['shares']:<10}  Deploy: ₹{sig['position_val']:,.0f}")
        print(f"  │ Risk   : ₹{sig['risk_amt']:,.0f}       "
              f"T1 profit: ₹{reward_t1:,.0f}  T2 profit: ₹{reward_t2:,.0f}")
        print(f"  ├─────────────────────────────────────────────────┤")
        print(f"  │ Score  : {sig['score']}   Regime: {sig['market']}   "
              f"ADX: {sig['adx']} (≥{sig['adx_threshold']})")
        print(f"  │ RSI    : {sig['rsi']}   VolSurge: {sig['vol_surge']}x   "
              f"BuyPressure: {sig['buy_pressure']}")
        print(f"  │ Base   : {sig['base_range']}%   VolDryup: {sig['vol_dryup']}   "
              f"RS60d: {sig['stock_r60']}%")
        print(f"  └─────────────────────────────────────────────────┘\n")

        send_entry_alert(sig)
        add_trade(sig)
        time.sleep(1)

    # ── Step 6: Capital summary ───────────────────────────────
    total_deploy = sum(s["position_val"] for s in signals)
    total_risk   = sum(s["risk_amt"]     for s in signals)

    print(f"  CAPITAL SUMMARY:")
    print(f"  Total signals   : {len(signals)}")
    print(f"  Total to deploy : ₹{total_deploy:,.0f}")
    print(f"  Total at risk   : ₹{total_risk:,.0f}  "
          f"({round(total_risk/CAPITAL*100,1)}% of capital)")
    print(f"  Available cap   : ₹{CAPITAL:,.0f}")

    if total_deploy > CAPITAL * 0.80:
        top2 = [s["ticker"] for s in signals[:2]]
        print(f"\n  ⚠️  WARNING: Need ₹{total_deploy:,.0f} but cap is ₹{CAPITAL:,.0f}")
        print(f"  → Take only TOP 2 signals by score: {top2}")
        print(f"  → Skip rest until capital frees up from existing trades")

    if len(signals) > 3:
        print(f"\n  💡 TIP: {len(signals)} signals found — take TOP 3 by score only.")
        print(f"     More signals = more concentrated risk.")
        print(f"     Top 3: {[s['ticker'] for s in signals[:3]]}")


if __name__ == "__main__":
    run_scan()
