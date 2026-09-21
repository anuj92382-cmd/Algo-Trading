"""
notifier.py - Telegram Notification System
Trade alerts Telegram pe bhejo (optional feature)
"""

import logging
import requests
from config import TELEGRAM

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram pe trade alerts bhejo"""

    def __init__(self):
        self.enabled = TELEGRAM["enabled"]
        self.bot_token = TELEGRAM["bot_token"]
        self.chat_id = TELEGRAM["chat_id"]
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send(self, message: str) -> bool:
        """Message bhejo"""
        if not self.enabled:
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def trade_entry(self, symbol: str, direction: str, price: float,
                    qty: int, sl: float, target: float, strategy: str):
        msg = (
            f"🟢 <b>TRADE ENTRY</b>\n"
            f"📈 Symbol: <b>{symbol}</b>\n"
            f"Direction: {direction}\n"
            f"Price: ₹{price:.2f}\n"
            f"Qty: {qty}\n"
            f"Stop Loss: ₹{sl:.2f}\n"
            f"Target: ₹{target:.2f}\n"
            f"Strategy: {strategy}"
        )
        return self.send(msg)

    def trade_exit(self, symbol: str, entry_price: float, exit_price: float,
                   qty: int, pnl: float, reason: str):
        emoji = "✅" if pnl >= 0 else "❌"
        msg = (
            f"{emoji} <b>TRADE EXIT</b>\n"
            f"📊 Symbol: <b>{symbol}</b>\n"
            f"Entry: ₹{entry_price:.2f} → Exit: ₹{exit_price:.2f}\n"
            f"Qty: {qty}\n"
            f"P&L: <b>₹{pnl:.2f}</b>\n"
            f"Reason: {reason}"
        )
        return self.send(msg)

    def daily_summary(self, total_trades: int, winners: int, losers: int,
                      total_pnl: float, capital: float):
        win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
        emoji = "🟢" if total_pnl >= 0 else "🔴"
        msg = (
            f"{emoji} <b>DAILY SUMMARY</b>\n"
            f"Total Trades: {total_trades}\n"
            f"Winners: {winners} | Losers: {losers}\n"
            f"Win Rate: {win_rate:.1f}%\n"
            f"Total P&L: <b>₹{total_pnl:.2f}</b>\n"
            f"Capital: ₹{capital:.2f}"
        )
        return self.send(msg)

    def error_alert(self, error_msg: str):
        msg = f"⚠️ <b>ERROR ALERT</b>\n{error_msg}"
        return self.send(msg)


# Singleton
notifier = TelegramNotifier()
