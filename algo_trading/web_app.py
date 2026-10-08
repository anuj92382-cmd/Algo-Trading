"""
web_app.py - Flask Web Server for Algo Trading Bot
"""

import os
import sys
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta
from pathlib import Path

# ── SSL Fix - sabse pehle ────────────────────────────────────
try:
    import certifi
    os.environ["SSL_CERT_FILE"]      = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

    import requests as _req
    _orig_send = _req.Session.send
    def _ssl_patched_send(self, request, **kwargs):
        kwargs.setdefault("verify", certifi.where())
        return _orig_send(self, request, **kwargs)
    _req.Session.send = _ssl_patched_send
except Exception as _ssl_err:
    print(f"SSL patch warning: {_ssl_err}")
# ─────────────────────────────────────────────────────────────

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import pytz

from utils.logger import setup_logger
from config import (
    KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID,
    TOTAL_CAPITAL, IS_PAPER_TRADING, TRADING_MODE,
    INTRADAY_CONFIG, SWING_CONFIG, MAX_DAILY_LOSS_AMOUNT,
    validate_config,
)
from order_manager import PaperPortfolio

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")

app = Flask(__name__)
app.secret_key = "algo_trading_secret_key_2024"

# ── Global bot state ─────────────────────────────────────────
_state = {
    "kite":            None,
    "data":            None,
    "order_mgr":       None,
    "risk_mgr":        None,
    "intraday_strat":  None,
    "swing_strat":     None,
    "ticker":          None,
    "bot_running":     False,
    "logged_in":       False,
    "user_name":       "",
    "user_id":         "",
    "error":           "",
    "paper_portfolio": None,  # Paper trading portfolio tracker
    "algo_engine":     None,  # Autonomous Algo Trading Engine
    "mcx_engine":      None,  # Autonomous MCX Commodity Engine
}

# Initialize paper portfolio tracker
try:
    _state["paper_portfolio"] = PaperPortfolio()
    logger.info("📄 Paper Portfolio initialized")
except Exception as _pe:
    logger.warning(f"Paper portfolio init warning: {_pe}")

try:
    from algo_engine import AlgoEngine
    _state["algo_engine"] = AlgoEngine(_state)
    logger.info("⚡ Autonomous AlgoEngine attached to web_state")
except Exception as _algo_err:
    logger.error(f"Failed to initialize AlgoEngine: {_algo_err}")

try:
    from mcx_engine import MCXEngine
    _state["mcx_engine"] = MCXEngine(_state)
    logger.info("🪙 Autonomous MCXEngine attached to web_state")
except Exception as _mcx_err:
    logger.error(f"Failed to initialize MCXEngine: {_mcx_err}")

BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "data" / "access_token.json"
WATCHLIST_FILE = BASE_DIR / "data" / "watchlist.json"

def _get_watchlist_symbols() -> list:
    """Loads persistent watchlist symbols or falls back to INTRADAY_CONFIG."""
    try:
        if WATCHLIST_FILE.exists():
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                syms = json.load(f)
                if isinstance(syms, list) and syms:
                    return [s.upper().strip() for s in syms if s.strip()]
    except Exception as e:
        logger.debug(f"Failed to load watchlist.json: {e}")
    return list(INTRADAY_CONFIG.get("watchlist", [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
        "BAJFINANCE", "TATAMOTORS", "WIPRO", "AXISBANK"
    ]))

def _save_watchlist_symbols(symbols: list):
    """Saves persistent watchlist symbols to watchlist.json."""
    try:
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(symbols, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save watchlist.json: {e}")

def _update_env_variable(key: str, value: str) -> bool:
    """Updates or adds a KEY=VALUE pair in .env file safely."""
    import re
    env_file = BASE_DIR / ".env"
    try:
        content = ""
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                content = f.read()

        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            new_content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
        else:
            new_content = content.rstrip() + f"\n{key}={value}\n"

        with open(env_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"✅ Updated .env: {key}={value}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update .env ({key}={value}): {e}")
        return False
# ─────────────────────────────────────────────────────────────
# TOKEN HELPERS
# ─────────────────────────────────────────────────────────────

def _save_token(access_token: str, user_id: str, user_name: str):
    """Token JSON file mein save karo"""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "access_token": access_token,
            "user_id":      user_id,
            "user_name":    user_name,
            "date":         date.today().isoformat(),
        }, f, indent=2)
    logger.info(f"Token saved for {user_name}")


def _load_token() -> dict:
    """Aaj ka valid token load karo, nahi toh empty dict"""
    try:
        if not TOKEN_FILE.exists():
            return {}
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("date") != date.today().isoformat():
            logger.info("Token purana hai (aaj ka nahi)")
            return {}
        return data
    except Exception as e:
        logger.warning(f"Token load error: {e}")
        return {}


def _init_modules(kite, user_name: str = "", user_id: str = ""):
    """Saare trading modules ek baar initialize karo"""
    from data import DataFetcher
    from order_manager import OrderManager
    from risk_manager import RiskManager
    from strategies.intraday import IntradayStrategy
    from strategies.swing import SwingStrategy

    _state["kite"]           = kite
    _state["data"]           = DataFetcher(kite)
    _state["order_mgr"]      = OrderManager(kite)
    _state["risk_mgr"]       = RiskManager(TOTAL_CAPITAL)
    _state["intraday_strat"] = IntradayStrategy()
    _state["swing_strat"]    = SwingStrategy()
    _state["logged_in"]      = True
    _state["user_name"]      = user_name
    _state["user_id"]        = user_id
    _state["error"]          = ""
    logger.info(f"✅ Modules initialized | User: {user_name} ({user_id})")

    # Start LiveTicker WebSocket for real-time millisecond price feed
    try:
        from ticker import LiveTicker
        access_token = getattr(kite, "access_token", "") or ""
        if not access_token:
            token_data = _load_token()
            access_token = token_data.get("access_token", "")
        if access_token and KITE_API_KEY:
            if not _state.get("ticker"):
                ticker = LiveTicker(kite, KITE_API_KEY, access_token, mode="quote")
                ticker.start(threaded=True)
                _state["ticker"] = ticker
                logger.info("📡 LiveTicker WebSocket initialized & running in background")
    except Exception as _te:
        logger.warning(f"LiveTicker initialization warning: {_te}")

    # Sync algo engine with kite and TRADING_MODE from .env
    engine = _state.get("algo_engine")
    if engine:
        engine.set_mode(TRADING_MODE)
        if engine.status == "STOPPED":
            engine.start()
            logger.info(f"🤖 Algo Auto-Pilot automatically started in {TRADING_MODE} mode")


def _ensure_live_ticker():
    """Returns active LiveTicker WebSocket instance, starting it if necessary."""
    ticker = _state.get("ticker")
    if ticker and ticker.is_connected:
        return ticker

    kite = _state.get("kite")
    if not kite:
        _try_auto_login()
        kite = _state.get("kite")

    if kite and KITE_API_KEY:
        try:
            from ticker import LiveTicker
            access_token = getattr(kite, "access_token", "") or ""
            if not access_token:
                access_token = _load_token().get("access_token", "")
            if access_token:
                if not ticker:
                    ticker = LiveTicker(kite, KITE_API_KEY, access_token, mode="quote")
                    ticker.start(threaded=True)
                    _state["ticker"] = ticker
                    logger.info("📡 LiveTicker WebSocket started via _ensure_live_ticker()")
                return ticker
        except Exception as e:
            logger.warning(f"Failed to start LiveTicker in _ensure_live_ticker: {e}")
    return _state.get("ticker")


def _try_auto_login() -> bool:
    """Saved token se auto login try karo"""
    token_data = _load_token()
    if not token_data:
        return False

    access_token = token_data.get("access_token", "")
    if not access_token:
        return False

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(access_token)

        # Token verify karo
        profile = kite.profile()
        user_name = profile.get("user_name", token_data.get("user_name", ""))
        user_id   = profile.get("user_id",   token_data.get("user_id", ""))

        _init_modules(kite, user_name, user_id)
        logger.info(f"✅ Auto-login successful: {user_name}")
        return True

    except Exception as e:
        logger.warning(f"Auto-login failed: {e}")
        # Token invalid hai - delete karo
        try:
            TOKEN_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# Attempt auto-login at server startup so Algo Engine immediately attaches to live Kite market feed
try:
    if _try_auto_login():
        logger.info(f"🚀 Server startup: Kite auto-login successful | Mode: {TRADING_MODE}")
    else:
        logger.info(f"ℹ️ Server startup: Kite not logged in yet | Mode: {TRADING_MODE}")
except Exception as _startup_login_err:
    logger.warning(f"Startup login attempt warning: {_startup_login_err}")



# ─────────────────────────────────────────────────────────────
# ROUTES - PAGES
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Already logged in?
    if _state["logged_in"]:
        return render_template("index.html",
            trading_mode=TRADING_MODE,
            capital=TOTAL_CAPITAL,
            is_paper=IS_PAPER_TRADING,
            user_name=_state["user_name"],
        )

    # Saved token se try karo
    if _try_auto_login():
        return render_template("index.html",
            trading_mode=TRADING_MODE,
            capital=TOTAL_CAPITAL,
            is_paper=IS_PAPER_TRADING,
            user_name=_state["user_name"],
        )

    return redirect(url_for("login_page"))


@app.route("/login")
def login_page():
    if _state["logged_in"]:
        return redirect(url_for("index"))

    login_url = _get_login_url()

    return render_template("login.html",
        login_url=login_url,
        api_key=KITE_API_KEY,
        error=_state.get("error", ""),
    )


@app.route("/callback")
def zerodha_callback():
    """
    Zerodha login ke baad yahan redirect hota hai.
    URL se request_token automatically capture karo.
    Example: http://localhost:5000/callback?request_token=xxx&action=login&status=success
    """
    req_token = request.args.get("request_token", "")
    status    = request.args.get("status", "")
    action    = request.args.get("action", "")

    logger.info(f"Callback received | status={status} | token={req_token[:8]}...")

    if status != "success" or not req_token:
        error_msg = request.args.get("message", "Login failed ya cancel kiya")
        return render_template("login.html",
            login_url=_get_login_url(),
            api_key=KITE_API_KEY,
            error=f"Zerodha login failed: {error_msg}",
        )

    # Token se session generate karo
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=KITE_API_KEY)

        logger.info(f"Generating session for token: {req_token[:8]}...")
        sess = kite.generate_session(
            request_token=req_token,
            api_secret=KITE_API_SECRET,
        )

        access_token = sess["access_token"]
        user_name    = sess.get("user_name", "")
        user_id      = sess.get("user_id", KITE_USER_ID)

        kite.set_access_token(access_token)
        _save_token(access_token, user_id, user_name)
        _init_modules(kite, user_name, user_id)

        logger.info(f"✅ Auto-login via callback: {user_name} ({user_id})")

        # Seedha dashboard pe bhejo!
        return render_template("index.html",
            trading_mode=TRADING_MODE,
            capital=TOTAL_CAPITAL,
            is_paper=IS_PAPER_TRADING,
            user_name=user_name,
        )

    except Exception as e:
        logger.error(f"Callback login error: {e}")
        return render_template("login.html",
            login_url=_get_login_url(),
            api_key=KITE_API_KEY,
            error=f"Login error: {str(e)}",
        )


def _get_login_url() -> str:
    """Fresh login URL generate karo"""
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=KITE_API_KEY)
        return kite.login_url()
    except Exception as e:
        logger.error(f"Login URL error: {e}")
        return ""
    _state["logged_in"]   = False
    _state["kite"]        = None
    _state["user_name"]   = ""
    _state["user_id"]     = ""
    _state["bot_running"] = False
    try:
        TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return redirect(url_for("login_page"))


# ─────────────────────────────────────────────────────────────
# ROUTES - API
# ─────────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def api_login():
    """
    Request token se access token generate karo.
    Frontend se POST JSON: {"request_token": "xxxx"}
    """
    body = request.get_json(silent=True) or {}
    req_token = body.get("request_token", "").strip()

    if not req_token:
        return jsonify({"success": False, "error": "Request token empty hai"})

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=KITE_API_KEY)

        logger.info(f"Generating session with request_token: {req_token[:8]}...")
        sess = kite.generate_session(
            request_token=req_token,
            api_secret=KITE_API_SECRET,
        )

        access_token = sess["access_token"]
        user_name    = sess.get("user_name", "")
        user_id      = sess.get("user_id", KITE_USER_ID)

        kite.set_access_token(access_token)

        # Save karo
        _save_token(access_token, user_id, user_name)

        # Modules initialize karo
        _init_modules(kite, user_name, user_id)

        logger.info(f"✅ Login successful: {user_name} ({user_id})")
        return jsonify({
            "success":   True,
            "user_name": user_name,
            "user_id":   user_id,
            "redirect":  "/"
        })

    except Exception as e:
        err = str(e)
        logger.error(f"API login error: {err}")

        # User-friendly messages
        if "Invalid" in err or "token" in err.lower():
            msg = "Token galat hai ya expire ho gaya. Zerodha se naya token lo."
        elif "SSL" in err or "certificate" in err.lower():
            msg = f"SSL Error. certifi install karo: pip install certifi\n{err}"
        elif "Forbidden" in err or "403" in err:
            msg = "API Key ya Secret galat hai. .env file check karo."
        else:
            msg = err

        return jsonify({"success": False, "error": msg})


@app.route("/api/status")
def api_status():
    # Get current time in Indian Standard Time (IST)
    ist_now = datetime.now(IST_tz)
    
    current_time = ist_now.time()
    current_day  = ist_now.weekday()  # 0=Monday, 6=Sunday

    # Market hours: Mon-Fri, 9:15 AM - 3:30 PM IST
    market_open_time  = datetime.strptime("09:15", "%H:%M").time()
    market_close_time = datetime.strptime("15:30", "%H:%M").time()

    # Weekend check
    if current_day >= 5:  # Saturday=5, Sunday=6
        mkt = "CLOSED"
    # Pre-market: before 9:15 AM
    elif current_time < market_open_time:
        mkt = "PRE_MARKET"
    # Market hours: 9:15 AM - 3:30 PM
    elif current_time <= market_close_time:
        mkt = "OPEN"
    # After market close
    else:
        mkt = "CLOSED"

    # Real Live Margins detection from Kite Connect
    is_live_mode = (TRADING_MODE == "LIVE")
    if _state.get("algo_engine") and getattr(_state["algo_engine"], "mode", None) == "LIVE":
        is_live_mode = True

    eq_live_bal = 0.0
    comm_live_bal = 0.0
    total_live_bal = TOTAL_CAPITAL

    if _state.get("kite"):
        try:
            m = _state["kite"].margins()
            eq = m.get("equity", {})
            comm = m.get("commodity", {})
            eq_live_bal = float(eq.get("available", {}).get("live_balance", 0) or eq.get("available", {}).get("cash", 0) or eq.get("net", 0) or 0)
            comm_live_bal = float(comm.get("available", {}).get("live_balance", 0) or comm.get("available", {}).get("cash", 0) or comm.get("net", 0) or 0)
            total_live_bal = eq_live_bal + comm_live_bal
        except Exception as _me:
            logger.debug(f"Failed to fetch live Kite margins: {_me}")

    display_capital = total_live_bal if is_live_mode else TOTAL_CAPITAL

    return jsonify({
        "logged_in":        _state["logged_in"],
        "bot_running":      _state["bot_running"],
        "trading_mode":     "LIVE" if is_live_mode else "PAPER",
        "is_paper":         not is_live_mode,
        "capital":          display_capital,
        "equity_capital":   eq_live_bal,
        "commodity_capital": comm_live_bal,
        "market_status":    mkt,
        "time":             ist_now.strftime("%I:%M:%S %p"),  # 12-hour format with AM/PM
        "date":             ist_now.strftime("%d %b %Y"),
        "day":              ist_now.strftime("%A"),
        "user_name":        _state["user_name"],
        "user_id":          _state["user_id"],
        "ticker_connected": (
            _state["ticker"].is_connected if _state["ticker"] else False
        ),
    })


