"""
trade_manager.py — Tracks open trades, monitors SL/T1/T2, sends exit alerts
=============================================================================
Identical logic to original — only data source changed:
  - yfinance REMOVED
  - AngelOne SmartAPI used for all price fetching

Run every evening after market close to check all open positions:
  python trade_manager.py

For morning summary:
  python trade_manager.py morning
"""

import json, os
from datetime import datetime, date
import pandas_ta as ta
import pandas as pd

# ── AngelOne data client (replaces yfinance) ─────────────────
from angel_client import get_candle_data, get_ltp

from telegram_bot import send_exit_alert, send_t1_alert, send_morning_summary, send_message

TRADES_FILE   = "trades.json"
MAX_HOLD_DAYS = 60


# ─────────────────────────────────────────────
#  LOAD / SAVE TRADES
# ─────────────────────────────────────────────
def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE, "r") as f:
        return json.load(f)

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def add_trade(signal):
    """Call this when a new signal is found in scanner.py"""
    trades = load_trades()

    # Don't add duplicate
    for t in trades:
        if t["ticker"] == signal["ticker"] and t["status"] == "OPEN":
            print(f"  {signal['ticker']} already has open trade, skipping")
            return

    trade = {
        "ticker":     signal["ticker"],
        "entry":      signal["entry"],
        "sl":         signal["sl"],
        "target1":    signal["target1"],
        "target2":    signal["target2"],
        "score":      signal["score"],
        "adx":        signal["adx"],
        "vol_surge":  signal["vol_surge"],
        "entry_date": str(date.today()),
        "days_held":  0,
        "t1_hit":     False,
        "status":     "OPEN",
    }
    trades.append(trade)
    save_trades(trades)
    print(f"  ✅ Trade added: {signal['ticker']} @ ₹{signal['entry']}")


# ─────────────────────────────────────────────
#  GET CURRENT PRICES  (uses AngelOne LTP)
# ─────────────────────────────────────────────
def get_current_prices(tickers):
    """
    Fetches LTP, day high, day low for each ticker via AngelOne.

    Parameters
    ----------
    tickers : list of plain NSE symbols e.g. ["RELIANCE", "INFY"]

    Returns
    -------
    dict with keys: ticker, ticker_high, ticker_low
    """
    prices = {}
    for ticker in tickers:
        try:
            data = get_ltp(ticker, exchange="NSE")
            prices[ticker]           = data["ltp"]
            prices[ticker + "_high"] = data["high"]
            prices[ticker + "_low"]  = data["low"]
        except Exception as e:
            print(f"  Price fetch error {ticker}: {e}")
    return prices


# ─────────────────────────────────────────────
#  CHECK WEEKLY EMA50 FOR TREND EXIT  (uses AngelOne)
# ─────────────────────────────────────────────
def check_weekly_trend(ticker):
    """
    Returns True if weekly trend is intact (price >= W_EMA50 * 0.99).
    Returns True on error (conservative — don't exit on data issues).
    """
    try:
        df = get_candle_data(ticker, exchange="NSE", interval="ONE_DAY", days=730)

        if df.empty or len(df) < 60:
            return True   # can't check, assume ok

        df.index = pd.to_datetime(df.index)
        weekly   = df["Close"].resample("W").last().dropna()

        if len(weekly) < 50:
            return True

        w_ema50 = float(ta.ema(weekly, 50).iloc[-1])
        current = float(weekly.iloc[-1])
        return current >= w_ema50 * 0.99   # True = trend intact

    except:
        return True


