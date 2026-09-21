"""
config.py - Central Configuration File
Zerodha Kite Algo Trading Application
Sabhi settings yahan se control hoti hain
"""

import os
import pytz
from datetime import time
from dotenv import load_dotenv

# .env file load karo
load_dotenv()

# ============================================================
# API CREDENTIALS
# ============================================================
KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")
KITE_USER_ID = os.getenv("KITE_USER_ID", "")
KITE_REQUEST_TOKEN = os.getenv("KITE_REQUEST_TOKEN", "")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")

# ============================================================
# TRADING MODE
# ============================================================
# "PAPER"  = Fake trading (practice ke liye, koi real order nahi)
# "LIVE"   = Real money trading (sambhal ke!)
TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")
IS_PAPER_TRADING = (TRADING_MODE == "PAPER")

# ============================================================
# CAPITAL & RISK MANAGEMENT
# ============================================================
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", 100000))
MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PER_TRADE", 1.0))   # 1% per trade
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS", 3.0))           # 3% daily max loss
MAX_OPEN_POSITIONS = 5          # Ek saath kitni positions rakh sakte ho
MAX_POSITION_SIZE_PCT = 20.0    # Ek stock mein max 20% capital

# Calculated values
MAX_RISK_PER_TRADE = TOTAL_CAPITAL * (MAX_RISK_PER_TRADE_PCT / 100)
MAX_DAILY_LOSS_AMOUNT = TOTAL_CAPITAL * (MAX_DAILY_LOSS_PCT / 100)

# ============================================================
# MARKET TIMINGS (IST)
# ============================================================
IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN = time(9, 15)       # 9:15 AM
MARKET_CLOSE = time(15, 30)     # 3:30 PM

# Intraday ke liye - kab entry band karo
INTRADAY_ENTRY_CUTOFF = time(14, 30)   # 2:30 PM ke baad koi naya entry nahi
INTRADAY_EXIT_TIME = time(15, 15)       # 3:15 PM pe saari positions band

# Pre-market analysis time
PRE_MARKET_TIME = time(9, 0)    # 9:00 AM pe analysis shuru

# ============================================================
# INTRADAY TRADING CONFIG
# ============================================================
INTRADAY_CONFIG = {
    "enabled": True,
    "timeframe": "5minute",         # Candle timeframe
    "indicators": {
        "ema_fast": 9,              # Fast EMA period
        "ema_slow": 21,             # Slow EMA period
        "rsi_period": 14,           # RSI period
        "rsi_overbought": 70,       # RSI overbought level
        "rsi_oversold": 30,         # RSI oversold level
        "vwap": True,               # VWAP use karna hai?
        "atr_period": 14,           # ATR for stop loss
    },
    "entry_conditions": {
        "ema_crossover": True,      # EMA crossover signal
        "rsi_confirm": True,        # RSI se confirm karo
        "vwap_filter": True,        # Price VWAP ke upar/niche ho
        "volume_multiplier": 1.5,   # Volume average se 1.5x zyada ho
    },
    "exit_conditions": {
        "stop_loss_atr_multiplier": 1.5,    # SL = 1.5x ATR
        "target_rr_ratio": 2.0,             # Risk:Reward = 1:2
        "trailing_stop": True,               # Trailing SL lagao
        "trailing_atr_multiplier": 1.0,      # Trailing SL = 1x ATR
    },
    # Intraday watchlist (NSE symbols)
    "watchlist": [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
        "SBIN", "BAJFINANCE", "TATAMOTORS", "WIPRO", "AXISBANK",
        "TATASTEEL", "HINDALCO", "ONGC", "NTPC", "COALINDIA"
    ],
    "exchange": "NSE",
    "product": "MIS",               # MIS = Intraday
    "order_type": "MARKET",
}