@app.route("/api/pnl")
def api_pnl():
    is_live_mode = (TRADING_MODE == "LIVE")
    if _state.get("algo_engine") and getattr(_state["algo_engine"], "mode", None) == "LIVE":
        is_live_mode = True

    display_capital = TOTAL_CAPITAL
    if is_live_mode and _state.get("kite"):
        try:
            m = _state["kite"].margins()
            eq = m.get("equity", {})
            comm = m.get("commodity", {})
            eq_bal = float(eq.get("available", {}).get("live_balance", 0) or eq.get("available", {}).get("cash", 0) or eq.get("net", 0) or 0)
            comm_bal = float(comm.get("available", {}).get("live_balance", 0) or comm.get("available", {}).get("cash", 0) or comm.get("net", 0) or 0)
            display_capital = eq_bal + comm_bal
        except Exception as _me:
            logger.debug(f"Error fetching live margins in pnl: {_me}")

    risk = _state["risk_mgr"]
    if not risk:
        return jsonify({
            "daily_pnl": 0, "daily_pnl_pct": 0,
            "total_trades": 0, "winners": 0, "losers": 0,
            "win_rate": 0, "current_capital": display_capital,
            "loss_used_pct": 0, "loss_remaining": MAX_DAILY_LOSS_AMOUNT,
            "trading_halted": False, "halt_reason": "",
            "active_positions": 0, "max_daily_loss": MAX_DAILY_LOSS_AMOUNT,
        })
    s = risk.get_daily_stats()
    if is_live_mode:
        s["current_capital"] = display_capital
    s["max_daily_loss"] = MAX_DAILY_LOSS_AMOUNT
    return jsonify(s)


@app.route("/api/positions")
def api_positions():
    positions = []
    ltp_map   = {}

    if _state["ticker"]:
        ltp_map = _state["ticker"].get_ltp_map()
    elif _state["data"]:
        try:
            syms = INTRADAY_CONFIG["watchlist"][:10]
            ltp_map = _state["data"].get_ltp(syms)
        except Exception:
            pass

    for name, strat in [("INTRADAY", _state["intraday_strat"]),
                        ("SWING",    _state["swing_strat"])]:
        if not strat:
            continue
        for sym, pos in strat.get_active_positions().items():
            ltp = ltp_map.get(sym, pos["entry_price"])
            pnl = (ltp - pos["entry_price"]) * pos.get("quantity", 1)
            if pos["direction"] == "SHORT":
                pnl = -pnl
            positions.append({
                "symbol":    sym,
                "strategy":  name,
                "direction": pos["direction"],
                "qty":       pos.get("quantity", 1),
                "entry":     round(pos["entry_price"], 2),
                "ltp":       round(ltp, 2),
                "sl":        round(pos["stop_loss"], 2),
                "target":    round(pos["target"], 2),
                "pnl":       round(pnl, 2),
                "pnl_pct":   round(pnl / max(pos["entry_price"] * pos.get("quantity", 1), 1) * 100, 2),
            })
    algo = _state.get("algo_engine")
    if algo:
        for pos in algo.get_active_positions():
            positions.append({
                "symbol":    pos["symbol"],
                "strategy":  pos.get("strategy_name", "ALGO"),
                "direction": pos.get("side", "BUY"),
                "qty":       pos.get("quantity", 1),
                "entry":     round(pos.get("entry_price", 0), 2),
                "ltp":       round(pos.get("current_price", pos.get("entry_price", 0)), 2),
                "sl":        round(pos.get("stop_loss", 0), 2),
                "target":    round(pos.get("target", 0), 2),
                "pnl":       round(pos.get("pnl", 0), 2),
                "pnl_pct":   round(pos.get("pnl_pct", 0), 2),
            })

    return jsonify(positions)


@app.route("/api/trades")
def api_trades():
    risk = _state["risk_mgr"]
    return jsonify(risk.get_trade_history() if risk else [])


@app.route("/api/watchlist")
def api_watchlist():
    symbols = _get_watchlist_symbols()
    result  = []
    ltp_map = {}

    # 1. First priority: Check algo_engine live quotes cache (ultra-fast in-memory)
    algo = _state.get("algo_engine")
    if algo and getattr(algo, "live_quotes_cache", None):
        with algo._quote_lock:
            for s in symbols:
                if s in algo.live_quotes_cache:
                    q = algo.live_quotes_cache[s]
                    ltp = float(q.get("ltp") or 0)
                    close_p = float(q.get("close") or q.get("prev_close") or 0)
                    chg_pct = float(q.get("change_pct") or 0)
                    if chg_pct == 0 and close_p > 0 and ltp > 0:
                        chg_pct = round(((ltp - close_p) / close_p) * 100, 2)
                    ltp_map[s] = {
                        "ltp": ltp,
                        "change_pct": chg_pct,
                        "change": round(ltp - close_p, 2) if close_p > 0 else 0,
                        "volume": int(q.get("volume") or 0),
                    }

    # 2. Second priority: Live Ticker WebSocket ticks
    ticker = _state.get("ticker")
    if ticker:
        for s in symbols:
            if s not in ltp_map or ltp_map[s]["ltp"] <= 0:
                t = ticker.get_tick(s)
                if t:
                    ltp = float(t.get("ltp") or 0)
                    chg_pct = float(t.get("change_pct") or 0)
                    close_p = float(t.get("close") or 0)
                    if chg_pct == 0 and close_p > 0 and ltp > 0:
                        chg_pct = round(((ltp - close_p) / close_p) * 100, 2)
                    ltp_map[s] = {
                        "ltp": ltp,
                        "change_pct": chg_pct,
                        "change": round(ltp - close_p, 2) if close_p > 0 else 0,
                        "volume": int(t.get("volume") or 0),
                    }

    # 3. Third priority: Kite OHLC batch fetch (fetches exact last_price & close)
    missing = [s for s in symbols if s not in ltp_map or ltp_map[s]["ltp"] <= 0 or ltp_map[s]["change_pct"] == 0]
    kite = _state.get("kite")
    if missing and kite:
        try:
            formatted = [f"NSE:{s}" if ":" not in s else s for s in missing]
            ohlc_data = kite.ohlc(formatted)
            for s in missing:
                raw = ohlc_data.get(f"NSE:{s}", {})
                if raw:
                    last_price = float(raw.get("last_price") or 0)
                    close_p = float(raw.get("ohlc", {}).get("close") or 0)
                    chg_pct = round(((last_price - close_p) / close_p) * 100, 2) if close_p > 0 and last_price > 0 else 0.0
                    ltp_map[s] = {
                        "ltp": last_price,
                        "change_pct": chg_pct,
                        "change": round(last_price - close_p, 2) if close_p > 0 else 0,
                        "volume": int(raw.get("volume") or 0),
                    }
        except Exception as oe:
            logger.debug(f"Watchlist OHLC batch error: {oe}")

    # 4. Fourth priority: Fallback to get_ltp if OHLC failed
    missing_still = [s for s in symbols if s not in ltp_map or ltp_map[s]["ltp"] <= 0]
    if missing_still and _state.get("data"):
        try:
            for s, ltp in _state["data"].get_ltp(missing_still).items():
                if s not in ltp_map or ltp_map[s]["ltp"] <= 0:
                    ltp_map[s] = {"ltp": float(ltp or 0), "change_pct": 0.0, "change": 0.0, "volume": 0}
        except Exception:
            pass

    # Ensure watchlist symbols are subscribed to WebSocket ticker if ticker is running
    if ticker and getattr(ticker, "is_connected", False):
        try:
            unsub = [s for s in symbols if s not in ticker.subscribed_symbols]
            if unsub:
                ticker.subscribe(unsub, exchange="NSE")
        except Exception:
            pass

    in_pos = set()
    if _state.get("algo_engine"):
        in_pos = {p["symbol"] for p in _state["algo_engine"].get_active_positions()}
    elif _state.get("intraday_strat"):
        in_pos = set(_state["intraday_strat"].get_active_positions().keys())

    for sym in symbols:
        d = ltp_map.get(sym, {})
        ltp = float(d.get("ltp") or 0)
        chg = float(d.get("change_pct") or 0)
        vol = int(d.get("volume") or 0)
        result.append({
            "symbol":      sym,
            "ltp":         round(ltp, 2),
            "change_pct":  round(chg, 2),
            "change":      round(d.get("change", 0), 2),
            "volume":      vol,
            "in_position": sym in in_pos,
        })
    return jsonify(result)


@app.route("/api/orders")
def api_orders():
    mgr = _state["order_mgr"]
    if not mgr:
        return jsonify([])
    try:
        return jsonify([{
            "order_id":    o.order_id[:12],
            "symbol":      o.symbol,
            "transaction": o.transaction,
            "qty":         o.quantity,
            "price":       o.price,
            "status":      o.status.value,
            "type":        o.order_type,
            "product":     o.product,
            "tag":         o.tag,
        } for o in mgr.get_orders()])
    except Exception:
        return jsonify([])


# ─────────────────────────────────────────────────────────────
# ⚡ AUTONOMOUS ALGO TRADE APIs (AUTO BUY / AUTO SELL ENGINE)
# ─────────────────────────────────────────────────────────────

@app.route("/api/algo/status")
def api_algo_status():
    """Returns live status of autonomous Algo Engine"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"status": "STOPPED", "mode": "PAPER", "error": "Algo engine not initialized"})
    return jsonify(engine.get_status())


@app.route("/api/algo/toggle", methods=["POST"])
def api_algo_toggle():
    """Starts, pauses, or stops the autonomous Algo Engine"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})

    body = request.get_json(silent=True) or {}
    action = body.get("action", "start").lower().strip()

    if action == "start":
        res = engine.start()
        _state["bot_running"] = (engine.status == "RUNNING")
        return jsonify(res)
    elif action == "pause":
        res = engine.pause()
        _state["bot_running"] = False
        return jsonify(res)
    elif action == "stop":
        res = engine.stop()
        _state["bot_running"] = False
        return jsonify(res)
    else:
        return jsonify({"success": False, "error": f"Unknown action: {action}"})


@app.route("/api/algo/mode", methods=["POST"])
def api_algo_mode():
    """Toggles execution mode between PAPER (5X Intraday Margin) and LIVE (Zerodha)"""
    global TRADING_MODE
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})

    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "PAPER").upper().strip()
    if mode not in ("PAPER", "LIVE"):
        return jsonify({"success": False, "error": "Invalid mode. Must be PAPER or LIVE"})

    res = engine.set_mode(mode)
    if res.get("success"):
        TRADING_MODE = mode
        _update_env_variable("TRADING_MODE", mode)
        if _state.get("mcx_engine"):
            try:
                _state["mcx_engine"].set_mode(mode)
            except Exception as me:
                logger.warning(f"MCX engine mode sync: {me}")
        if mode == "PAPER" and not _state.get("paper_portfolio"):
            try:
                _state["paper_portfolio"] = PaperPortfolio()
            except Exception:
                pass
    return jsonify(res)


def _get_live_kite_margins():
    """Fetches real Zerodha Kite margins with caching (10s TTL) to prevent timeouts."""
    now = time.time()
    cached = _state.get("_cached_kite_margins")
    last_t = _state.get("_cached_kite_margins_time", 0)
    if cached and (now - last_t < 10):
        return cached

    kite = _state.get("kite")
    if not kite:
        return {"equity": 0.0, "commodity": 0.0, "net": 0.0}

    try:
        m = kite.margins()
        eq = m.get("equity", {})
        comm = m.get("commodity", {})
        eq_bal = float(eq.get("available", {}).get("live_balance", 0) or eq.get("available", {}).get("cash", 0) or eq.get("net", 0) or 0)
        comm_bal = float(comm.get("available", {}).get("live_balance", 0) or comm.get("available", {}).get("cash", 0) or comm.get("net", 0) or 0)
        res = {
            "equity": round(eq_bal, 2),
            "commodity": round(comm_bal, 2),
            "net": round(eq_bal + comm_bal, 2),
        }
        _state["_cached_kite_margins"] = res
        _state["_cached_kite_margins_time"] = now
        return res
    except Exception as e:
        logger.debug(f"Error fetching Kite margins: {e}")
        if cached:
            return cached
        return {"equity": 0.0, "commodity": 0.0, "net": 0.0}


@app.route("/api/config", methods=["GET", "POST"])
def api_system_config():
    """Consolidated config endpoint for Trading Mode, Paper Settings, and RMS Rules."""
    global TRADING_MODE, TOTAL_CAPITAL
    engine = _state.get("algo_engine")
    
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        
        # 1. Update Mode if provided
        if "mode" in body or "trading_mode" in body:
            new_mode = (body.get("mode") or body.get("trading_mode")).upper().strip()
            if new_mode in ("PAPER", "LIVE"):
                TRADING_MODE = new_mode
                _update_env_variable("TRADING_MODE", new_mode)
                if engine:
                    engine.set_mode(new_mode)
                if _state.get("mcx_engine"):
                    try:
                        _state["mcx_engine"].set_mode(new_mode)
                    except Exception:
                        pass

        # 2. Update Capital if provided
        if "total_capital" in body:
            try:
                new_cap = float(body["total_capital"])
                if new_cap > 0:
                    TOTAL_CAPITAL = new_cap
                    _update_env_variable("TOTAL_CAPITAL", str(int(new_cap)))
                    if engine:
                        engine.update_config({"risk_config": {"total_capital": new_cap}})
            except Exception as e:
                logger.error(f"Error updating total capital: {e}")
                
        # 3. Update RMS & Universe if provided
        if engine and ("risk_config" in body or "universe" in body or "strategies" in body):
            engine.update_config(body)
            
        return jsonify({"success": True, "message": "Configuration saved successfully", "mode": TRADING_MODE})

    # GET request
    algo_cfg = engine.get_config() if engine else {}
    risk_cfg = algo_cfg.get("risk_config", {})
    
    # Paper summary
    paper_summary = {
        "total_capital": TOTAL_CAPITAL,
        "net_capital": TOTAL_CAPITAL,
        "used_margin": 0.0,
        "available_margin": TOTAL_CAPITAL,
        "closed_pnl": 0.0,
        "open_pnl": 0.0,
        "open_positions_count": 0,
        "total_orders_count": 0,
    }
    portfolio = _state.get("paper_portfolio")
    if portfolio:
        try:
            summary = portfolio.get_margin_summary(_state.get("kite"), TOTAL_CAPITAL)
            paper_summary.update(summary)
            paper_summary["open_positions_count"] = len(portfolio.positions)
            paper_summary["total_orders_count"] = len(portfolio.orders)
        except Exception as pe:
            logger.debug(f"Paper summary error: {pe}")

    return jsonify({
        "trading_mode": TRADING_MODE,
        "total_capital": TOTAL_CAPITAL,
        "is_paper": (TRADING_MODE == "PAPER"),
        "logged_in": _state.get("logged_in", False),
        "user_name": _state.get("user_name", ""),
        "user_id": _state.get("user_id", ""),
        "universe": algo_cfg.get("universe", "all_stocks"),
        "risk_config": risk_cfg,
        "paper_summary": paper_summary,
        "broker_margins": _get_live_kite_margins(),
    })


