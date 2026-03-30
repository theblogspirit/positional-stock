"""
telegram_bot.py — Sends alerts to Telegram
"""

import os
import requests

# Read from environment variables (set as GitHub Actions secrets)
# or fall back to hardcoded values for local testing
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

def send_message(text):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def send_entry_alert(signal):
    msg = f"""🚀 <b>NEW VCP SIGNAL FOUND</b>

📌 <b>Stock    :</b> {signal['ticker']}
💰 <b>Entry    :</b> ₹{signal['entry']}
🛑 <b>Stop Loss:</b> ₹{signal['sl']}  ({round((signal['sl']-signal['entry'])/signal['entry']*100,1)}%)
🎯 <b>Target 1 :</b> ₹{signal['target1']}  (+{round((signal['target1']-signal['entry'])/signal['entry']*100,1)}%)
🏆 <b>Target 2 :</b> ₹{signal['target2']}  (+{round((signal['target2']-signal['entry'])/signal['entry']*100,1)}%)

📊 <b>Score    :</b> {signal['score']}
📈 <b>ADX      :</b> {signal['adx']}
🔊 <b>Volume   :</b> {signal['vol_surge']}x
📦 <b>Base     :</b> {signal['base_range']}%
🌍 <b>Market   :</b> {signal['market']}

⚡ <b>Action: BUY tomorrow at market open</b>
⚠️ Risk max 20% of capital on this trade"""
    send_message(msg)

def send_exit_alert(trade, reason, current_price, pnl_pct):
    emoji = "✅" if pnl_pct > 0 else "❌"
    msg = f"""{emoji} <b>EXIT ALERT — {trade['ticker']}</b>

📌 <b>Reason   :</b> {reason}
💰 <b>Entry    :</b> ₹{trade['entry']}
💸 <b>Exit     :</b> ₹{current_price}
📊 <b>P&L      :</b> {pnl_pct:+.2f}%
📅 <b>Days Held:</b> {trade.get('days_held', '?')}

<b>Action: SELL your position now</b>"""
    send_message(msg)

def send_t1_alert(trade, current_price):
    pnl = round((current_price - trade['entry']) / trade['entry'] * 100, 2)
    msg = f"""🎯 <b>TARGET 1 HIT — {trade['ticker']}</b>

💰 <b>Entry    :</b> ₹{trade['entry']}
✅ <b>Target 1 :</b> ₹{trade['target1']}
📊 <b>P&L      :</b> +{pnl}%

<b>Action:</b>
• SELL 50% of your position now
• Move Stop Loss to ₹{trade['entry']} (breakeven)
• Hold remaining 50% for Target 2: ₹{trade['target2']}"""
    send_message(msg)

def send_morning_summary(open_trades, prices):
    if not open_trades:
        msg = "📊 <b>MORNING SUMMARY</b>\n\nNo open trades today. Waiting for next signal. 🎯"
        send_message(msg)
        return

    lines = ["📊 <b>OPEN TRADES MORNING SUMMARY</b>\n"]
    total_pnl = 0

    for t in open_trades:
        ticker  = t['ticker']
        entry   = t['entry']
        current = prices.get(ticker, entry)
        pnl_pct = round((current - entry) / entry * 100, 2)
        days    = t.get('days_held', 0)
        t1_hit  = t.get('t1_hit', False)
        total_pnl += pnl_pct

        if pnl_pct >= 10:   status = "🟢"
        elif pnl_pct >= 0:  status = "🟡"
        elif pnl_pct >= -4: status = "🟠"
        else:                status = "🔴"

        t1_tag = " | T1 ✅" if t1_hit else ""
        lines.append(
            f"{status} <b>{ticker}</b> | Entry ₹{entry} | Now ₹{round(current,1)} | "
            f"{pnl_pct:+.1f}% | Day {days}{t1_tag}"
        )

    lines.append(f"\n📈 <b>Total Open Trades:</b> {len(open_trades)}")
    lines.append(f"💰 <b>Avg P&L:</b> {round(total_pnl/len(open_trades),2):+.1f}%")
    send_message("\n".join(lines))

def send_no_signal_alert():
    send_message("🔍 <b>EVENING SCAN COMPLETE</b>\n\nNo new VCP signals found today.\nMarket scanned: Nifty 200")


def send_error_alert(context: str, error: Exception):
    """Send a Telegram alert when an unexpected error occurs in the bot."""
    import traceback
    tb = traceback.format_exc()[-400:]
    msg = (
        "🚨 <b>BOT ERROR</b>\n\n"
        f"📍 <b>Where :</b> {context}\n"
        f"❌ <b>Error :</b> {type(error).__name__}: {str(error)}\n"
        f"<pre>{tb}</pre>\n"
        "⚠️ Check your trades manually."
    )
    send_message(msg)