# ============================================================
# SWING TRADING CONFIG
# ============================================================
SWING_CONFIG = {
    "enabled": True,
    "timeframe": "day",             # Daily candles
    "holding_days": (3, 15),        # Min 3 din, max 15 din hold karo
    "indicators": {
        "ema_fast": 20,             # 20 EMA
        "ema_slow": 50,             # 50 EMA
        "macd_fast": 12,            # MACD fast period
        "macd_slow": 26,            # MACD slow period
        "macd_signal": 9,           # MACD signal period
        "rsi_period": 14,
        "rsi_overbought": 65,
        "rsi_oversold": 40,
        "bb_period": 20,            # Bollinger Bands
        "bb_std": 2,
        "adx_period": 14,           # ADX for trend strength
        "adx_threshold": 25,        # ADX > 25 = strong trend
    },
    "entry_conditions": {
        "ema_crossover": True,
        "macd_crossover": True,
        "rsi_filter": True,
        "adx_filter": True,
        "volume_confirm": True,
        "volume_multiplier": 1.3,
    },
    "exit_conditions": {
        "stop_loss_pct": 5.0,       # 5% stop loss
        "target_pct": 10.0,         # 10% target
        "trailing_stop_pct": 3.0,   # 3% trailing stop
        "ema_crossdown": True,       # EMA niche cross kare toh exit
    },
    # Swing trading watchlist (NSE + BSE)
    "watchlist": [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
        "SBIN", "BAJFINANCE", "TATAMOTORS", "WIPRO", "AXISBANK",
        "MARUTI", "SUNPHARMA", "DMART", "TITAN", "NESTLEIND",
        "ADANIPORTS", "ULTRACEMCO", "TECHM", "HCLTECH", "LT"
    ],
    "exchange": "NSE",
    "product": "CNC",               # CNC = Delivery (swing ke liye)
    "order_type": "LIMIT",
}

# ============================================================
# KITE API SETTINGS
# ============================================================
KITE_API = {
    "base_url": "https://api.kite.trade",
    "login_url": "https://kite.zerodha.com/connect/login",
    "token_file": "data/access_token.json",
    "max_retries": 3,
    "retry_delay": 2,               # seconds
    "rate_limit_per_second": 10,    # Kite allows 10 req/sec
}

# ============================================================
# DATABASE SETTINGS
# ============================================================
DATABASE = {
    "url": "sqlite:///data/trades.db",      # SQLite database
    "echo": False,
}

# ============================================================
# LOGGING SETTINGS
# ============================================================
LOGGING = {
    "level": "INFO",
    "log_dir": "logs",
    "log_file": "logs/trading.log",
    "max_bytes": 10 * 1024 * 1024,  # 10 MB
    "backup_count": 5,
    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
}

# ============================================================
# NOTIFICATIONS (Telegram - optional)
# ============================================================
TELEGRAM = {
    "enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "alerts": {
        "trade_entry": True,
        "trade_exit": True,
        "stop_loss_hit": True,
        "target_hit": True,
        "daily_summary": True,
        "error_alert": True,
    }
}

# ============================================================
# REPORT SETTINGS
# ============================================================
REPORTS = {
    "dir": "reports",
    "daily_report": True,
    "excel_export": True,
}

# ============================================================
# VALIDATION
# ============================================================
def validate_config():
    """Config check karo - koi zaruri value missing toh nahi"""
    errors = []
    warnings = []

    if not KITE_API_KEY or KITE_API_KEY == "your_api_key_here":
        errors.append("KITE_API_KEY set nahi hai! .env file mein bharo.")

    if not KITE_API_SECRET or KITE_API_SECRET == "your_api_secret_here":
        errors.append("KITE_API_SECRET set nahi hai! .env file mein bharo.")

    if not KITE_USER_ID:
        errors.append("KITE_USER_ID set nahi hai!")

    if IS_PAPER_TRADING:
        warnings.append("⚠️  PAPER TRADING mode ON hai. Koi real order nahi jayega.")
    else:
        warnings.append("🔴 LIVE TRADING mode ON hai! Real money use hoga!")

    if TOTAL_CAPITAL < 10000:
        warnings.append("Capital bahut kam hai. Minimum 10,000 recommend hai.")

    return errors, warnings


if __name__ == "__main__":
    errors, warnings = validate_config()
    for e in errors:
        print(f"❌ ERROR: {e}")
    for w in warnings:
        print(f"⚠️  WARNING: {w}")
    if not errors:
        print("✅ Config sahi hai!")