@app.route("/api/algo/config", methods=["GET", "POST"])
def api_algo_config():
    """GET strategy & risk config, or POST updates to parameters"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"error": "Algo engine not initialized"})

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        return jsonify(engine.update_config(body))
    else:
        return jsonify(engine.get_config())


@app.route("/api/algo/positions")
def api_algo_positions():
    """Active positions opened and monitored by Algo Engine"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify([])
    return jsonify(engine.get_active_positions())


@app.route("/api/algo/position/exit", methods=["POST"])
def api_algo_position_exit():
    """Manual square-off of an active algo position"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})

    body = request.get_json(silent=True) or {}
    pos_id = body.get("pos_id", "")
    return jsonify(engine.manual_exit_position(pos_id))


@app.route("/api/algo/trades")
def api_algo_trades():
    """Completed algo trades history with P&L and exit reasons"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify([])
    limit = int(request.args.get("limit", 50))
    return jsonify(engine.get_closed_trades(limit=limit))


@app.route("/api/algo/trades/clear", methods=["POST"])
def api_algo_trades_clear():
    """Clear completed trades history"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})
    return jsonify(engine.clear_closed_trades())



@app.route("/api/algo/logs")
def api_algo_logs():
    """Live streaming terminal logs from the autonomous engine"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify([])
    limit = int(request.args.get("limit", 150))
    return jsonify(engine.get_recent_logs(limit=limit))


@app.route("/api/algo/scan_now", methods=["POST"])
def api_algo_scan_now():
    """Triggers an immediate on-demand scan and execution cycle"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})
    return jsonify(engine.force_scan_now())


@app.route("/api/algo/kill_switch", methods=["POST"])
def api_algo_kill_switch():
    """🚨 EMERGENCY KILL SWITCH: Halt bot and square-off ALL open positions immediately"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})
    _state["bot_running"] = False
    return jsonify(engine.emergency_kill_switch())


@app.route("/api/algo/equity")
def api_algo_equity():
    """Live intraday equity curve time-series points"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify([])
    return jsonify(engine.get_equity_curve())


@app.route("/api/algo/strategy_analytics")
def api_algo_strategy_analytics():
    """Returns detailed return % and win/loss statistics for a strategy over 1-6 days"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized"})
    strat_id = request.args.get("strat_id", "momentum_trend")
    days = request.args.get("days", "1")
    return jsonify(engine.get_strategy_analytics(strat_id=strat_id, days=days))


@app.route("/api/algo/custom_scanner_stocks")
def api_algo_custom_scanner_stocks():
    """Returns live qualified stocks matching the 4-filter Pre-Market, Sector & OI strategy"""
    engine = _state.get("algo_engine")
    if not engine:
        return jsonify({"success": False, "error": "Algo engine not initialized", "stocks": []})
    return jsonify(engine.get_custom_strategy_scan_candidates())


# ═══════════════════════════════════════════════════════════════
# MCX COMMODITY ALGO API ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route("/api/mcx/status")
def api_mcx_status():
    """Returns live MCX commodity rates, market status, positions, and signals"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    return jsonify(engine.get_status())


@app.route("/api/mcx/toggle", methods=["POST"])
def api_mcx_toggle():
    """Starts or pauses the MCX Algo Bot"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    return jsonify(engine.toggle())


@app.route("/api/mcx/mode", methods=["POST"])
def api_mcx_mode():
    """Switches MCX mode between PAPER and LIVE"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    data = request.get_json() or {}
    mode = data.get("mode", "PAPER")
    return jsonify(engine.set_mode(mode))


@app.route("/api/mcx/order", methods=["POST"])
def api_mcx_order():
    """Places a paper or live order on an MCX commodity"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    data = request.get_json() or {}
    commodity = data.get("commodity", "")
    side = data.get("side", "BUY")
    quantity = int(data.get("quantity", 1))
    return jsonify(engine.place_order(commodity=commodity, side=side, quantity=quantity))


@app.route("/api/mcx/exit", methods=["POST"])
def api_mcx_exit():
    """Exits an active MCX position"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    data = request.get_json() or {}
    pos_id = data.get("pos_id", "")
    return jsonify(engine.exit_position(pos_id=pos_id, reason="MANUAL_EXIT"))


@app.route("/api/mcx/scan_now", methods=["POST"])
def api_mcx_scan_now():
    """Triggers an on-demand quantitative scan across all enabled commodities"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    return jsonify(engine.force_scan_now())


@app.route("/api/mcx/commodity/toggle", methods=["POST"])
def api_mcx_commodity_toggle():
    """Toggles auto-trading on/off for a specific commodity"""
    engine = _state.get("mcx_engine")
    if not engine:
        return jsonify({"success": False, "error": "MCX engine not initialized"})
    data = request.get_json() or {}
    commodity = data.get("commodity", "")
    enabled = bool(data.get("enabled", True))
    return jsonify(engine.update_commodity_config(commodity, {"enabled": enabled}))


# Legacy bot routes wired to algo engine
@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    engine = _state.get("algo_engine")
    if engine:
        res = engine.start()
        _state["bot_running"] = (engine.status == "RUNNING")
        return jsonify(res)
    _state["bot_running"] = True
    return jsonify({"success": True, "message": "Bot started!"})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    engine = _state.get("algo_engine")
    if engine:
        res = engine.stop()
        _state["bot_running"] = False
        return jsonify(res)
    _state["bot_running"] = False
    return jsonify({"success": True, "message": "Bot stopped"})


# ─────────────────────────────────────────────────────────────
# MARKET DATA APIs
# ─────────────────────────────────────────────────────────────

@app.route("/api/market/gainers-losers")
def api_gainers_losers():
    """
    NSE se Top Gainers aur Losers fetch karo.
    Price filter: ₹50 - ₹20,000
    Agar live quotes nahi milti (Personal plan) toh instruments se basic data show karo.
    """
    if not _state["kite"]:
        return jsonify({"error": "Not logged in", "gainers": [], "losers": []})

    try:
        kite = _state["kite"]
        instruments = kite.instruments("NSE")

        eq_stocks = [
            inst for inst in instruments
            if inst.get("instrument_type") == "EQ"
            and inst.get("segment") == "NSE"
        ]

        if not eq_stocks:
            return jsonify({"gainers": [], "losers": [], "total": 0})

        # Live quotes try karo
        symbols = [f"NSE:{s['tradingsymbol']}" for s in eq_stocks[:500]]
        result = []

        try:
            ohlc_data = kite.ohlc(symbols)

            name_map = {s["tradingsymbol"]: s.get("name", "") for s in eq_stocks}

            for key, data in ohlc_data.items():
                symbol     = key.replace("NSE:", "")
                ltp        = data.get("last_price", 0)
                prev_close = data.get("ohlc", {}).get("close", 0)

                if ltp < 50 or ltp > 20000:
                    continue
                if prev_close <= 0:
                    continue

                change     = ltp - prev_close
                change_pct = (change / prev_close) * 100

                result.append({
                    "symbol":     symbol,
                    "name":       name_map.get(symbol, ""),
                    "ltp":        round(ltp, 2),
                    "prev_close": round(prev_close, 2),
                    "open":       round(data.get("ohlc", {}).get("open", 0), 2),
                    "high":       round(data.get("ohlc", {}).get("high", 0), 2),
                    "low":        round(data.get("ohlc", {}).get("low",  0), 2),
                    "change":     round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "volume":     data.get("volume", 0),
                })

        except Exception as quote_err:
            logger.warning(f"Live quotes failed ({quote_err}) - returning instruments only")
            return jsonify({
                "gainers": [],
                "losers":  [],
                "total":   0,
                "error":   "Live market data ke liye Kite Connect plan 'Personal' se 'Connect' pe upgrade karo. developers.kite.trade pe jaao.",
                "plan_issue": True,
            })

        gainers = sorted([s for s in result if s["change_pct"] > 0],
                         key=lambda x: x["change_pct"], reverse=True)[:20]
        losers  = sorted([s for s in result if s["change_pct"] < 0],
                         key=lambda x: x["change_pct"])[:20]

        return jsonify({
            "gainers": gainers,
            "losers":  losers,
            "total":   len(result),
            "scanned": len(symbols),
        })

    except Exception as e:
        logger.error(f"Gainers/Losers error: {e}")
        return jsonify({"error": str(e), "gainers": [], "losers": []})


_prev_day_cache: dict = {}
_prev_day_cache_date: str = ""

def _get_symbol_prev_day(symbol: str, kite, token_map: dict = None) -> dict:
    """Ek symbol ke previous day high, low, close, open return karo."""
    res = _get_symbols_prev_day_batch([symbol], kite, token_map)
    return res.get(symbol, {})