# ─────────────────────────────────────────────
#  MONITOR ALL OPEN TRADES
# ─────────────────────────────────────────────
def monitor_trades():
    trades      = load_trades()
    open_trades = [t for t in trades if t["status"] == "OPEN"]

    if not open_trades:
        print("  No open trades to monitor")
        return

    print(f"  Monitoring {len(open_trades)} open trades...")
    tickers = [t["ticker"] for t in open_trades]
    prices  = get_current_prices(tickers)

    for trade in trades:
        if trade["status"] != "OPEN":
            continue

        ticker  = trade["ticker"]
        entry   = trade["entry"]
        sl      = trade["sl"]
        target1 = trade["target1"]
        target2 = trade["target2"]
        t1_hit  = trade.get("t1_hit", False)

        current = prices.get(ticker, entry)
        high    = prices.get(ticker + "_high", current)
        low     = prices.get(ticker + "_low",  current)
        pnl_pct = round((current - entry) / entry * 100, 2)

        # Update days held
        try:
            entry_date  = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            days_held   = (date.today() - entry_date).days
            trade["days_held"] = days_held
        except:
            days_held = trade.get("days_held", 0)

        print(f"  {ticker:<14} Entry:₹{entry}  Now:₹{round(current,1)}  P&L:{pnl_pct:+.1f}%  Day:{days_held}")

        # ── CHECK T2 FIRST (best outcome) ──────────────────
        if t1_hit and high >= target2:
            t1_pnl    = (target1 - entry) / entry * 100
            t2_pnl    = (target2 - entry) / entry * 100
            final_pnl = round(t1_pnl * 0.5 + t2_pnl * 0.5, 2)
            send_exit_alert(trade, "🏆 TARGET 2 HIT — FULL WIN!", target2, final_pnl)
            trade["status"]     = "CLOSED"
            trade["outcome"]    = "FULL_WIN"
            trade["exit_price"] = target2
            trade["exit_pnl"]   = final_pnl
            trade["close_date"] = str(date.today())
            print(f"    → FULL WIN: {final_pnl:+}%")
            continue

        # ── CHECK T1 ───────────────────────────────────────
        if not t1_hit and high >= target1:
            trade["t1_hit"] = True
            trade["sl"]     = entry   # Move SL to breakeven
            send_t1_alert(trade, current)
            print(f"    → T1 HIT: SL moved to breakeven ₹{entry}")
            continue

        # ── CHECK STOP LOSS ────────────────────────────────
        if low <= sl:
            if t1_hit:
                t1_pnl    = (target1 - entry) / entry * 100
                final_pnl = round(t1_pnl * 0.5, 2)
                send_exit_alert(trade, "Stopped at Breakeven (after T1)", sl, final_pnl)
                trade["outcome"] = "PARTIAL_WIN"
            else:
                final_pnl = round((sl - entry) / entry * 100, 2)
                send_exit_alert(trade, "🛑 STOP LOSS HIT", sl, final_pnl)
                trade["outcome"] = "LOSS"

            trade["status"]     = "CLOSED"
            trade["exit_price"] = sl
            trade["exit_pnl"]   = final_pnl
            trade["close_date"] = str(date.today())
            print(f"    → SL HIT: {final_pnl:+}%")
            continue

        # ── CHECK MAX HOLD DAYS ────────────────────────────
        if days_held >= MAX_HOLD_DAYS:
            final_pnl = pnl_pct
            if t1_hit:
                t1_pnl    = (target1 - entry) / entry * 100
                final_pnl = round(t1_pnl * 0.5 + pnl_pct * 0.5, 2)
                outcome   = "PARTIAL_WIN"
            else:
                outcome   = "EXPIRED"

            send_exit_alert(trade, f"⏰ 60 DAYS REACHED — TIME EXIT", round(current, 1), final_pnl)
            trade["status"]     = "CLOSED"
            trade["outcome"]    = outcome
            trade["exit_price"] = round(current, 1)
            trade["exit_pnl"]   = final_pnl
            trade["close_date"] = str(date.today())
            print(f"    → TIME EXIT (day {days_held}): {final_pnl:+}%")
            continue

        # ── CHECK WEEKLY TREND BREAK ───────────────────────
        trend_intact = check_weekly_trend(ticker)
        if not trend_intact:
            final_pnl = pnl_pct
            if t1_hit:
                t1_pnl    = (target1 - entry) / entry * 100
                final_pnl = round(t1_pnl * 0.5 + pnl_pct * 0.5, 2)
                outcome   = "PARTIAL_WIN"
            else:
                outcome   = "TREND_EXIT"

            send_exit_alert(trade, "📉 WEEKLY TREND BROKEN — EXIT", round(current, 1), final_pnl)
            trade["status"]     = "CLOSED"
            trade["outcome"]    = outcome
            trade["exit_price"] = round(current, 1)
            trade["exit_pnl"]   = final_pnl
            trade["close_date"] = str(date.today())
            print(f"    → TREND EXIT: {final_pnl:+}%")
            continue

        print(f"    → Trade running normally ✅")

    save_trades(trades)
    print(f"\n  Trades updated and saved.")


# ─────────────────────────────────────────────
#  MORNING SUMMARY
# ─────────────────────────────────────────────
def morning_summary():
    trades      = load_trades()
    open_trades = [t for t in trades if t["status"] == "OPEN"]

    if not open_trades:
        send_message("📊 <b>MORNING SUMMARY</b>\n\nNo open trades today.\nBot is watching Nifty 200 for next VCP signal. 🎯")
        print("  No open trades — sent empty summary")
        return

    tickers = [t["ticker"] for t in open_trades]
    prices  = get_current_prices(tickers)

    # Update days held for display
    for t in open_trades:
        try:
            entry_date  = datetime.strptime(t["entry_date"], "%Y-%m-%d").date()
            t["days_held"] = (date.today() - entry_date).days
        except:
            pass

    send_morning_summary(open_trades, prices)
    print(f"  Morning summary sent for {len(open_trades)} open trades")


# ─────────────────────────────────────────────
#  PERFORMANCE SUMMARY
# ─────────────────────────────────────────────
def print_performance():
    trades  = load_trades()
    closed  = [t for t in trades if t["status"] == "CLOSED"]
    open_t  = [t for t in trades if t["status"] == "OPEN"]

    if not closed:
        print("  No closed trades yet")
        return

    wins    = [t for t in closed if t.get("exit_pnl", 0) > 0]
    losses  = [t for t in closed if t.get("exit_pnl", 0) <= 0]
    wr      = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_pnl = round(sum(t.get("exit_pnl", 0) for t in closed) / len(closed), 2)

    print(f"\n  PERFORMANCE SUMMARY")
    print(f"  {'='*40}")
    print(f"  Open Trades  : {len(open_t)}")
    print(f"  Closed Trades: {len(closed)}")
    print(f"  Win Rate     : {wr}%")
    print(f"  Avg P&L      : {avg_pnl:+}%")
    print(f"  Total P&L    : {round(sum(t.get('exit_pnl',0) for t in closed),2):+}%")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "morning":
        print("Running morning summary...")
        morning_summary()
    else:
        print("Monitoring open trades...")
        monitor_trades()
        print_performance()