def _get_symbols_prev_day_batch(symbols: list, kite, token_map: dict = None) -> dict:
    """Batch fetch previous day OHLC with fast multi-threading and daily caching."""
    global _prev_day_cache, _prev_day_cache_date
    today_str = str(date.today())
    if _prev_day_cache_date != today_str:
        _prev_day_cache.clear()
        _prev_day_cache_date = today_str

    needed = [s for s in symbols if s not in _prev_day_cache]
    if needed and kite and token_map:
        to_d = datetime.now(IST_tz)
        from_d = to_d - timedelta(days=6)

        def _fetch_one(sym):
            token = token_map.get(sym)
            if not token:
                return sym, {}
            try:
                recs = kite.historical_data(token, from_d, to_d, "day")
                if recs and len(recs) >= 1:
                    last_rec = recs[-1]
                    rec_date = last_rec["date"].date() if hasattr(last_rec["date"], "date") else str(last_rec["date"])[:10]
                    if str(rec_date) == today_str and len(recs) >= 2:
                        prev_rec = recs[-2]
                    else:
                        prev_rec = last_rec

                    p_high = float(prev_rec["high"])
                    p_low = float(prev_rec["low"])
                    p_close = float(prev_rec["close"])
                    p_open = float(prev_rec["open"])
                    p_range = max(0.0, p_high - p_low)
                    p_body = abs(p_close - p_open)
                    b_ratio = round((p_body / p_range * 100), 1) if p_range > 0 else 100.0

                    return sym, {
                        "high": p_high,
                        "low": p_low,
                        "close": p_close,
                        "open": p_open,
                        "range": round(p_range, 2),
                        "body": round(p_body, 2),
                        "body_ratio": b_ratio,
                    }
            except Exception:
                pass
            return sym, {}

        # Parallel fetch for high speed
        workers = min(20, max(1, len(needed)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = executor.map(_fetch_one, needed)
            for sym, data in results:
                if data:
                    _prev_day_cache[sym] = data

    return {s: _prev_day_cache.get(s, {}) for s in symbols}


@app.route("/api/market/stocks")
def api_market_stocks():
    """
    Enhanced All Stocks & Base Candle Breakout Screener API.
    Identifies previous day base candles and live high/low breakouts / approaching breakouts.
    """
    if not _state["kite"]:
        return jsonify({"error": "Not logged in", "stocks": [], "total": 0})

    universe       = request.args.get("universe", "fno").lower().strip()
    status_filter  = request.args.get("status_filter", "all_triggers").lower().strip()
    base_only      = request.args.get("base_only", "true").lower() == "true"
    max_body_pct   = float(request.args.get("max_body", 50.0))
    near_pct       = float(request.args.get("near_pct", 0.6))
    min_price      = float(request.args.get("min", 50))
    max_price      = float(request.args.get("max", 20000))
    sort_by        = request.args.get("sort", "status_desc")
    search_q       = request.args.get("q", "").upper().strip()

    try:
        kite        = _state["kite"]
        instruments = kite.instruments("NSE")

        token_map = {
            inst["tradingsymbol"]: inst["instrument_token"]
            for inst in instruments
            if inst.get("segment") == "NSE" and inst.get("instrument_type") == "EQ"
        }
        name_map = {
            inst["tradingsymbol"]: inst.get("name", "")
            for inst in instruments
            if inst.get("segment") == "NSE" and inst.get("instrument_type") == "EQ"
        }

        # Resolve universe
        fno_set = _get_fno_symbols(kite)
        if universe == "fno":
            target_symbols = sorted(list(fno_set))
        elif universe == "all_stocks" or universe == "all_nse":
            target_symbols = [
                inst["tradingsymbol"] for inst in instruments
                if inst.get("segment") == "NSE" and inst.get("instrument_type") == "EQ"
            ]
        elif universe in ("nifty50", "nifty100", "nifty500", "watchlist"):
            target_symbols = _resolve_symbols(universe)
        else:
            target_symbols = sorted(list(fno_set))

        # Filter by search term before query
        if search_q:
            target_symbols = [
                s for s in target_symbols
                if search_q in s.upper() or search_q in name_map.get(s, "").upper()
            ]

        # Fetch today's OHLC in batches
        all_results = []
        has_live_data = True
        batch_size = 500
        stocks_to_fetch = target_symbols[:2500]

        ohlc_all = {}
        for i in range(0, len(stocks_to_fetch), batch_size):
            batch = stocks_to_fetch[i : i + batch_size]
            syms_req = [f"NSE:{s}" for s in batch]
            try:
                batch_ohlc = kite.ohlc(syms_req)
                ohlc_all.update(batch_ohlc)
            except Exception as batch_err:
                logger.warning(f"Screener OHLC batch {i} failed: {batch_err}")
                has_live_data = False
                break

        # Candidate symbols within price bounds
        candidate_syms = []
        for key, data in ohlc_all.items():
            sym = key.replace("NSE:", "")
            ltp = data.get("last_price", 0)
            if ltp > 0:
                if not search_q and (ltp < min_price or ltp > max_price):
                    continue
                candidate_syms.append(sym)

        # Batch fetch previous day OHLC for candidates
        prev_data_map = _get_symbols_prev_day_batch(candidate_syms, kite, token_map)

        summary_counts = {
            "total_scanned": len(candidate_syms),
            "base_candles_count": 0,
            "high_breakouts_count": 0,
            "near_high_count": 0,
            "low_breakdown_count": 0,
            "near_low_count": 0,
            "all_triggers_count": 0,
            "all_stocks_count": len(candidate_syms),
        }

        for sym in candidate_syms:
            data = ohlc_all.get(f"NSE:{sym}", {})
            ltp = data.get("last_price", 0)
            ohlc_d = data.get("ohlc", {})
            open_p = ohlc_d.get("open", 0)
            high_p = ohlc_d.get("high", 0)
            low_p = ohlc_d.get("low", 0)
            prev_close_ohlc = ohlc_d.get("close", 0) or ltp

            prev_info = prev_data_map.get(sym, {})
            p_high_raw = float(prev_info.get("high", 0.0) or 0.0)
            p_low_raw  = float(prev_info.get("low", 0.0) or 0.0)
            p_close_raw = float(prev_info.get("close", 0.0) or 0.0)
            p_open_raw  = float(prev_info.get("open", 0.0) or 0.0)

            if p_high_raw > 0 and p_low_raw > 0 and p_high_raw >= p_low_raw:
                prev_high = p_high_raw
                prev_low  = p_low_raw
                prev_close = p_close_raw if p_close_raw > 0 else prev_close_ohlc
                prev_open  = p_open_raw if p_open_raw > 0 else prev_close
                prev_range = max(0.01, prev_high - prev_low)
                prev_body  = abs(prev_close - prev_open)
                body_ratio_pct = round((prev_body / prev_range * 100), 1)
            else:
                # Synthetic estimation when historical API is unavailable
                prev_close = prev_close_ohlc if prev_close_ohlc > 0 else ltp
                prev_range = max(1.0, prev_close * 0.018)
                prev_high  = round(prev_close + prev_range * 0.55, 2)
                prev_low   = round(prev_close - prev_range * 0.45, 2)
                prev_open  = round(prev_close + prev_range * 0.10, 2)
                prev_body  = abs(prev_close - prev_open)
                body_ratio_pct = round((prev_body / prev_range * 100), 1)

            # Base Candle check (Body <= max_body_pct of Range)
            is_base = bool(body_ratio_pct <= max_body_pct)
            if is_base:
                summary_counts["base_candles_count"] += 1

            if body_ratio_pct <= 20.0:
                base_type = "Doji Base"
            elif body_ratio_pct <= 35.0:
                base_type = "Tight Base"
            elif body_ratio_pct <= 50.0:
                base_type = "Base Candle"
            else:
                base_type = "Expansion"

            # Change %
            if prev_close > 0 and ltp > 0:
                change = ltp - prev_close
                change_pct = (change / prev_close) * 100.0
            else:
                change = change_pct = 0.0

            # ── Breakout & Approaching Evaluation ──
            status = "INSIDE_BASE" if is_base else "NORMAL"
            status_label = "📦 Inside Base" if is_base else "Normal"
            break_level = prev_high
            distance_pct = 0.0
            trigger_score = 0  # For sorting priority

            # 1. High Breakout (LTP or High crossed PDH or positive momentum)
            if prev_high > 0 and (ltp >= prev_high or high_p >= prev_high or change_pct >= 0.75):
                status = "HIGH_BREAKOUT"
                status_label = "🔥 High Breakout"
                break_level = prev_high
                distance_pct = round((ltp - prev_high) / prev_high * 100.0, 2)
                trigger_score = 100
                summary_counts["high_breakouts_count"] += 1
                summary_counts["all_triggers_count"] += 1

            # 2. Near High Break (LTP below PDH and within near_pct)
            elif prev_high > 0 and ltp < prev_high and ((prev_high - ltp) / prev_high * 100.0) <= near_pct:
                dist_to_high = round((prev_high - ltp) / prev_high * 100.0, 2)
                status = "NEAR_HIGH"
                status_label = "⚡ Near High Break"
                break_level = prev_high
                distance_pct = -dist_to_high
                trigger_score = 80 - dist_to_high
                summary_counts["near_high_count"] += 1
                summary_counts["all_triggers_count"] += 1

            # 3. Low Breakdown (LTP or Low crossed PDL or negative momentum)
            elif prev_low > 0 and (ltp <= prev_low or low_p <= prev_low or change_pct <= -0.75):
                status = "LOW_BREAKDOWN"
                status_label = "🔻 Low Breakdown"
                break_level = prev_low
                distance_pct = round((prev_low - ltp) / prev_low * 100.0, 2)
                trigger_score = 90
                summary_counts["low_breakdown_count"] += 1
                summary_counts["all_triggers_count"] += 1

            # 4. Near Low Break (LTP above PDL and within near_pct)
            elif prev_low > 0 and ltp > prev_low and ((ltp - prev_low) / prev_low * 100.0) <= near_pct:
                dist_to_low = round((ltp - prev_low) / prev_low * 100.0, 2)
                status = "NEAR_LOW"
                status_label = "⚠️ Near Low Break"
                break_level = prev_low
                distance_pct = -dist_to_low
                trigger_score = 70 - dist_to_low
                summary_counts["near_low_count"] += 1
                summary_counts["all_triggers_count"] += 1

            item = {
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "ltp": round(ltp, 2),
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "prev_close": round(prev_close, 2),
                "prev_high": round(prev_high, 2),
                "prev_low": round(prev_low, 2),
                "prev_open": round(prev_open, 2),
                "prev_body": round(prev_body, 2),
                "prev_range": round(prev_range, 2),
                "body_ratio_pct": body_ratio_pct,
                "is_base_candle": is_base,
                "base_type": base_type,
                "status": status,
                "status_label": status_label,
                "break_level": round(break_level, 2),
                "distance_pct": distance_pct,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "is_fno": bool(sym in fno_set),
                "trigger_score": trigger_score,
            }

            # Filter checks
            # 1. Base only filter (only when requested explicitly)
            if base_only and not is_base and status_filter in ("all_base",):
                continue

            # 2. Status filter
            if status_filter == "all_triggers":
                if status not in ("HIGH_BREAKOUT", "NEAR_HIGH", "LOW_BREAKDOWN", "NEAR_LOW", "INSIDE_BASE"):
                    continue
            elif status_filter == "high_break":
                if status != "HIGH_BREAKOUT":
                    continue
            elif status_filter == "near_high":
                if status != "NEAR_HIGH":
                    continue
            elif status_filter == "low_break":
                if status != "LOW_BREAKDOWN":
                    continue
            elif status_filter == "near_low":
                if status != "NEAR_LOW":
                    continue
            elif status_filter == "all_base":
                if not is_base:
                    continue
            # "all" passes everything

            all_results.append(item)

        # Fallback: if all_results empty due to strict filters, include candidate stocks
        if not all_results and candidate_syms:
            for sym in candidate_syms:
                data = ohlc_all.get(f"NSE:{sym}", {})
                ltp = data.get("last_price", 0)
                ohlc_d = data.get("ohlc", {})
                prev_close = ohlc_d.get("close", 0) or ltp
                change = ltp - prev_close if prev_close > 0 else 0
                change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                all_results.append({
                    "symbol": sym,
                    "name": name_map.get(sym, sym),
                    "ltp": round(ltp, 2),
                    "open": round(ohlc_d.get("open", 0), 2),
                    "high": round(ohlc_d.get("high", 0), 2),
                    "low": round(ohlc_d.get("low", 0), 2),
                    "prev_close": round(prev_close, 2),
                    "prev_high": round(prev_close * 1.01, 2),
                    "prev_low": round(prev_close * 0.99, 2),
                    "prev_open": round(prev_close, 2),
                    "prev_body": 0,
                    "prev_range": round(prev_close * 0.02, 2),
                    "body_ratio_pct": 30.0,
                    "is_base_candle": True,
                    "base_type": "Tight Base",
                    "status": "HIGH_BREAKOUT" if change_pct >= 0 else "LOW_BREAKDOWN",
                    "status_label": "🔥 High Breakout" if change_pct >= 0 else "🔻 Low Breakdown",
                    "break_level": round(prev_close * 1.01, 2),
                    "distance_pct": round(change_pct, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "is_fno": bool(sym in fno_set),
                    "trigger_score": 50,
                })

        # Sorting
        sort_map = {
            "status_desc": lambda x: (-x["trigger_score"], -abs(x["change_pct"])),
            "chg_desc":    lambda x: -x["change_pct"],
            "chg_asc":     lambda x:  x["change_pct"],
            "body_asc":    lambda x:  x["body_ratio_pct"],
            "price_desc":  lambda x: -x["ltp"],
            "price_asc":   lambda x:  x["ltp"],
            "name_asc":    lambda x:  x["symbol"],
        }
        all_results.sort(key=sort_map.get(sort_by, sort_map["status_desc"]))

        logger.info(f"Base Candle Screener: {len(all_results)} matches out of {len(candidate_syms)} scanned | universe={universe}")
        return jsonify({
            "stocks":        all_results,
            "total":         len(all_results),
            "summary":       summary_counts,
            "universe":      universe,
            "has_live_data": has_live_data,
        })

    except Exception as e:
        logger.error(f"Stocks Screener Error: {e}")
        return jsonify({"error": str(e), "stocks": [], "total": 0})


@app.route("/api/chart/candles")
def api_chart_candles():
    """
    Custom Candlestick Chart Data Endpoint.
    Returns OHLCV candles, PDH, PDL, and Base Candle zones for any NSE stock.
    """
    if not _state["kite"]:
        return jsonify({"error": "Not logged in", "candles": []})

    symbol   = request.args.get("symbol", "").upper().strip()
    interval = request.args.get("interval", "day").lower().strip()

    if not symbol:
        return jsonify({"error": "Symbol required", "candles": []})

    try:
        kite = _state["kite"]
        instruments = kite.instruments("NSE")
        token = None
        for inst in instruments:
            if inst.get("tradingsymbol") == symbol and inst.get("segment") == "NSE" and inst.get("instrument_type") == "EQ":
                token = inst.get("instrument_token")
                break

        to_d = datetime.now(IST_tz)
        if interval in ("day", "1d", "d"):
            kite_interval = "day"
            from_d = to_d - timedelta(days=90)
        elif interval in ("15minute", "15m", "15"):
            kite_interval = "15minute"
            from_d = to_d - timedelta(days=12)
        elif interval in ("5minute", "5m", "5"):
            kite_interval = "5minute"
            from_d = to_d - timedelta(days=5)
        elif interval in ("minute", "1minute", "1m", "1"):
            kite_interval = "minute"
            from_d = to_d - timedelta(days=2)
        else:
            kite_interval = "day"
            from_d = to_d - timedelta(days=90)

        candles = []
        if token:
            try:
                records = kite.historical_data(token, from_d, to_d, kite_interval)
                for r in records:
                    d_str = r["date"].strftime("%Y-%m-%d %H:%M") if hasattr(r["date"], "strftime") else str(r["date"])
                    candles.append({
                        "time": d_str,
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": int(r.get("volume", 0)),
                    })
            except Exception as hist_err:
                logger.debug(f"Historical data fetch fallback for {symbol}: {hist_err}")

        # Fetch live OHLC for today
        live_ohlc = {}
        ltp = 0.0
        try:
            q = kite.ohlc([f"NSE:{symbol}"])
            if f"NSE:{symbol}" in q:
                live_ohlc = q[f"NSE:{symbol}"].get("ohlc", {})
                ltp = float(q[f"NSE:{symbol}"].get("last_price", 0.0))
        except Exception:
            pass

        # Fetch previous day data
        prev_data = _get_symbol_prev_day(symbol, kite, {symbol: token} if token else None)
        prev_high = prev_data.get("high", 0.0) or float(live_ohlc.get("close", 0.0))
        prev_low = prev_data.get("low", 0.0) or float(live_ohlc.get("close", 0.0))
        prev_open = prev_data.get("open", 0.0) or float(live_ohlc.get("close", 0.0))
        prev_close = prev_data.get("close", 0.0) or float(live_ohlc.get("close", 0.0))

        # If candles empty (e.g. historical API not enabled on Kite plan), generate synthetic recent candles from OHLC
        if not candles and ltp > 0:
            today_open = float(live_ohlc.get("open", ltp))
            today_high = float(live_ohlc.get("high", ltp))
            today_low = float(live_ohlc.get("low", ltp))
            
            # Add previous day candle
            candles.append({
                "time": (to_d - timedelta(days=1)).strftime("%Y-%m-%d"),
                "open": prev_open if prev_open > 0 else today_open,
                "high": prev_high if prev_high > 0 else max(today_high, ltp),
                "low": prev_low if prev_low > 0 else min(today_low, ltp),
                "close": prev_close if prev_close > 0 else today_open,
                "volume": 500000,
            })
            # Add today's candle
            candles.append({
                "time": to_d.strftime("%Y-%m-%d"),
                "open": today_open,
                "high": today_high,
                "low": today_low,
                "close": ltp,
                "volume": 850000,
            })

        return jsonify({
            "symbol": symbol,
            "interval": kite_interval,
            "candles": candles,
            "ltp": ltp,
            "prev_day": {
                "high": prev_high,
                "low": prev_low,
                "open": prev_open,
                "close": prev_close,
                "range": round(prev_high - prev_low, 2),
                "body": round(abs(prev_close - prev_open), 2),
                "body_ratio": prev_data.get("body_ratio", 0.0),
            }
        })
    except Exception as e:
        logger.error(f"Candles endpoint error for {symbol}: {e}")
        return jsonify({"error": str(e), "candles": []})


NSE_FNO_SYMBOLS = {
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT",
    "ADANIPORTS", "ALKEM", "AMBUJACEM", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY",
    "ASIANPAINT", "ASTRAL", "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BALRAMCHIN",
    "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", "BHARATFORG",
    "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSOFT", "CANBK",
    "CANFINHOME", "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE",
    "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR",
    "DALBHARAT", "DEEPAKNTR", "DELHIVERY", "DIVISLAB", "DIXON", "DLF", "DRREDDY",
    "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK",
    "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM",
    "FLUOROCHEM", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDPETRO", "HINDUNILVR", "ICICIBANK", "ICICIGI",
    "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM",
    "INDIAMART", "INDIANB", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC",
    "IPCALAB", "IRCTC", "ITC", "JINDALSTEL", "JKCEMENT", "JSWENERGY",
    "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN",
    "LT", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN", "MANAPPURAM", "MARICO",
    "MARUTI", "UNITDSPR", "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON",
    "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR",
    "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PIRAMALFIN",
    "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB",
    "POWERGRID", "PRESTIGE", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD",
    "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN",
    "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", "TATACOMM",
    "TATACONSUM", "TMCV", "TMPV", "TATAPOWER", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "TORNTPHARM", "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL",
    "ULTRACEMCO", "UNIONBANK", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZYDUSLIFE"
}

_fno_symbols_cache = set()
_fno_symbols_cache_time = None

def _get_fno_symbols(kite=None) -> set:
    """Returns set of NSE Equity tradingsymbols that have active F&O contracts."""
    global _fno_symbols_cache, _fno_symbols_cache_time
    now = datetime.now()
    if _fno_symbols_cache and _fno_symbols_cache_time and (now - _fno_symbols_cache_time).total_seconds() < 86400:
        return _fno_symbols_cache

    fno_set = set(NSE_FNO_SYMBOLS)
    if kite:
        try:
            nfo_instruments = kite.instruments("NFO")
            nse_instruments = kite.instruments("NSE")
            valid_nse_eq = {
                inst.get("tradingsymbol", "").strip().upper()
                for inst in nse_instruments
                if inst.get("instrument_type") == "EQ" and inst.get("tradingsymbol")
            }
            indices = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTYFPI", "NIFTYIT"}
            dyn_symbols = {
                inst.get("name", "").strip().upper()
                for inst in nfo_instruments
                if inst.get("name") and inst.get("name").strip().upper() not in indices
            }
            # Only include dynamic symbols that actually exist as NSE EQ instruments
            valid_dyn = {s for s in dyn_symbols if s in valid_nse_eq}
            if len(valid_dyn) > 20:
                fno_set.update(valid_dyn)
                logger.info(f"Loaded {len(fno_set)} active F&O equity underlyings from Kite NFO")
        except Exception as e:
            logger.debug(f"Kite NFO instruments fetch skipped/failed: {e}")

    _fno_symbols_cache = fno_set
    _fno_symbols_cache_time = now
    return _fno_symbols_cache


@app.route("/api/market/reversals")
def api_market_reversals():
    """
    Open Reversals Screener API:
    - Up Side: Stock opened -> dipped below Open (Low < Open) -> reversed and is now trading ABOVE Open (LTP > Open).
    - Down Side: Stock opened -> rallied above Open (High > Open) -> reversed and is now trading BELOW Open (LTP < Open).
    """
    if not _state["kite"]:
        return jsonify({
            "success": False,
            "error": "Not logged in",
            "up_side": [],
            "down_side": [],
            "total_up": 0,
            "total_down": 0,
            "scanned": 0,
        })

    universe   = request.args.get("universe", "all_stocks").strip()
    min_dip    = float(request.args.get("min_dip", 0.1))     # min % dip below open
    min_rally  = float(request.args.get("min_rally", 0.1))   # min % rally above open
    min_price  = float(request.args.get("min_price", 20))
    max_price  = float(request.args.get("max_price", 50000))

    try:
        kite = _state["kite"]
        symbols = _resolve_symbols(universe)
        if not symbols:
            symbols = _resolve_symbols("nifty50")

        # Name lookup map and token map
        name_map = {}
        token_map = {}
        try:
            instruments = kite.instruments("NSE")
            for inst in instruments:
                sym = inst.get("tradingsymbol")
                nm = inst.get("name")
                tok = inst.get("instrument_token")
                if sym:
                    if nm: name_map[sym] = nm
                    if tok: token_map[sym] = tok
        except Exception:
            pass

        # F&O symbol lookup
        fno_set = _get_fno_symbols(kite)

        # Batch symbols in chunks of 500
        batch_size = 500
        ohlc_all = {}
        formatted_symbols = [f"NSE:{s}" if ":" not in s else s for s in symbols]

        for i in range(0, len(formatted_symbols), batch_size):
            chunk = formatted_symbols[i:i + batch_size]
            try:
                data = kite.ohlc(chunk)
                if data:
                    ohlc_all.update(data)
            except Exception as be:
                logger.warning(f"Reversals OHLC batch error: {be}")

        up_side = []
        down_side = []

        for key, item in ohlc_all.items():
            sym = key.replace("NSE:", "")
            ltp = float(item.get("last_price", 0) or 0)
            ohlc = item.get("ohlc", {}) or {}
            open_p = float(ohlc.get("open", 0) or 0)
            high_p = float(ohlc.get("high", 0) or 0)
            low_p  = float(ohlc.get("low", 0) or 0)
            prev_close = float(ohlc.get("close", 0) or 0)

            # Skip invalid prices or out of price filter
            if open_p <= 0 or ltp <= 0 or high_p <= 0 or low_p <= 0:
                continue
            if ltp < min_price or ltp > max_price:
                continue

            day_chg_amt = ltp - prev_close if prev_close > 0 else 0
            day_chg_pct = (day_chg_amt / prev_close * 100) if prev_close > 0 else 0
            rng = high_p - low_p
            is_fno = bool(sym in fno_set)

            # ─────────────────────────────────────────────────────────
            # 1. UP SIDE (Open -> Dip Below Open -> Reversed Above Open)
            # ─────────────────────────────────────────────────────────
            if low_p < open_p and ltp > open_p:
                dip_amt = open_p - low_p
                dip_pct = (dip_amt / open_p) * 100
                if dip_pct >= min_dip:
                    gain_vs_open_amt = ltp - open_p
                    gain_vs_open_pct = (gain_vs_open_amt / open_p) * 100
                    recovery_from_low_amt = ltp - low_p
                    recovery_from_low_pct = (recovery_from_low_amt / low_p) * 100
                    rev_strength = round((ltp - low_p) / rng * 100, 1) if rng > 0 else 50.0

                    # Previous Day High / Low
                    prev_data = _get_symbol_prev_day(sym, kite, token_map)
                    prev_high = prev_data.get("high", 0.0)
                    prev_low  = prev_data.get("low", 0.0)
                    benchmark_p = prev_high if prev_high > 0 else prev_close

                    crossed_break = bool(benchmark_p > 0 and ltp >= benchmark_p)
                    near_break = False
                    break_dist_pct = 0.0
                    if benchmark_p > 0:
                        if crossed_break:
                            break_dist_pct = round((ltp - benchmark_p) / benchmark_p * 100, 2)
                        else:
                            dist = benchmark_p - ltp
                            break_dist_pct = round((dist / benchmark_p) * 100, 2)
                            if 0 < break_dist_pct <= 0.45:
                                near_break = True

                    crossed_prev_day = crossed_break or bool(prev_close > 0 and low_p <= prev_close and ltp > prev_close)
                    is_above_prev_day = bool(prev_close > 0 and ltp > prev_close)
                    prev_diff_pct = round((ltp - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0

                    up_side.append({
                        "symbol": sym,
                        "name": name_map.get(sym, sym),
                        "ltp": round(ltp, 2),
                        "open": round(open_p, 2),
                        "high": round(high_p, 2),
                        "low": round(low_p, 2),
                        "prev_close": round(prev_close, 2),
                        "prev_high": round(prev_high, 2) if prev_high > 0 else round(prev_close, 2),
                        "prev_low": round(prev_low, 2) if prev_low > 0 else round(prev_close, 2),
                        "dip_amt": round(dip_amt, 2),
                        "dip_pct": round(dip_pct, 2),
                        "gain_vs_open_amt": round(gain_vs_open_amt, 2),
                        "gain_vs_open_pct": round(gain_vs_open_pct, 2),
                        "recovery_from_low_amt": round(recovery_from_low_amt, 2),
                        "recovery_from_low_pct": round(recovery_from_low_pct, 2),
                        "day_change_amt": round(day_chg_amt, 2),
                        "day_change_pct": round(day_chg_pct, 2),
                        "change_pct": round(day_chg_pct, 2),
                        "crossed_prev_day": crossed_prev_day,
                        "is_above_prev_day": is_above_prev_day,
                        "prev_diff_pct": prev_diff_pct,
                        "near_break": near_break,
                        "crossed_break": crossed_break,
                        "break_level": round(benchmark_p, 2),
                        "break_dist_pct": break_dist_pct,
                        "is_fno": is_fno,
                        "volume": int(item.get("volume", 0) or 0),
                        "rev_strength": rev_strength,
                    })

            # ─────────────────────────────────────────────────────────
            # 2. DOWN SIDE (Open -> Rally Above Open -> Reversed Below Open)
            # ─────────────────────────────────────────────────────────
            elif high_p > open_p and ltp < open_p:
                rally_amt = high_p - open_p
                rally_pct = (rally_amt / open_p) * 100
                if rally_pct >= min_rally:
                    drop_vs_open_amt = open_p - ltp
                    drop_vs_open_pct = (drop_vs_open_amt / open_p) * 100
                    fall_from_high_amt = high_p - ltp
                    fall_from_high_pct = (fall_from_high_amt / high_p) * 100
                    rev_strength = round((high_p - ltp) / rng * 100, 1) if rng > 0 else 50.0

                    # Previous Day High / Low
                    prev_data = _get_symbol_prev_day(sym, kite, token_map)
                    prev_high = prev_data.get("high", 0.0)
                    prev_low  = prev_data.get("low", 0.0)
                    benchmark_p = prev_low if prev_low > 0 else prev_close

                    crossed_break = bool(benchmark_p > 0 and ltp <= benchmark_p)
                    near_break = False
                    break_dist_pct = 0.0
                    if benchmark_p > 0:
                        if crossed_break:
                            break_dist_pct = round((benchmark_p - ltp) / benchmark_p * 100, 2)
                        else:
                            dist = ltp - benchmark_p
                            break_dist_pct = round((dist / benchmark_p) * 100, 2)
                            if 0 < break_dist_pct <= 0.45:
                                near_break = True

                    crossed_prev_day = crossed_break or bool(prev_close > 0 and high_p >= prev_close and ltp < prev_close)
                    is_below_prev_day = bool(prev_close > 0 and ltp < prev_close)
                    prev_diff_pct = round((ltp - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0

                    down_side.append({
                        "symbol": sym,
                        "name": name_map.get(sym, sym),
                        "ltp": round(ltp, 2),
                        "open": round(open_p, 2),
                        "high": round(high_p, 2),
                        "low": round(low_p, 2),
                        "prev_close": round(prev_close, 2),
                        "prev_high": round(prev_high, 2) if prev_high > 0 else round(prev_close, 2),
                        "prev_low": round(prev_low, 2) if prev_low > 0 else round(prev_close, 2),
                        "rally_amt": round(rally_amt, 2),
                        "rally_pct": round(rally_pct, 2),
                        "drop_vs_open_amt": round(drop_vs_open_amt, 2),
                        "drop_vs_open_pct": round(drop_vs_open_pct, 2),
                        "fall_from_high_amt": round(fall_from_high_amt, 2),
                        "fall_from_high_pct": round(fall_from_high_pct, 2),
                        "day_change_amt": round(day_chg_amt, 2),
                        "day_change_pct": round(day_chg_pct, 2),
                        "change_pct": round(day_chg_pct, 2),
                        "crossed_prev_day": crossed_prev_day,
                        "is_below_prev_day": is_below_prev_day,
                        "prev_diff_pct": prev_diff_pct,
                        "near_break": near_break,
                        "crossed_break": crossed_break,
                        "break_level": round(benchmark_p, 2),
                        "break_dist_pct": break_dist_pct,
                        "is_fno": is_fno,
                        "volume": int(item.get("volume", 0) or 0),
                        "rev_strength": rev_strength,
                    })

        up_side.sort(key=lambda x: -x["recovery_from_low_pct"])
        down_side.sort(key=lambda x: -x["fall_from_high_pct"])

        up_crossed_count = sum(1 for x in up_side if x.get("crossed_break") or x.get("crossed_prev_day"))
        down_crossed_count = sum(1 for x in down_side if x.get("crossed_break") or x.get("crossed_prev_day"))
        up_near_count = sum(1 for x in up_side if x.get("near_break"))
        down_near_count = sum(1 for x in down_side if x.get("near_break"))
        up_fno_count = sum(1 for x in up_side if x.get("is_fno"))
        down_fno_count = sum(1 for x in down_side if x.get("is_fno"))
        total_fno_count = up_fno_count + down_fno_count

        return jsonify({
            "success": True,
            "universe": universe,
            "scanned": len(ohlc_all),
            "total_scanned": len(ohlc_all),
            "total_up": len(up_side),
            "total_down": len(down_side),
            "up_count": len(up_side),
            "down_count": len(down_side),
            "up_crossed_count": up_crossed_count,
            "down_crossed_count": down_crossed_count,
            "up_near_count": up_near_count,
            "down_near_count": down_near_count,
            "up_fno_count": up_fno_count,
            "down_fno_count": down_fno_count,
            "total_fno_count": total_fno_count,
            "up_side": up_side,
            "down_side": down_side,
            "timestamp": datetime.now(IST_tz).strftime("%I:%M:%S %p"),
        })

    except Exception as e:
        logger.error(f"Reversals error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "up_side": [],
            "down_side": [],
            "total_up": 0,
            "total_down": 0,
            "scanned": 0,
        })


@app.route("/api/watchlist/add", methods=["POST"])
def api_watchlist_add():
    """Symbol ko persistent watchlist mein add karo"""
    body   = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").upper().strip()

    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"})

    symbols = _get_watchlist_symbols()
    if symbol in symbols:
        return jsonify({"success": False, "error": f"{symbol} already in watchlist"})

    symbols.append(symbol)
    _save_watchlist_symbols(symbols)
    INTRADAY_CONFIG["watchlist"] = symbols

    # Auto subscribe to ticker if connected
    ticker = _state.get("ticker")
    if ticker and getattr(ticker, "is_connected", False):
        try:
            ticker.subscribe([symbol], exchange="NSE")
        except Exception:
            pass

    logger.info(f"Added to persistent watchlist: {symbol}")
    return jsonify({"success": True, "symbol": symbol, "watchlist": symbols})


@app.route("/api/watchlist/delete", methods=["POST"])
def api_watchlist_delete():
    """Symbol ko persistent watchlist se remove karo"""
    body   = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").upper().strip()

    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"})

    symbols = _get_watchlist_symbols()
    if symbol not in symbols:
        return jsonify({"success": False, "error": f"{symbol} not in watchlist"})

    symbols = [s for s in symbols if s != symbol]
    _save_watchlist_symbols(symbols)
    INTRADAY_CONFIG["watchlist"] = symbols
    logger.info(f"Removed from persistent watchlist: {symbol}")
    return jsonify({"success": True, "symbol": symbol, "watchlist": symbols})


# ─────────────────────────────────────────────────────────────
# SCANNER APIs
# ─────────────────────────────────────────────────────────────

# Scanner state - background scan track karne ke liye
_scan_state = {
    "running":    False,
    "progress":   0,
    "total":      0,
    "current":    "",
    "results":    [],
    "last_scan":  None,
    "error":      "",
    "scan_type":  "",
}


@app.route("/api/scanner/run", methods=["POST"])
def api_scanner_run():
    """
    Scanner background mein start karo.
    POST body: {
        "symbols":   ["RELIANCE","TCS",...] or "nifty50" / "nifty200" / "custom",
        "timeframe": "day" / "60minute" / "15minute" / "5minute",
        "min_score": 6,
        "direction": "both" / "long" / "short"
    }
    """
    if not _state["kite"]:
        return jsonify({"success": False, "error": "Pehle login karo"})

    if _scan_state["running"]:
        return jsonify({"success": False, "error": "Scan already chal raha hai. Wait karo."})

    body      = request.get_json(silent=True) or {}
    timeframe = body.get("timeframe", "day")
    min_score = int(body.get("min_score", 6))
    direction = body.get("direction", "both")
    symbols_q = body.get("symbols", "nifty50")

    # Symbol list resolve karo
    symbols = _resolve_symbols(symbols_q)
    if not symbols:
        return jsonify({"success": False, "error": "Koi symbol nahi mila"})

    # Background thread mein start karo
    def _run():
        try:
            from scanner import BulkScanner
            _scan_state["running"]   = True
            _scan_state["progress"]  = 0
            _scan_state["total"]     = len(symbols)
            _scan_state["results"]   = []
            _scan_state["error"]     = ""
            _scan_state["scan_type"] = f"{len(symbols)} stocks | {timeframe}"
            _scan_state["current"]   = "Starting..."

            def progress_cb(done, total, sym, current_results=None):
                _scan_state["progress"] = done
                _scan_state["current"]  = sym
                if current_results is not None:
                    filtered = current_results
                    if direction == "long":
                        filtered = [r for r in filtered if r.direction == "LONG"]
                    elif direction == "short":
                        filtered = [r for r in filtered if r.direction == "SHORT"]
                    _scan_state["results"] = [r.to_dict() for r in filtered]

            def stop_check():
                return not _scan_state["running"]

            bulk    = BulkScanner(_state["kite"])
            results = bulk.scan_symbols(
                symbols     = symbols,
                timeframe   = timeframe,
                days        = 200 if timeframe == "day" else 30,
                min_score   = min_score,
                progress_cb = progress_cb,
                stop_check  = stop_check,
            )

            # Direction filter
            if direction == "long":
                results = [r for r in results if r.direction == "LONG"]
            elif direction == "short":
                results = [r for r in results if r.direction == "SHORT"]

            _scan_state["results"]  = [r.to_dict() for r in results]
            _scan_state["last_scan"] = datetime.now(IST_tz).strftime("%H:%M:%S %d-%b")
            logger.info(f"Scan complete: {len(results)} signals found")

        except Exception as e:
            _scan_state["error"] = str(e)
            logger.error(f"Scanner error: {e}")
        finally:
            _scan_state["running"] = False
            if _scan_state["current"] != "Cancelled by user":
                _scan_state["current"] = "Done"

    threading.Thread(target=_run, daemon=True).start()

    return jsonify({
        "success":  True,
        "total":    len(symbols),
        "message":  f"Scanning {len(symbols)} stocks...",
    })


@app.route("/api/scanner/status")
def api_scanner_status():
    """Scanner ka current progress"""
    pct = 0
    if _scan_state["total"] > 0:
        pct = round(_scan_state["progress"] / _scan_state["total"] * 100)

    return jsonify({
        "running":   _scan_state["running"],
        "progress":  _scan_state["progress"],
        "total":     _scan_state["total"],
        "pct":       pct,
        "current":   _scan_state["current"],
        "results":   _scan_state["results"],
        "count":     len(_scan_state["results"]),
        "last_scan": _scan_state["last_scan"],
        "error":     _scan_state["error"],
        "scan_type": _scan_state["scan_type"],
    })


@app.route("/api/scanner/cancel", methods=["POST"])
def api_scanner_cancel():
    """Cancel running scan"""
    _scan_state["running"] = False
    _scan_state["current"] = "Cancelled by user"
    logger.info("Scanner cancelled")
    return jsonify({"success": True, "message": "Scan cancelled"})


@app.route("/api/scanner/analyse", methods=["POST"])
def api_scanner_analyse():
    """
    Single stock ka quick analysis karo.
    POST: {"symbol": "RELIANCE", "timeframe": "day"}
    """
    if not _state["kite"]:
        return jsonify({"success": False, "error": "Not logged in"})

    body      = request.get_json(silent=True) or {}
    symbol    = body.get("symbol", "").upper().strip()
    timeframe = body.get("timeframe", "day")
    min_score = int(body.get("min_score", 1))

    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"})

    try:
        from scanner import BulkScanner
        bulk = BulkScanner(_state["kite"])
        df   = bulk._fetch_data(symbol, timeframe, days=200)

        if df is None or df.empty:
            return jsonify({
                "success": False,
                "error": f"{symbol} ka data nahi mila. "
                         "Historical data ke liye Connect plan chahiye."
            })

        from scanner import StockScanner
        sc     = StockScanner()
        result = sc.analyse(symbol, "", df, timeframe, min_score=min_score)

        if result:
            return jsonify({"success": True, "signal": result.to_dict()})
        else:
            return jsonify({
                "success":  False,
                "no_signal": True,
                "error":    f"{symbol} mein abhi koi strong signal nahi hai. "
                            f"Score threshold meet nahi hua."
            })

    except Exception as e:
        logger.error(f"Single analyse error {symbol}: {e}")
        return jsonify({"success": False, "error": str(e)})


_cached_all_nse_symbols: list = []

def _resolve_symbols(query) -> list:
    """
    Symbol query ko actual symbols list mein convert karo.
    Supports: "all_stocks", "all_nse", "nifty500", "all_sectors", index names, sector names, custom list
    """
    global _cached_all_nse_symbols

    if isinstance(query, list):
        return [s.upper().strip() for s in query if s.strip()]

    # ── All Index Symbol Lists ────────────────────────────────
    NIFTY_50 = [
        "RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","HINDUNILVR",
        "ITC","SBIN","BHARTIARTL","KOTAKBANK","LT","BAJFINANCE",
        "HCLTECH","MARUTI","SUNPHARMA","TITAN","ADANIPORTS","ULTRACEMCO",
        "AXISBANK","WIPRO","NESTLEIND","DMART","ASIANPAINT","BAJAJFINSV",
        "POWERGRID","NTPC","TECHM","ONGC","COALINDIA","JSWSTEEL",
        "TMCV","TMPV","HINDALCO","TATASTEEL","DIVISLAB","CIPLA",
        "DRREDDY","APOLLOHOSP","BPCL","EICHERMOT","GRASIM",
        "HEROMOTOCO","INDUSINDBK","M&M","SBILIFE","HDFCLIFE",
        "BAJAJ-AUTO","BRITANNIA","UPL","VEDL","ADANIENT"
    ]
    NIFTY_NEXT_50 = [
        "ABB","ADANIGREEN","AMBUJACEM","AUROPHARMA","BANKBARODA",
        "BERGEPAINT","BOSCHLTD","CANBK","CHOLAFIN","COLPAL",
        "DABUR","DLF","GAIL","GODREJCP","HAVELLS","ICICIPRULI",
        "INDIGO","IOC","IRCTC","JUBLFOOD","LUPIN","MARICO",
        "UNITDSPR","MUTHOOTFIN","NAUKRI","NMDC","PAGEIND",
        "PETRONET","PIDILITIND","RECLTD","SAIL","SIEMENS","SRF",
        "TATACONSUM","TATAPOWER","TORNTPHARM","TRENT","TVSMOTOR",
        "UBL","UNIONBANK","VBL","VOLTAS","ZYDUSLIFE",
        "IDFCFIRSTB","GODREJPROP","TRIDENT","WHIRLPOOL"
    ]
    NIFTY_MIDCAP50 = [
        "ABCAPITAL","ALKEM","APLLTD","ASTRAL","BALKRISIND",
        "BATAINDIA","BSOFT","CANFINHOME","CDSL","COFORGE",
        "CROMPTON","CUMMINSIND","DEEPAKNTR","DIXON","EMAMILTD",
        "ESCORTS","EXIDEIND","FEDERALBNK","GLENMARK","HAL",
        "IBULHSGFIN","IGL","INDHOTEL","IPCALAB","JKCEMENT",
        "JUBILANT","KAJARIACER","KPITTECH","LAURUSLABS","LICHSGFIN",
        "MANAPPURAM","MRF","NBCC","PERSISTENT","PHOENIXLTD",
        "POLYCAB","RAMCOCEM","ROUTE","SBICARD","SUPREMEIND",
        "TATAELXSI","THERMAX","TORNTPOWER","TVSMOTOR","UJJIVANSFB",
        "VARROC","VGUARD","ZOMATO","NAUKRI","AAVAS"
    ]
    NIFTY_MIDCAP150 = [
        "AAVAS","ABCAPITAL","ABFRL","ACC","ALKEM","APLLTD",
        "ASTRAL","BALKRISIND","BANDHANBNK","BATAINDIA","BEL",
        "BHARATFORG","BIOCON","BSOFT","CANFINHOME","CDSL",
        "CESC","COFORGE","CONCOR","CROMPTON","CUMMINSIND",
        "DEEPAKNTR","DIXON","EMAMILTD","ESCORTS","EXIDEIND",
        "FEDERALBNK","GLENMARK","GNFC","GRANULES","FLUOROCHEM",
        "HAL","HONAUT","IBULHSGFIN","IGL","INDHOTEL","IPCALAB",
        "JKCEMENT","JSWENERGY","JUBILANT","KAJARIACER","KPITTECH",
        "LALPATHLAB","LAURUSLABS","LICHSGFIN","MANAPPURAM",
        "NBCC","PERSISTENT","PHOENIXLTD","POLYCAB","RAMCOCEM",
        "ROUTE","SBICARD","SUPREMEIND","SYNGENE","TATAELXSI",
        "THERMAX","TORNTPOWER","TVSMOTOR","UJJIVANSFB",
        "ZOMATO","NAUKRI","RITES","STAR","SUNDARMFIN","TATACHEM"
    ]
    NIFTY_SMALLCAP100 = [
        "AARTIDRUGS","AARTIIND","AEGISLOG","AJANTPHARM","ALKYLAMINE",
        "APTUS","ATUL","BALAMINES","BEML","BIKAJI","BLUESTARCO",
        "BRIGADE","BSE","CAMPUS","CARYSIL","CASTROLIND","CEATLTD",
        "CENTURYPLY","CLEAN","CMSINFO","DATAMATICS","DELTACORP",
        "ELGIEQUIP","EQUITASBNK","ERIS","ESABINDIA","FINEORG",
        "FLUOROCHEM","GALAXYSURF","GARFIBRES","GPIL","GRINDWELL",
        "HAPPSTMNDS","HOMEFIRST","IDFC","IIFL","INDIAMART",
        "INDIGOPNTS","INTELLECT","JBCHEPHARM","JINDALSAW","JKLAKSHMI",
        "JMFINANCIL","KFINTECH","KNRCON","KRBL","LATENTVIEW",
        "LXCHEM","MASTEK","MATRIMONY","MAZDOCK","METROPOLIS",
        "NATCOPHARM","NAVINFLUOR","NAZARA","NIACL","OFSS","PCBL",
        "PERSISTENT","PHOENIXLTD","POLYCAB","POWERINDIA","RAMCOCEM",
        "RITES","ROUTE","SCHAEFFLER","SOLARINDS","STAR","SUNDARMFIN",
        "SUPREMEIND","SYNGENE","TATACHEM","TATAELXSI","THERMAX",
        "TIMKEN","TITAGARH","TORNTPOWER","TVSMOTOR","UJJIVANSFB",
        "VAIBHAVGBL","VGUARD","VINATIORGA","ZOMATO","NAZARA"
    ]
    BANKNIFTY = [
        "HDFCBANK","ICICIBANK","KOTAKBANK","AXISBANK","SBIN",
        "INDUSINDBK","BANDHANBNK","FEDERALBNK","IDFCFIRSTB",
        "AUBANK","PNB","BANKBARODA","CANBK","UNIONBANK","INDIANB"
    ]
    FINNIFTY = [
        "HDFCBANK","ICICIBANK","KOTAKBANK","AXISBANK","SBIN",
        "BAJFINANCE","BAJAJFINSV","HDFCLIFE","SBILIFE","ICICIPRULI",
        "INDUSINDBK","MUTHOOTFIN","CHOLAFIN","RECLTD","PFC",
        "IDFCFIRSTB","MANAPPURAM","LICHSGFIN","SBICARD","M&MFIN"
    ]
    SENSEX30 = [
        "RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","HINDUNILVR",
        "ITC","SBIN","BHARTIARTL","KOTAKBANK","LT","BAJFINANCE",
        "HCLTECH","MARUTI","SUNPHARMA","TITAN","ULTRACEMCO","AXISBANK",
        "WIPRO","NESTLEIND","ASIANPAINT","BAJAJFINSV","POWERGRID",
        "NTPC","TECHM","ONGC","TMCV","TATASTEEL","INDUSINDBK","M&M"
    ]
    BSE100 = NIFTY_50 + NIFTY_NEXT_50

    # ── Sector Stocks ─────────────────────────────────────────
    SECTORS = {
        "it_technology":         ["TCS","INFY","HCLTECH","WIPRO","TECHM","LTIM","MPHASIS","COFORGE","PERSISTENT","OFSS","KPITTECH","TATAELXSI","BSOFT","MASTEK","HAPPSTMNDS","LATENTVIEW"],
        "banking":               ["HDFCBANK","ICICIBANK","KOTAKBANK","AXISBANK","SBIN","INDUSINDBK","BANDHANBNK","FEDERALBNK","IDFCFIRSTB","AUBANK","PNB","BANKBARODA","CANBK","UNIONBANK","INDIANB"],
        "financial_services":    ["BAJFINANCE","BAJAJFINSV","HDFCLIFE","SBILIFE","ICICIPRULI","MUTHOOTFIN","CHOLAFIN","RECLTD","PFC","LICHSGFIN","SBICARD","MANAPPURAM","CANFINHOME","ABCAPITAL"],
        "auto_ev":               ["MARUTI","TMCV","TMPV","M&M","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","ASHOKLEY","BOSCHLTD","MOTHERSON","EXIDEIND","BALKRISIND","ESCORTS","OLECTRA","ATHER"],
        "pharma_healthcare":     ["SUNPHARMA","DIVISLAB","CIPLA","DRREDDY","APOLLOHOSP","ALKEM","TORNTPHARM","LUPIN","AUROPHARMA","IPCALAB","BIOCON","LALPATHLAB","METROPOLIS","SYNGENE","LAURUSLABS","ZYDUSLIFE"],
        "fmcg_consumer":         ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","COLPAL","EMAMILTD","TATACONSUM","VBL","UBL","UNITDSPR","BIKAJI"],
        "oil_gas_energy":        ["RELIANCE","ONGC","BPCL","IOC","GAIL","PETRONET","HINDPETRO","NTPC","POWERGRID","TATAPOWER","ADANIPOWER","ADANIGREEN","JSWENERGY","CESC","TORNTPOWER","IGL","FLUOROCHEM"],
        "metals_mining":         ["TATASTEEL","HINDALCO","JSWSTEEL","VEDL","COALINDIA","NMDC","SAIL","HINDZINC","NATIONALUM","APLAPOLLO","GPIL","JINDALSTEL"],
        "real_estate":           ["DLF","GODREJPROP","PHOENIXLTD","BRIGADE","PRESTIGE","SOBHA","IBREALEST","MAHLIFE","OBEROIRLTY","SUNTECK","KOLTEPATIL"],
        "infrastructure_capgoods":["LT","ABB","SIEMENS","BEL","HAL","BHEL","THERMAX","CUMMINSIND","SCHAEFFLER","KEC","KALPATPOWR","NBCC","RITES","GRINDWELL"],
        "cement":                ["ULTRACEMCO","GRASIM","AMBUJACEM","ACC","SHREECEM","RAMCOCEM","JKCEMENT","JKLAKSHMI","STAR","KAJARIACER"],
        "telecom_media":         ["BHARTIARTL","IDEA","INDUSTOWER","TATACOMM","ROUTE","NETWORK18","ZEEL","HATHWAY"],
        "chemicals_specialty":   ["PIDILITIND","SRF","DEEPAKNTR","AARTIIND","NAVINFLUOR","CLEAN","FINEORG","ATUL","LXCHEM","ALKYLAMINE","GNFC","FLUOROCHEM","BALAMINES","SOLARINDS","PCBL"],
        "retail_ecommerce":      ["DMART","TRENT","NYKAA","TITAN","BATAINDIA","ABFRL","CAMPUS","VMART"],
        "defence":               ["HAL","BEL","BHEL","BEML","MIDHANI","GRSE","COCHINSHIP"],
        "new_age_tech":          ["ZOMATO","PAYTM","NYKAA","POLICYBZR","DELHIVERY","NAZARA","EASEMYTRIP","MAMAEARTH"],
    }

    INDEX_MAP = {
        "nifty50":           NIFTY_50,
        "nifty_next50":      NIFTY_NEXT_50,
        "nifty100":          NIFTY_50 + NIFTY_NEXT_50,
        "nifty_midcap50":    NIFTY_MIDCAP50,
        "nifty_midcap150":   NIFTY_MIDCAP150,
        "nifty_smallcap100": NIFTY_SMALLCAP100,
        "nifty200":          NIFTY_50 + NIFTY_NEXT_50 + NIFTY_MIDCAP150,
        "banknifty":         BANKNIFTY,
        "finnifty":          FINNIFTY,
        "sensex30":          SENSEX30,
        "bse100":            BSE100,
        "watchlist":         INTRADAY_CONFIG["watchlist"],
        "fno":               sorted(list(NSE_FNO_SYMBOLS)),
    }

    if isinstance(query, list):
        return [s.upper().strip() for s in query if s.strip()]

    q = query.lower().strip() if isinstance(query, str) else ""

    # F&O Stocks Universe
    if q in ("fno", "fno_stocks", "nifty_fno", "fno_only"):
        fno_set = _get_fno_symbols(_state.get("kite"))
        return sorted(list(fno_set))

    # All combined predefined fallback
    all_predefined = list(dict.fromkeys(
        NIFTY_50 + NIFTY_NEXT_50 + NIFTY_MIDCAP150 + NIFTY_SMALLCAP100 +
        [s for sec in SECTORS.values() for s in sec]
    ))

    # All NSE / All Stocks
    if q in ("all_stocks", "all_nse", "all"):
        if _cached_all_nse_symbols:
            return _cached_all_nse_symbols
        try:
            kite = _state.get("kite")
            if kite:
                instruments = kite.instruments("NSE")
                import re
                debt_re = re.compile(r'(-\d|-[A-Z]\d|GS\d|\d{4}|SGB)')
                clean_eq = []
                for inst in instruments:
                    if inst.get("instrument_type") != "EQ" or inst.get("segment") != "NSE":
                        continue
                    sym = (inst.get("tradingsymbol") or "").strip().upper()
                    if not sym or sym[0].isdigit() or debt_re.search(sym):
                        continue
                    if sym.endswith(("-RE", "-IV", "-RR", "-PP", "-GB")):
                        continue
                    clean_eq.append(sym)

                if clean_eq:
                    # Guarantee major market leaders (F&O stocks & Benchmark Index constituents) are scanned FIRST
                    fno_list = list(_get_fno_symbols(kite))
                    leaders = list(dict.fromkeys(fno_list + all_predefined))
                    remaining = [s for s in sorted(clean_eq) if s not in set(leaders)]
                    _cached_all_nse_symbols = leaders + remaining
                    logger.info(f"Loaded {len(_cached_all_nse_symbols)} clean NSE EQ stocks (with {len(leaders)} market leaders prioritized) for All Stocks scan")
                    return _cached_all_nse_symbols
        except Exception as e:
            logger.warning(f"Failed to fetch all NSE instruments: {e}")
        return all_predefined

    # Nifty 500
    if q == "nifty500":
        if _cached_all_nse_symbols:
            return _cached_all_nse_symbols[:500]
        try:
            kite = _state.get("kite")
            if kite:
                instruments = kite.instruments("NSE")
                eq_stocks = [
                    inst["tradingsymbol"]
                    for inst in instruments
                    if inst.get("instrument_type") == "EQ"
                    and inst.get("segment") == "NSE"
                    and inst.get("tradingsymbol")
                ]
                if eq_stocks:
                    _cached_all_nse_symbols = sorted(list(dict.fromkeys(eq_stocks)))
                    return _cached_all_nse_symbols[:500]
        except Exception:
            pass
        return all_predefined[:500] if len(all_predefined) >= 500 else all_predefined

    if q in INDEX_MAP:
        return INDEX_MAP[q]
    if q in SECTORS:
        return SECTORS[q]
    if q == "all_sectors":
        seen, result = set(), []
        for stocks in SECTORS.values():
            for s in stocks:
                if s not in seen:
                    seen.add(s); result.append(s)
        return result
    if "," in query:
        return [s.upper().strip() for s in query.split(",") if s.strip()]
    if q:
        return [q.upper()]

    return NIFTY_50




# ─────────────────────────────────────────────────────────────
# TRADING APIs - BUY / SELL / EXIT
# ─────────────────────────────────────────────────────────────

@app.route("/api/trade/place", methods=["POST"])
def api_trade_place():
    """
    Order place karo.
    POST body:
    {
        "symbol":        "RELIANCE",
        "exchange":      "NSE",
        "transaction":   "BUY" | "SELL",
        "quantity":      10,
        "order_type":    "MARKET" | "LIMIT" | "SL" | "SL-M",
        "product":       "MIS" | "CNC" | "NRML",
        "price":         0,          # 0 for MARKET
        "trigger_price": 0,          # for SL / SL-M
        "stop_loss":     0,          # optional SL order
        "target":        0,          # optional target order
        "tag":           "MANUAL"
    }
    """
    if not _state["kite"]:
        return jsonify({"success": False, "error": "Pehle login karo"})

    body = request.get_json(silent=True) or {}

    # Required fields
    symbol      = body.get("symbol",      "").upper().strip()
    exchange    = body.get("exchange",    "NSE").upper()
    transaction = body.get("transaction", "BUY").upper()
    quantity    = int(body.get("quantity", 0))
    order_type  = body.get("order_type",  "MARKET").upper()
    product     = body.get("product",     "MIS").upper()
    price       = float(body.get("price",         0))
    trig_price  = float(body.get("trigger_price", 0))
    tag         = body.get("tag", "MANUAL")[:20]

    # Validation
    if not symbol:
        return jsonify({"success": False, "error": "Symbol required hai"})
    if quantity <= 0:
        return jsonify({"success": False, "error": "Quantity 0 se zyada honi chahiye"})
    if transaction not in ("BUY", "SELL"):
        return jsonify({"success": False, "error": "Transaction BUY ya SELL hona chahiye"})
    if order_type in ("LIMIT", "SL") and price <= 0:
        return jsonify({"success": False, "error": f"{order_type} order mein price required hai"})
    if order_type in ("SL", "SL-M") and trig_price <= 0:
        return jsonify({"success": False, "error": "SL order mein trigger price required hai"})

    # Paper trading check
    if IS_PAPER_TRADING:
        logger.info(f"📄 PAPER order: {transaction} {quantity} {symbol} @ {order_type}")
        
        # Get SL and Target from request
        stop_loss = float(body.get("stop_loss", 0))
        target    = float(body.get("target",    0))
        
        # Fetch current market price for MARKET orders
        exec_price = price
        if order_type == "MARKET" or exec_price == 0:
            try:
                kite = _state["kite"]
                if kite:
                    ohlc_data = kite.ohlc([f"{exchange}:{symbol}"])
                    exec_price = ohlc_data.get(f"{exchange}:{symbol}", {}).get("last_price", 0)
                    if exec_price == 0:
                        exec_price = 100  # Fallback dummy price
            except Exception as e:
                logger.warning(f"LTP fetch failed for paper order: {e}")
                exec_price = 100  # Fallback
        
        # Save to paper portfolio
        portfolio = _state.get("paper_portfolio")
        if portfolio:
            # 5X Intraday Margin Check (MIS: 20% margin, CNC: 100%)
            is_mis = (product.upper() == "MIS")
            margin_factor = 0.20 if is_mis else 1.0
            order_val = exec_price * quantity
            req_margin = order_val * margin_factor

            # Check if this order is closing / reducing an existing position
            pos = portfolio.positions.get(symbol)
            is_closing = False
            if pos:
                if (pos.quantity > 0 and transaction == "SELL") or (pos.quantity < 0 and transaction == "BUY"):
                    is_closing = True

            if not is_closing:
                margin_info = portfolio.get_margin_summary(_state.get("kite"), TOTAL_CAPITAL)
                avail_margin = margin_info.get("available_margin", TOTAL_CAPITAL)
                if req_margin > avail_margin:
                    lev_str = "5X Intraday Margin" if is_mis else "1X Delivery (CNC)"
                    return jsonify({
                        "success": False,
                        "error": f"Insufficient margin! Required: ₹{req_margin:,.2f} ({lev_str}), Available: ₹{avail_margin:,.2f}. Quantity kam karein ya funds badhayein."
                    })

            order_id = portfolio.place_order(
                symbol=symbol,
                exchange=exchange,
                transaction=transaction,
                quantity=quantity,
                order_type=order_type,
                product=product,
                price=exec_price,
                trigger_price=trig_price,
                stop_loss=stop_loss,
                target=target,
                tag=tag,
            )
        else:
            order_id = f"PAPER_{symbol}_{transaction}_{quantity}"
        
        is_mis = (product.upper() == "MIS")
        margin_used = (exec_price * quantity) / 5.0 if is_mis else (exec_price * quantity)
        lev_tag = " [5X Margin: ₹" + f"{margin_used:,.2f}]" if is_mis else ""

        return jsonify({
            "success":    True,
            "order_id":   order_id,
            "paper_mode": True,
            "message":    f"📄 PAPER: {transaction} {quantity} {symbol} @ ₹{exec_price:.2f}{lev_tag}",
            "symbol":     symbol,
            "transaction": transaction,
            "quantity":   quantity,
            "order_type": order_type,
            "product":    product,
            "price":      exec_price,
            "margin_used": round(margin_used, 2),
            "leverage":   "5X" if is_mis else "1X",
        })

    # Live order
    try:
        kite = _state["kite"]

        # Map to kite constants
        kite_txn = kite.TRANSACTION_TYPE_BUY if transaction == "BUY" else kite.TRANSACTION_TYPE_SELL
        kite_ot  = {
            "MARKET": kite.ORDER_TYPE_MARKET,
            "LIMIT":  kite.ORDER_TYPE_LIMIT,
            "SL":     kite.ORDER_TYPE_SL,
            "SL-M":   kite.ORDER_TYPE_SLM,
        }.get(order_type, kite.ORDER_TYPE_MARKET)
        kite_prod = {
            "MIS":  kite.PRODUCT_MIS,
            "CNC":  kite.PRODUCT_CNC,
            "NRML": kite.PRODUCT_NRML,
        }.get(product, kite.PRODUCT_MIS)

        params = {
            "variety":          kite.VARIETY_REGULAR,
            "exchange":         exchange,
            "tradingsymbol":    symbol,
            "transaction_type": kite_txn,
            "quantity":         quantity,
            "product":          kite_prod,
            "order_type":       kite_ot,
            "tag":              tag,
        }
        if order_type in ("LIMIT", "SL") and price > 0:
            params["price"] = price
        if order_type in ("SL", "SL-M") and trig_price > 0:
            params["trigger_price"] = trig_price

        order_id = kite.place_order(**params)
        logger.info(f"✅ Order placed: {transaction} {quantity} {symbol} | ID: {order_id}")

        # Agar stop_loss bhi diya hai toh SL order bhi lagao
        sl_order_id = None
        sl_val = float(body.get("stop_loss", 0))
        if sl_val > 0 and order_type == "MARKET":
            sl_txn  = kite.TRANSACTION_TYPE_SELL if transaction == "BUY" else kite.TRANSACTION_TYPE_BUY
            try:
                sl_order_id = kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=symbol,
                    transaction_type=sl_txn,
                    quantity=quantity,
                    product=kite_prod,
                    order_type=kite.ORDER_TYPE_SLM,
                    trigger_price=sl_val,
                    tag="SL_" + tag,
                )
                logger.info(f"✅ SL order placed: {sl_val} | ID: {sl_order_id}")
            except Exception as e:
                logger.warning(f"SL order failed: {e}")

        return jsonify({
            "success":     True,
            "order_id":    str(order_id),
            "sl_order_id": str(sl_order_id) if sl_order_id else None,
            "paper_mode":  False,
            "message":     f"✅ {transaction} {quantity} {symbol} order placed!",
            "symbol":      symbol,
            "transaction": transaction,
            "quantity":    quantity,
            "order_type":  order_type,
            "product":     product,
            "price":       price,
        })

    except Exception as e:
        err = str(e)
        logger.error(f"Order placement error: {err}")
        if "Insufficient" in err or "margin" in err.lower():
            msg = "Insufficient margin! Funds check karo."
        elif "Invalid" in err:
            msg = f"Invalid order: {err}"
        else:
            msg = err
        return jsonify({"success": False, "error": msg})


@app.route("/api/trade/exit", methods=["POST"])
def api_trade_exit():
    """
    Kisi specific position se exit karo (square off).
    POST: {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "quantity": 10}
    """
    if not _state["kite"]:
        return jsonify({"success": False, "error": "Not logged in"})

    body     = request.get_json(silent=True) or {}
    symbol   = body.get("symbol",   "").upper()
    exchange = body.get("exchange", "NSE").upper()
    product  = body.get("product",  "MIS").upper()
    quantity = int(body.get("quantity", 0))
    txn      = body.get("transaction", "SELL").upper()   # SELL to exit long, BUY to exit short

    if not symbol or quantity <= 0:
        return jsonify({"success": False, "error": "Symbol aur quantity required"})

    if IS_PAPER_TRADING:
        return jsonify({
            "success":  True,
            "message":  f"📄 PAPER: Exit {quantity} {symbol} ({product})",
            "paper_mode": True,
        })

    try:
        kite = _state["kite"]
        kite_txn  = kite.TRANSACTION_TYPE_SELL if txn == "SELL" else kite.TRANSACTION_TYPE_BUY
        kite_prod = {
            "MIS":  kite.PRODUCT_MIS,
            "CNC":  kite.PRODUCT_CNC,
            "NRML": kite.PRODUCT_NRML,
        }.get(product, kite.PRODUCT_MIS)

        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=kite_txn,
            quantity=quantity,
            product=kite_prod,
            order_type=kite.ORDER_TYPE_MARKET,
            tag="EXIT",
        )
        logger.info(f"✅ Exit order: {symbol} {quantity} | ID: {order_id}")
        return jsonify({
            "success":  True,
            "order_id": str(order_id),
            "message":  f"✅ Exit order placed for {quantity} {symbol}",
        })

    except Exception as e:
        logger.error(f"Exit order error: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/trade/squareoff_all", methods=["POST"])
def api_squareoff_all():
    """Saari intraday (MIS) positions ek saath band karo"""
    if not _state["kite"]:
        return jsonify({"success": False, "error": "Not logged in"})

    if IS_PAPER_TRADING:
        return jsonify({"success": True, "message": "📄 PAPER: All positions squared off", "count": 0})

    try:
        kite      = _state["kite"]
        positions = kite.positions().get("net", [])
        count     = 0
        errors    = []

        for pos in positions:
            qty = pos.get("quantity", 0)
            if qty == 0:
                continue
            symbol   = pos.get("tradingsymbol", "")
            exchange = pos.get("exchange", "NSE")
            product  = pos.get("product", "MIS")
            txn = kite.TRANSACTION_TYPE_SELL if qty > 0 else kite.TRANSACTION_TYPE_BUY
            abs_qty  = abs(qty)

            try:
                kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=exchange,
                    tradingsymbol=symbol,
                    transaction_type=txn,
                    quantity=abs_qty,
                    product=kite.PRODUCT_MIS,
                    order_type=kite.ORDER_TYPE_MARKET,
                    tag="SQUAREOFF",
                )
                count += 1
            except Exception as e:
                errors.append(f"{symbol}: {e}")

        msg = f"✅ {count} positions squared off"
        if errors:
            msg += f" | Errors: {', '.join(errors[:3])}"

        logger.info(msg)
        return jsonify({"success": True, "message": msg, "count": count, "errors": errors})

    except Exception as e:
        logger.error(f"Square off all error: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/trade/positions")
def api_trade_positions():
    """Live positions from Kite (net + day)"""
    if not _state["kite"]:
        return jsonify({"net": [], "day": []})

    if IS_PAPER_TRADING:
        return jsonify({"net": [], "day": [], "paper_mode": True})

    try:
        pos = _state["kite"].positions()
        return jsonify({
            "net": pos.get("net", []),
            "day": pos.get("day", []),
        })
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return jsonify({"net": [], "day": [], "error": str(e)})


@app.route("/api/trade/holdings")
def api_trade_holdings():
    """CNC holdings (long-term portfolio)"""
    if not _state["kite"]:
        return jsonify({"holdings": []})

    if IS_PAPER_TRADING:
        return jsonify({"holdings": [], "paper_mode": True})

    try:
        holdings = _state["kite"].holdings()
        return jsonify({"holdings": holdings})
    except Exception as e:
        logger.error(f"Holdings error: {e}")
        return jsonify({"holdings": [], "error": str(e)})


@app.route("/api/trade/funds")
def api_trade_funds():
    """Available funds/margin"""
    if not _state["kite"]:
        return jsonify({"available": 0, "used": 0, "net": 0})

    is_live_mode = (TRADING_MODE == "LIVE")
    if _state.get("algo_engine") and getattr(_state["algo_engine"], "mode", None) == "LIVE":
        is_live_mode = True

    if not is_live_mode:
        portfolio = _state.get("paper_portfolio")
        if portfolio:
            summary = portfolio.get_margin_summary(_state.get("kite"), TOTAL_CAPITAL)
            return jsonify({
                "available": summary["available_margin"],
                "used":      summary["used_margin"],
                "net":       summary["net_capital"],
                "leverage":  "5X (Intraday MIS)",
                "paper_mode": True,
            })
        return jsonify({
            "available": TOTAL_CAPITAL,
            "used":      0,
            "net":       TOTAL_CAPITAL,
            "leverage":  "5X (Intraday MIS)",
            "paper_mode": True,
        })

    try:
        margins = _state["kite"].margins()
        equity  = margins.get("equity", {})
        comm    = margins.get("commodity", {})

        eq_avail = float(equity.get("available", {}).get("live_balance", 0) or equity.get("available", {}).get("cash", 0) or equity.get("net", 0) or 0)
        eq_used  = float(equity.get("utilised",  {}).get("debits", 0) or 0)
        eq_net   = float(equity.get("net", 0) or 0)

        comm_avail = float(comm.get("available", {}).get("live_balance", 0) or comm.get("available", {}).get("cash", 0) or comm.get("net", 0) or 0)
        comm_used  = float(comm.get("utilised",  {}).get("debits", 0) or 0)
        comm_net   = float(comm.get("net", 0) or 0)

        return jsonify({
            "available": eq_avail,
            "used":      eq_used,
            "net":       eq_net,
            "commodity_available": comm_avail,
            "commodity_used": comm_used,
            "commodity_net": comm_net,
            "total_available": eq_avail + comm_avail,
            "paper_mode": False,
        })
    except Exception as e:
        logger.error(f"Funds error: {e}")
        return jsonify({"available": 0, "used": 0, "net": 0, "error": str(e)})


# ─────────────────────────────────────────────────────────────
# PAPER TRADING - Portfolio Tracking
# ─────────────────────────────────────────────────────────────

@app.route("/api/trade/paper_positions")
def api_paper_positions():
    """
    Paper trading positions with live P&L.
    Returns: [{"symbol", "quantity", "avg_price", "ltp", "pnl", "pnl_pct", ...}]
    """
    portfolio = _state.get("paper_portfolio")
    if not portfolio:
        try:
            _state["paper_portfolio"] = PaperPortfolio()
            portfolio = _state["paper_portfolio"]
        except Exception:
            return jsonify({"positions": [], "error": "Portfolio not initialized"})

    try:
        kite = _state.get("kite")
        positions = portfolio.get_positions(kite=kite)
        
        # Calculate totals
        total_pnl     = sum(p["pnl"] for p in positions)
        total_invested = sum(p["avg_price"] * abs(p["quantity"]) for p in positions)
        overall_pct   = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        
        return jsonify({
            "positions":    positions,
            "total_pnl":    round(total_pnl, 2),
            "total_invested": round(total_invested, 2),
            "overall_pct":  round(overall_pct, 2),
            "closed_pnl":   round(portfolio.closed_pnl, 2),
            "count":        len(positions),
        })
    except Exception as e:
        logger.error(f"Paper positions error: {e}")
        return jsonify({"positions": [], "error": str(e)})


@app.route("/api/trade/paper_orders")
def api_paper_orders():
    """
    Paper trading order history.
    Returns: [{"order_id", "symbol", "transaction", "quantity", "price", "timestamp", ...}]
    """
    portfolio = _state.get("paper_portfolio")
    if not portfolio:
        try:
            _state["paper_portfolio"] = PaperPortfolio()
            portfolio = _state["paper_portfolio"]
        except Exception:
            return jsonify({"orders": [], "error": "Portfolio not initialized"})

    try:
        limit  = int(request.args.get("limit", 50))
        orders = portfolio.get_orders(limit=limit)
        
        return jsonify({
            "orders": orders,
            "count":  len(orders),
        })
    except Exception as e:
        logger.error(f"Paper orders error: {e}")
        return jsonify({"orders": [], "error": str(e)})


@app.route("/api/trade/paper_exit", methods=["POST"])
def api_paper_exit():
    """
    Close a paper trading position.
    POST body: {"symbol": "RELIANCE", "price": 2500}  # price optional
    """
    portfolio = _state.get("paper_portfolio")
    if not portfolio:
        try:
            _state["paper_portfolio"] = PaperPortfolio()
            portfolio = _state["paper_portfolio"]
        except Exception:
            return jsonify({"success": False, "error": "Portfolio not initialized"})

    body   = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").upper().strip()
    price  = float(body.get("price", 0))

    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"})

    try:
        kite    = _state.get("kite")
        success = portfolio.exit_position(symbol=symbol, price=price, kite=kite)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"Position closed: {symbol}",
                "symbol":  symbol,
            })
        else:
            return jsonify({
                "success": False,
                "error":   f"Position not found: {symbol}",
            })
    except Exception as e:
        logger.error(f"Paper exit error: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/trade/paper_reset", methods=["POST"])
def api_paper_reset():
    """Reset paper portfolio - clear all positions and orders"""
    portfolio = _state.get("paper_portfolio")
    if not portfolio:
        try:
            _state["paper_portfolio"] = PaperPortfolio()
            portfolio = _state["paper_portfolio"]
        except Exception:
            return jsonify({"success": False, "error": "Portfolio not initialized"})

    try:
        portfolio.reset()
        # Also clear any paper trades from algo engine if available
        algo = _state.get("algo_engine")
        if algo and hasattr(algo, "clear_closed_trades"):
            try:
                algo.clear_closed_trades()
            except Exception:
                pass

        return jsonify({
            "success": True,
            "message": "Paper portfolio and trade history reset successfully",
        })
    except Exception as e:
        logger.error(f"Paper reset error: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/trade/quote")
def api_trade_quote():
    """Symbol ka live quote (LTP + OHLC)"""
    symbol   = request.args.get("symbol",   "").upper()
    exchange = request.args.get("exchange", "NSE").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"})

    if not _state["kite"]:
        return jsonify({"error": "Not logged in"})

    try:
        key   = f"{exchange}:{symbol}"
        quote = _state["kite"].quote([key]).get(key, {})
        ohlc  = quote.get("ohlc", {})
        return jsonify({
            "symbol":     symbol,
            "ltp":        quote.get("last_price", 0),
            "open":       ohlc.get("open",  0),
            "high":       ohlc.get("high",  0),
            "low":        ohlc.get("low",   0),
            "close":      ohlc.get("close", 0),
            "volume":     quote.get("volume_traded", 0),
            "buy_qty":    quote.get("total_buy_quantity",  0),
            "sell_qty":   quote.get("total_sell_quantity", 0),
            "change":     quote.get("net_change", 0),
            "change_pct": round(
                (quote.get("last_price", 0) - ohlc.get("close", 1)) /
                max(ohlc.get("close", 1), 1) * 100, 2
            ),
        })
    except Exception as e:
        logger.error(f"Quote error {symbol}: {e}")
        return jsonify({"error": str(e), "ltp": 0})


# ─────────────────────────────────────────────────────────────
# SECTOR HEATMAP & INDEX APIs
# ─────────────────────────────────────────────────────────────

# Sector data - heatmap ke liye (web_app level pe define)
_SECTOR_MAP = {
    "IT & Technology":          ["TCS","INFY","HCLTECH","WIPRO","TECHM","MPHASIS","COFORGE","PERSISTENT","OFSS","KPITTECH","TATAELXSI","BSOFT","MASTEK","HAPPSTMNDS","LATENTVIEW"],
    "Banking":                  ["HDFCBANK","ICICIBANK","KOTAKBANK","AXISBANK","SBIN","INDUSINDBK","BANDHANBNK","FEDERALBNK","IDFCFIRSTB","AUBANK","PNB","BANKBARODA","CANBK","UNIONBANK"],
    "Financial Services":       ["BAJFINANCE","BAJAJFINSV","HDFCLIFE","SBILIFE","ICICIPRULI","MUTHOOTFIN","CHOLAFIN","RECLTD","PFC","LICHSGFIN","SBICARD","MANAPPURAM","CANFINHOME"],
    "Auto & EV":                ["MARUTI","TMCV","TMPV","M&M","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","TVSMOTOR","BOSCHLTD","MOTHERSON","EXIDEIND","BALKRISIND","ESCORTS"],
    "Pharma & Healthcare":      ["SUNPHARMA","DIVISLAB","CIPLA","DRREDDY","APOLLOHOSP","ALKEM","TORNTPHARM","LUPIN","AUROPHARMA","IPCALAB","BIOCON","LALPATHLAB","SYNGENE","ZYDUSLIFE"],
    "FMCG & Consumer":          ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP","COLPAL","EMAMILTD","TATACONSUM","VBL","UBL","UNITDSPR"],
    "Oil, Gas & Energy":        ["RELIANCE","ONGC","BPCL","IOC","GAIL","PETRONET","NTPC","POWERGRID","TATAPOWER","ADANIPOWER","ADANIGREEN","JSWENERGY","CESC","IGL"],
    "Metals & Mining":          ["TATASTEEL","HINDALCO","JSWSTEEL","VEDL","COALINDIA","NMDC","SAIL","HINDZINC","NATIONALUM","GPIL"],
    "Real Estate":              ["DLF","GODREJPROP","PHOENIXLTD","BRIGADE","PRESTIGE","SOBHA","OBEROIRLTY","SUNTECK"],
    "Infra & Capital Goods":    ["LT","ABB","SIEMENS","BEL","HAL","BHEL","THERMAX","CUMMINSIND","KEC","NBCC","RITES"],
    "Cement":                   ["ULTRACEMCO","GRASIM","AMBUJACEM","ACC","SHREECEM","RAMCOCEM","JKCEMENT","STAR","KAJARIACER"],
    "Telecom":                  ["BHARTIARTL","IDEA","INDUSTOWER","TATACOMM","ROUTE"],
    "Chemicals":                ["PIDILITIND","SRF","DEEPAKNTR","AARTIIND","NAVINFLUOR","CLEAN","FINEORG","ATUL","LXCHEM","ALKYLAMINE","GNFC","SOLARINDS"],
    "Defence":                  ["HAL","BEL","BHEL","BEML","MIDHANI","GRSE","COCHINSHIP"],
    "New Age & Tech":           ["ZOMATO","PAYTM","NYKAA","POLICYBZR","DELHIVERY","NAZARA","EASEMYTRIP"],
}


@app.route("/api/indices/list")
def api_indices_list():
    """Available indices aur sectors ki list"""
    indices = [
        # All Market
        {"key": "all_stocks",        "label": "🌐 All Stocks (All NSE EQ)", "count": 1800, "group": "All Market"},
        {"key": "nifty500",          "label": "📊 Nifty 500",          "count": 500,  "group": "NSE Index"},
        # NSE Indices
        {"key": "nifty50",           "label": "🔵 Nifty 50",           "count": 50,  "group": "NSE Index"},
        {"key": "nifty_next50",      "label": "🔵 Nifty Next 50",      "count": 47,  "group": "NSE Index"},
        {"key": "nifty100",          "label": "🔵 Nifty 100",          "count": 97,  "group": "NSE Index"},
        {"key": "banknifty",         "label": "🏦 Bank Nifty",         "count": 15,  "group": "NSE Index"},
        {"key": "finnifty",          "label": "💰 Fin Nifty",          "count": 20,  "group": "NSE Index"},
        {"key": "nifty_midcap50",    "label": "📊 Nifty Midcap 50",    "count": 50,  "group": "NSE Midcap"},
        {"key": "nifty_midcap150",   "label": "📊 Nifty Midcap 150",   "count": 65,  "group": "NSE Midcap"},
        {"key": "nifty_smallcap100", "label": "📉 Nifty Smallcap 100", "count": 80,  "group": "NSE Smallcap"},
        {"key": "nifty200",          "label": "📈 Nifty 200",          "count": 162, "group": "NSE Index"},
        # BSE Indices
        {"key": "sensex30",          "label": "🟠 Sensex 30",          "count": 30,  "group": "BSE Index"},
        {"key": "bse100",            "label": "🟠 BSE 100",            "count": 97,  "group": "BSE Index"},
        # Special
        {"key": "watchlist",         "label": "⭐ My Watchlist",       "count": len(INTRADAY_CONFIG["watchlist"]), "group": "Custom"},
        {"key": "all_sectors",       "label": "🌐 All Sectors",        "count": 200, "group": "Custom"},
    ]

    sectors = [
        {"key":   name.lower().replace(" ", "_").replace(",","").replace("&",""),
         "label": name,
         "count": len(stocks),
         "group": "Sector"}
        for name, stocks in _SECTOR_MAP.items()
    ]

    return jsonify({"indices": indices, "sectors": sectors})


@app.route("/api/sector/heatmap")
def api_sector_heatmap():
    """
    Har sector ka average % change fetch karo.
    Aaj kaunsa sector teji mein hai kaunsa mandi mein.
    """
    if not _state["kite"]:
        return jsonify({"error": "Not logged in", "sectors": []})

    try:
        kite    = _state["kite"]
        results = []

        for sector_name, symbols in _SECTOR_MAP.items():
            clean = [s for s in symbols if s and s.replace("-","").replace("&","").replace("_","").isalnum() or "-" in s][:12]
            if not clean:
                continue

            try:
                ohlc = kite.ohlc([f"NSE:{s}" for s in clean])
            except Exception:
                continue

            changes, up, dn = [], 0, 0
            top_gainer = {"symbol": "", "chg": 0.0, "ltp": 0.0}
            top_loser  = {"symbol": "", "chg": 0.0, "ltp": 0.0}

            for key, data in ohlc.items():
                sym  = key.replace("NSE:", "")
                ltp  = data.get("last_price", 0)
                prev = data.get("ohlc", {}).get("close", 0)
                if ltp <= 0 or prev <= 0:
                    continue
                chg = (ltp - prev) / prev * 100
                changes.append(chg)
                if chg > 0:
                    up += 1
                    if chg > top_gainer["chg"]:
                        top_gainer = {"symbol": sym, "chg": round(chg,2), "ltp": round(ltp,2)}
                else:
                    dn += 1
                    if chg < top_loser["chg"]:
                        top_loser = {"symbol": sym, "chg": round(chg,2), "ltp": round(ltp,2)}

            if not changes:
                continue

            avg  = round(sum(changes) / len(changes), 2)
            total = up + dn

            results.append({
                "sector":     sector_name,
                "avg_change": avg,
                "up_stocks":  up,
                "dn_stocks":  dn,
                "total":      total,
                "up_pct":     round(up / max(total,1) * 100),
                "top_gainer": top_gainer,
                "top_loser":  top_loser,
                "strength":   "BULLISH" if avg > 0.5 else "BEARISH" if avg < -0.5 else "NEUTRAL",
            })

        results.sort(key=lambda x: -x["avg_change"])
        return jsonify({"sectors": results, "total": len(results),
                        "timestamp": datetime.now(IST_tz).strftime("%H:%M:%S")})

    except Exception as e:
        logger.error(f"Sector heatmap error: {e}")
        return jsonify({"error": str(e), "sectors": []})


@app.route("/api/sector/stocks")
def api_sector_stocks():
    """Ek sector ke stocks detail"""
    sector = request.args.get("name", "")
    stocks = _SECTOR_MAP.get(sector, [])
    if not stocks:
        # Try key-based lookup
        for name, syms in _SECTOR_MAP.items():
            k = name.lower().replace(" ","_").replace(",","").replace("&","")
            if k == sector.lower():
                stocks = syms
                sector = name
                break

    if not stocks:
        return jsonify({"error": f"Sector not found: {sector}", "stocks": []})

    if not _state["kite"]:
        return jsonify({"sector": sector,
                        "stocks": [{"symbol":s,"ltp":0,"change_pct":0} for s in stocks],
                        "total": len(stocks)})
    try:
        ohlc   = _state["kite"].ohlc([f"NSE:{s}" for s in stocks[:20]])
        result = []
        for key, data in ohlc.items():
            sym  = key.replace("NSE:","")
            ltp  = data.get("last_price",0)
            prev = data.get("ohlc",{}).get("close",0)
            chg  = (ltp-prev)/prev*100 if prev>0 else 0
            result.append({
                "symbol": sym, "ltp": round(ltp,2),
                "prev_close": round(prev,2),
                "open": round(data.get("ohlc",{}).get("open",0),2),
                "high": round(data.get("ohlc",{}).get("high",0),2),
                "low":  round(data.get("ohlc",{}).get("low",0),2),
                "change_pct": round(chg,2),
                "volume": data.get("volume",0),
            })
        result.sort(key=lambda x: -x["change_pct"])
        return jsonify({"sector": sector, "stocks": result, "total": len(result)})
    except Exception as e:
        return jsonify({"error": str(e), "stocks": []})


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_logger("INFO", "logs/web_app.log")
    errors, warnings = validate_config()
    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🌐 Starting Web Server → http://0.0.0.0:{port}")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
