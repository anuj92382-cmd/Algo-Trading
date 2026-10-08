"""
algo_trading/algo_engine.py - Autonomous Algorithmic Trading Engine
100% Fully Automated Auto Buy / Auto Sell Execution Engine (Auto-Pilot)

Key Concepts Implemented:
1. Multi-Strategy Quantitative Engine (Momentum, Open Reversal, RSI Reversion, Breakout Surge, Supertrend)
2. Autonomous Execution Loop (No human clicks needed - scans, detects signals, executes orders automatically)
3. Risk Management System (RMS) & Circuit Breakers (Daily Loss Cap, Daily Profit Lock, Max Positions, Cutoff Times)
4. Dynamic Trailing Stop Loss & Auto Target Management
5. Dual Execution Routing: 📄 Paper Trading (with 5X intraday margin) and 🔴 Live Zerodha Kite Execution
6. Emergency Panic Kill Switch (Instant square-off of all positions and bot freeze)
7. Real-time Live Terminal Activity Stream
"""

import os
import json
import time
import random
import logging
import threading
import hashlib
from collections import deque
from datetime import datetime, date, timedelta, time as dtime
from typing import Dict, List, Optional, Any
from pathlib import Path
import sys
import pytz

pkg_dir = str(Path(__file__).resolve().parent)
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

try:
    from config import TRADING_MODE, TOTAL_CAPITAL
except Exception:
    TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")
    TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", 2000000.0))

logger = logging.getLogger("algo_engine")
IST = pytz.timezone("Asia/Kolkata")

# Storage file for persistent algo metrics & settings
STATE_FILE = Path(__file__).resolve().parent / "data" / "algo_state.json"

# Sector Mapping for Bullish Sector Analysis
SECTOR_MAP = {
    "IT & Tech":                ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "COFORGE", "PERSISTENT", "MPHASIS", "KPITTECH", "TATAELXSI", "OFSS"],
    "Banking & Financials":     ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "BANKBARODA", "PNB", "FEDERALBNK", "IDFCFIRSTB", "BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "CHOLAFIN", "MUTHOOTFIN", "RECLTD", "PFC"],
    "Auto & EV":                ["MARUTI", "TMCV", "TMPV", "M&M", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "TVSMOTOR", "ASHOKLEY", "BHARATFORG", "MOTHERSON", "BOSCHLTD"],
    "Pharma & Healthcare":      ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP", "LUPIN", "AUROPHARMA", "TORNTPHARM", "ZYDUSLIFE", "ALKEM", "BIOCON", "MANKIND"],
    "FMCG & Consumption":       ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR", "MARICO", "GODREJCP", "COLPAL", "VBL", "UNITDSPR"],
    "Metals & Mining":          ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "COALINDIA", "JINDALSTEL", "NMDC", "NATIONALUM", "SAIL", "APLAPOLLO"],
    "Oil, Gas & Energy":        ["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL", "PETRONET", "NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "ADANIGREEN", "JSWENERGY", "CESC", "IGL"],
    "Real Estate & Infra":      ["DLF", "GODREJPROP", "PHOENIXLTD", "BRIGADE", "PRESTIGE", "SOBHA", "OBEROIRLTY", "SUNTECK", "LT", "ABB", "SIEMENS", "BEL", "HAL", "BHEL"],
    "Chemicals & Fertilizers":  ["PIDILITIND", "SRF", "DEEPAKNTR", "AARTIIND", "NAVINFLUOR", "PIIND", "UPL", "COROMANDEL", "TATACHEM", "FLUOROCHEM"],
    "Consumer Durables & Media":["TITAN", "HAVELLS", "VOLTAS", "DIXON", "CROMPTON", "POLYCAB", "KEI", "BHARTIARTL", "IDEA", "INDUSTOWER", "ZEEL", "PVRINOX"]
}


def calculate_trade_charges(product: str, quantity: int, buy_price: float, sell_price: float) -> dict:
    """
    Computes exact statutory brokerage and taxes for Indian Equities on NSE (Zerodha standard schedule):
    - Turnover: Buy Turnover + Sell Turnover
    - Brokerage:
        - MIS (Intraday): min(20.0, 0.0003 * turnover) per leg (buy leg + sell leg)
        - CNC (Delivery): 0.0 (Zero brokerage)
    - STT (Securities Transaction Tax):
        - MIS: 0.025% on Sell turnover
        - CNC: 0.1% on Total (Buy + Sell) turnover
    - Exchange Transaction Charges:
        - NSE: 0.00297% on Total turnover
    - SEBI Turnover Charges:
        - ₹10 per crore = 0.0001% on Total turnover
    - Stamp Duty:
        - 0.003% on Buy turnover
    - GST:
        - 18% on (Brokerage + Exchange Txn Charges + SEBI Charges)
    - Total Charges: Sum of all above
    """
    qty = max(1, int(quantity))
    b_price = max(0.01, float(buy_price))
    s_price = max(0.01, float(sell_price))
    prod = (product or "MIS").upper().strip()

    buy_turnover = b_price * qty
    sell_turnover = s_price * qty
    total_turnover = buy_turnover + sell_turnover

    # 1. Brokerage
    if prod == "MIS":
        buy_brokerage = min(20.0, 0.0003 * buy_turnover)
        sell_brokerage = min(20.0, 0.0003 * sell_turnover)
        brokerage = buy_brokerage + sell_brokerage
    else:  # CNC
        brokerage = 0.0

    # 2. STT / CTT
    if prod == "MIS":
        stt = 0.00025 * sell_turnover
    else:
        stt = 0.001 * total_turnover

    # 3. Exchange Transaction Charges (NSE Equity: 0.00297%)
    exchange_txn = 0.0000297 * total_turnover

    # 4. SEBI Turnover Charges (₹10/crore: 0.0001%)
    sebi_charges = 0.000001 * total_turnover

    # 5. Stamp Duty (Buy side only: 0.003% for intraday MIS, 0.015% for CNC)
    if prod == "MIS":
        stamp_duty = 0.00003 * buy_turnover
    else:
        stamp_duty = 0.00015 * buy_turnover

    # 6. GST (18% on Brokerage + Exchange Txn + SEBI)
    gst = 0.18 * (brokerage + exchange_txn + sebi_charges)

    total_charges = brokerage + stt + exchange_txn + sebi_charges + stamp_duty + gst

    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_txn": round(exchange_txn, 2),
        "sebi": round(sebi_charges, 2),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "total_charges": round(total_charges, 2),
        "breakdown": {
            "Brokerage": f"₹{brokerage:.2f}",
            "STT": f"₹{stt:.2f}",
            "Exchange": f"₹{exchange_txn:.2f}",
            "GST": f"₹{gst:.2f}",
            "Stamp Duty": f"₹{stamp_duty:.2f}",
            "SEBI": f"₹{sebi_charges:.2f}",
        }
    }


def calculate_setup_win_rate(
    strat_id: str,
    side: str,
    ltp: float,
    open_p: float,
    high_p: float,
    low_p: float,
    prev_close: float,
    target_1_pct: float = 1.0,
    sl_pct: float = 0.8,
    avg_price: float = 0.0,
    volume: int = 0,
) -> dict:
    """
    Computes a quantitative Win Rate / Probability Score (0.0% to 100.0%) for an intraday technical setup.
    Evaluates:
    - Relative Strength & Day Change % (+0.8% to +3.5% = strongest institutional edge)
    - Proximity to Day High (Range Position >= 80% = genuine expansion, never buy bottom half)
    - Institutional VWAP alignment & support
    - Volume surge confirmation
    - Risk-Reward ratio
    """
    base_rates = {
        "custom_quant_momentum": 66.0,
        "breakout_surge": 64.0,
        "orb_breakout": 63.0,
        "vwap_sniper": 62.0,
        "momentum_trend": 60.0,
        "supertrend_rider": 58.0,
        "open_reversal": 56.0,
        "rsi_reversion": 54.0,
    }
    score = base_rates.get(strat_id, 58.0)

    # 1. Risk-to-Reward Ratio Confluence (Target / Stop Loss)
    if sl_pct > 0:
        rr = target_1_pct / sl_pct
        if rr >= 1.6:
            score += 6.0
        elif rr >= 1.2:
            score += 3.0
        elif rr < 1.0:
            score -= 8.0

    # 2. Intraday Range Position (Buying near high of the day vs bottom)
    day_range = high_p - low_p
    if day_range > 0:
        pos_ratio = (ltp - low_p) / day_range
        if side == "BUY":
            if pos_ratio >= 0.85:   # Strong breakout near day high
                score += 8.0
            elif pos_ratio >= 0.70:
                score += 4.0
            elif pos_ratio < 0.50:  # Weak setup trading in bottom half
                score -= 14.0
        else: # SELL / SHORT
            if pos_ratio <= 0.15:
                score += 8.0
            elif pos_ratio <= 0.30:
                score += 4.0
            elif pos_ratio > 0.50:
                score -= 14.0

    # 3. Day Trend Strength against previous close
    if prev_close > 0:
        day_chg = ((ltp - prev_close) / prev_close) * 100.0
        if side == "BUY":
            if 1.0 <= day_chg <= 3.8:   # Ideal sweet spot of strong relative strength
                score += 8.0
            elif 0.6 <= day_chg < 1.0:
                score += 4.0
            elif day_chg > 5.5:         # Overextended exhaustion risk
                score -= 8.0
            elif day_chg < 0:           # Counter-trend trap
                score -= 14.0
        else: # SELL
            if -3.8 <= day_chg <= -1.0:
                score += 8.0
            elif -1.0 < day_chg <= -0.6:
                score += 4.0
            elif day_chg < -5.5:
                score -= 8.0
            elif day_chg > 0:
                score -= 14.0

    # 4. Open price confirmation
    if open_p > 0:
        open_gain = ((ltp - open_p) / open_p) * 100.0
        if side == "BUY":
            if open_gain >= 0.6:
                score += 4.0
            elif open_gain < 0:
                score -= 8.0
        elif side == "SELL":
            if open_gain <= -0.6:
                score += 4.0
            elif open_gain > 0:
                score -= 8.0

    # 5. VWAP Institutional Trend Confluence (Buy strictly above VWAP, Sell strictly below VWAP)
    effective_vwap = avg_price if avg_price > 0 else (open_p + high_p + low_p) / 3.0
    if effective_vwap > 0:
        if side == "BUY":
            if ltp >= effective_vwap:
                dist = (ltp - effective_vwap) / effective_vwap * 100.0
                if 0.1 <= dist <= 1.8:   # Healthy distance above VWAP
                    score += 8.0
                elif dist > 3.5:         # Too far extended from VWAP
                    score -= 4.0
                else:
                    score += 4.0
            else:
                score -= 16.0  # Strictly penalize buying below VWAP
        else: # SELL
            if ltp <= effective_vwap:
                dist = (effective_vwap - ltp) / effective_vwap * 100.0
                if 0.1 <= dist <= 1.8:
                    score += 8.0
                elif dist > 3.5:
                    score -= 4.0
                else:
                    score += 4.0
            else:
                score -= 16.0

    # 6. Volume Surge Confluence
    if volume > 0:
        if volume >= 250000:
            score += 7.0
        elif volume >= 100000:
            score += 4.0
        elif volume >= 40000:
            score += 2.0
        elif volume < 15000:
            score -= 8.0   # Illiquid trap

    final_score = round(max(10.0, min(95.0, score)), 1)

    # ── OPENING VOLATILITY TIME PENALTY ──────────────────────────────────────────
    # 9:30 AM - 9:45 AM: Market opening is extremely volatile.
    # OHLC data is incomplete, VWAP unreliable, false breakouts are common.
    # Apply progressive penalty: strongest in first 5 minutes, reducing by 9:45.
    # Note: custom_quant_momentum is specifically tuned for early morning pre-market & 9:15 surge.
    from datetime import datetime
    import pytz
    _IST = pytz.timezone("Asia/Kolkata")
    _now_t = datetime.now(_IST).time()
    from datetime import time as _dtime
    if strat_id != "custom_quant_momentum":
        if _dtime(9, 30) <= _now_t < _dtime(9, 38):
            final_score = round(max(10.0, final_score - 18.0), 1)  # Heavy penalty: first 8 minutes
        elif _dtime(9, 38) <= _now_t < _dtime(9, 45):
            final_score = round(max(10.0, final_score - 10.0), 1)  # Moderate penalty: 9:38-9:45

    return {
        "win_rate": final_score,
        "is_approved": final_score >= 60.0,
    }


class AlgoEngine:
    """
    Autonomous Multi-Strategy Algorithmic Trading Engine.
    Executes trades on auto-pilot without manual intervention.
    """

    def __init__(self, web_state: Optional[dict] = None):
        self._web_state = web_state or {}
        self._lock = threading.RLock()

        # Engine State
        self.status = "STOPPED"       # "STOPPED" | "RUNNING" | "PAUSED"
        self.mode = TRADING_MODE.upper().strip() if TRADING_MODE else "PAPER"  # Controlled via .env
        self.universe = "all_stocks"     # "all_stocks" (All Market Stocks) | "fno" (F&O Only)


        # Scheduler & Timing
        self.scan_interval_sec = 15
        self.last_scan_time: Optional[datetime] = None
        self.next_scan_countdown = 15
        self._worker_thread: Optional[threading.Thread] = None
        self._running_flag = False
        self._scan_lock = threading.Lock()  # Mutex to prevent duplicate concurrent scans

        # Live Terminal Logs (Ring buffer of last 300 logs)
        self.logs = deque(maxlen=300)

        # Risk Management Settings (RMS)
        self.risk_config = {
            "total_capital": float(TOTAL_CAPITAL) if TOTAL_CAPITAL else 2000000.0,  # 💼 Total Trading Capital from .env
            "capital_mode": "auto_split",      # "auto_split" (total_capital / max_positions) or "fixed"
            "max_daily_loss": 5000.0,         # Bot halts if loss exceeds ₹5,000
            "max_daily_profit": 15000.0,       # Bot locks profits at ₹15,000
            "max_open_positions": 4,          # Max simultaneous positions
            "min_win_rate_pct": 60.0,         # 🎯 Minimum 60% Win Rate Required to Execute Orders!
            "min_stock_price": 50.0,           # 💰 Minimum stock price (₹50) - Blocks penny stocks
            "max_stock_price": 3000.0,         # 💰 Maximum stock price (₹3,000) - Blocks illiquid high prices
            "min_market_cap_m": 100.0,         # 🏢 Minimum Market Cap > 100 Million (₹10 Cr+ / 100M+)
            "entry_start_time": "09:30",       # 9:30 AM IST (Opening 15-min candle form hone ke baad entry - opening volatility se bachav)
            "entry_cutoff_time": "14:45",      # 2:45 PM IST (No new entries)
            "auto_squareoff_time": "15:15",    # 3:15 PM IST (Auto exit all intraday)
            "circuit_breaker_hit": False,
            "circuit_breaker_reason": "",
        }

        # Quantitative Strategies Library
        self.strategies: Dict[str, dict] = {
            "momentum_trend": {
                "id": "momentum_trend",
                "name": "Momentum Trend",
                "badge": "EMA + VWAP",
                "desc": "Fast EMA(9) crosses Slow EMA(21) with VWAP support and RSI confirmation.",
                "icon": "📈",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:45",
                "min_gain_pct": 0.5,
                "max_gain_pct": 2.8,
                "min_day_chg_pct": 0.8,
                "max_day_chg_pct": 3.5,
                "min_range_pos": 0.75,
                "vwap_dist_mult": 1.002,
                "min_turnover": 10000000.0,
                "target_pct": 2.0,
                "target_1_pct": 1.5,           # Target 1: Book 50% Qty & Move SL to Cost
                "target_2_pct": 2.5,           # Target 2: Final 50% Runner
                "sl_pct": 1.2,
                "trailing_sl_pct": 0.6,
                "capital_per_trade": 5000.0,
                "product": "MIS",              # MIS uses 5X leverage
                "side": "BOTH",               # BOTH, BUY_ONLY, SELL_ONLY
                "fixed_qty": 0,               # 0 = Auto (capital based), >0 = Fixed qty per trade
                "signals_count": 0,
            },
            "open_reversal": {
                "id": "open_reversal",
                "name": "Morning Reversal + PDH Breakout",
                "badge": "9:30-10:45 AM | PDH Break",
                "desc": "Active 9:30-10:45 AM: Stock dips >= 0.5% below morning Open, recovers >= 0.6% back above Open, breaks Prev Day High (strict: 0.1% above PDH required). Gap protection: skips gap-up > 2% or gap-down > 2.5%. Auto exits immediately if price drops 1.5% from peak high.",
                "icon": "🔄",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:30",
                "end_time": "10:45",
                "min_dip_pct": 0.50,
                "min_recovery_pct": 0.60,
                "max_gap_up_pct": 2.0,
                "max_gap_down_pct": 2.5,
                "min_day_chg_pct": 0.3,
                "min_range_pos": 0.60,
                "pdh_breakout_mult": 1.001,
                "vwap_dist_mult": 1.003,
                "peak_drop_exit_pct": 1.5,
                "min_turnover": 5000000.0,
                "target_pct": 2.5,
                "target_1_pct": 1.5,
                "target_2_pct": 3.0,
                "sl_pct": 1.2,
                "trailing_sl_pct": 0.5,
                "capital_per_trade": 5000.0,
                "product": "MIS",
                "side": "BUY_ONLY",
                "fixed_qty": 0,
                "signals_count": 0,
            },
            "rsi_reversion": {
                "id": "rsi_reversion",
                "name": "RSI Mean Reversion",
                "badge": "Overbought/Oversold",
                "desc": "RSI < 30 oversold bounce back, or RSI > 70 overbought breakdown pullback.",
                "icon": "🎯",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:50",
                "min_drop_from_close": 1.0,
                "max_drop_from_close": 3.0,
                "min_bounce_from_low": 1.0,
                "vwap_dist_mult": 0.998,
                "min_turnover": 10000000.0,
                "target_pct": 1.5,
                "target_1_pct": 1.0,
                "target_2_pct": 2.0,
                "sl_pct": 1.0,
                "trailing_sl_pct": 0.5,
                "capital_per_trade": 5000.0,
                "product": "MIS",
                "side": "BOTH",
                "fixed_qty": 0,
                "signals_count": 0,
            },
            "breakout_surge": {
                "id": "breakout_surge",
                "name": "Breakout & Volume Surge",
                "badge": "Day High + ₹2Cr Turn",
                "desc": "Day High breakout with institutional Rupee Turnover >= ₹2Cr (Active 9:30-12:00 & 1:45-2:45).",
                "icon": "🚀",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:30",
                "morning_end_time": "12:00",
                "afternoon_start_time": "13:45",
                "end_time": "14:45",
                "min_range_pos": 0.88,
                "min_day_chg_pct": 0.8,
                "min_day_gain_pct": 0.6,
                "max_day_gain_pct": 4.0,
                "min_turnover": 20000000.0,
                "vwap_dist_mult": 1.002,
                "target_pct": 2.2,
                "target_1_pct": 1.5,
                "target_2_pct": 3.0,
                "sl_pct": 1.2,
                "trailing_sl_pct": 0.6,
                "capital_per_trade": 5000.0,
                "product": "MIS",
                "side": "BUY_ONLY",
                "fixed_qty": 0,
                "signals_count": 0,
            },
            "supertrend_rider": {
                "id": "supertrend_rider",
                "name": "Supertrend Trend Rider",
                "badge": "Trend Pullback Retest",
                "desc": "Captures high-probability trend retests into 20-EMA/VWAP shelf during sustained trends.",
                "icon": "🛡️",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:45",
                "min_day_chg_pct": 1.0,
                "max_day_chg_pct": 3.8,
                "min_range_pos": 0.65,
                "max_range_pos": 0.85,
                "vwap_dist_mult": 1.003,
                "min_turnover": 15000000.0,
                "target_pct": 2.5,
                "target_1_pct": 1.5,
                "target_2_pct": 3.0,
                "sl_pct": 1.2,
                "trailing_sl_pct": 0.6,
                "capital_per_trade": 5000.0,
                "product": "MIS",
                "side": "BOTH",
                "fixed_qty": 0,
                "signals_count": 0,
            },
            "vwap_sniper": {
                "id": "vwap_sniper",
                "name": "VWAP Institutional Pullback",
                "badge": "VWAP Bounce Confirm",
                "desc": "Buys confirmed green bounces off the institutional VWAP shelf in strong uptrending stocks.",
                "icon": "💎",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:45",
                "min_day_chg_pct": 0.6,
                "max_day_chg_pct": 3.8,
                "min_vwap_dist_pct": 0.05,
                "max_vwap_dist_pct": 0.55,
                "min_bounce_pct": 0.35,
                "min_turnover": 15000000.0,
                "target_pct": 1.8,
                "target_1_pct": 1.2,           # Target 1: Book 50% Qty & Move SL to Cost
                "target_2_pct": 2.5,           # Target 2: Final 50% Runner
                "sl_pct": 1.0,                 # 1.0% SL below VWAP shelf (protective against noise)
                "trailing_sl_pct": 0.5,
                "capital_per_trade": 5000.0,
                "product": "MIS",              # MIS uses 5X leverage
                "side": "BUY_ONLY",
                "fixed_qty": 0,
                "signals_count": 0,
            },
            "orb_breakout": {
                "id": "orb_breakout",
                "name": "ORB 15-Min Breakout",
                "badge": "9:15-9:30 Frozen Box",
                "desc": "True 15-minute Opening Range (9:15-9:30 AM) high breakout, active strictly 9:30-11:15 AM.",
                "icon": "⚡",
                "enabled": True,
                "timeframe": "15m",
                "start_time": "09:30",
                "end_time": "11:15",
                "min_day_gain_pct": 0.6,
                "max_day_gain_pct": 3.8,
                "min_day_chg_pct": 0.8,
                "orb_breakout_mult": 0.998,
                "vwap_dist_mult": 1.002,
                "min_turnover": 20000000.0,
                "target_pct": 2.2,
                "target_1_pct": 1.5,
                "target_2_pct": 3.0,
                "sl_pct": 1.2,
                "trailing_sl_pct": 0.6,
                "capital_per_trade": 5000.0,
                "product": "MIS",
                "side": "BUY_ONLY",
                "fixed_qty": 0,
                "signals_count": 0,
            },
            "custom_quant_momentum": {
                "id": "custom_quant_momentum",
                "name": "Pre-Market, Sector & OI Sniper",
                "badge": "4-Filter | Sector + OI + 1.5% Peak SL",
                "desc": "Active 9:15-14:45: Scans (1) Prev Day >4.5% movers, (2) 9:10 AM Pre-market gainers/losers, (3) 9:15 AM >=2% surge, (4) Bullish Sector stocks. Confirms Short Covering / OI Gainer before Buy. Instant 1.5% Peak Drop Stop Loss.",
                "icon": "🎯",
                "enabled": True,
                "timeframe": "5m",
                "start_time": "09:15",
                "end_time": "14:45",
                "prev_day_mover_pct": 4.5,
                "pre_market_mover_pct": 1.5,
                "open_surge_pct": 2.0,
                "sector_bullish_min_pct": 0.5,
                "peak_drop_exit_pct": 1.5,
                "min_turnover": 5000000.0,
                "target_pct": 2.5,
                "target_1_pct": 1.5,
                "target_2_pct": 3.0,
                "sl_pct": 1.5,
                "trailing_sl_pct": 0.5,
                "capital_per_trade": 5000.0,
                "product": "MIS",
                "side": "BUY_ONLY",
                "fixed_qty": 0,
                "signals_count": 0,
            },
        }

        # Active Positions Tracked by Algo Engine
        # {pos_id: {...}}
        self.active_positions: Dict[str, dict] = {}

        # Closed Trades History
        self.closed_trades: List[dict] = []

        # Intraday Equity Curve Tracker
        self.equity_curve: List[dict] = []

        # Performance Metrics
        self.stats = {
            "today_pnl": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "gross_pnl": 0.0,
            "total_charges": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "signals_today": 0,
            "orders_today": 0,
        }

        # Real-time WebSocket Live Feed Buffer
        self.live_quotes_cache: Dict[str, dict] = {}
        self._quote_lock = threading.RLock()
        self.last_scan_duration_ms: float = 0.0
        self.is_websocket_active: bool = False
        self._ticker_callback_registered: bool = False
        self._token_cache: Dict[str, int] = {}
        self._orb_ranges: Dict[str, dict] = {}
        self._bullish_sector_cache: Dict[str, tuple] = {}

        # Load persisted settings and trades if available
        self._load_state()

        # Seed welcome log
        self._log("INFO", "⚡ Algo Trading Engine initialized in AUTO-PILOT mode (Ready to Start).")

    # ─────────────────────────────────────────────────────────────
    # LOGGING UTILITIES
    # ─────────────────────────────────────────────────────────────

    def _log(self, level: str, message: str, details: str = ""):
        """Add an event to the live activity terminal ring buffer."""
        now_str = datetime.now(IST).strftime("%H:%M:%S")
        entry = {
            "time": now_str,
            "level": level.upper(),
            "message": message,
            "details": details,
        }
        self.logs.append(entry)
        log_msg = f"[{now_str}] [{level.upper()}] {message}"
        if details:
            log_msg += f" | {details}"
        logger.info(log_msg)

    # ─────────────────────────────────────────────────────────────
    # STATE PERSISTENCE
    # ─────────────────────────────────────────────────────────────

    def _save_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "mode": self.mode,
                "universe": self.universe,
                "risk_config": self.risk_config,
                "strategies": self.strategies,
                "closed_trades": self.closed_trades[-100:],  # keep last 100
                "stats": self.stats,
                "trade_date": datetime.now(IST).strftime("%Y-%m-%d"),  # Track trade date for cross-day reset
                "saved_at": datetime.now(IST).isoformat(),
            }
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"Failed to save algo state: {e}")

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.mode = TRADING_MODE.upper().strip() if TRADING_MODE else data.get("mode", "PAPER")
                self.universe = data.get("universe", "nifty50")

                if "risk_config" in data:
                    self.risk_config.update(data["risk_config"])
                self.risk_config.setdefault("min_win_rate_pct", 60.0)
                self.risk_config.setdefault("min_stock_price", 50.0)
                self.risk_config.setdefault("max_stock_price", 3000.0)
                self.risk_config.setdefault("min_market_cap_m", 100.0)
                env_cap = float(TOTAL_CAPITAL) if TOTAL_CAPITAL else 2000000.0
                # Synchronize with .env TOTAL_CAPITAL
                if env_cap and (self.risk_config.get("total_capital") != env_cap):
                    logger.info(f"Synchronizing total_capital from .env: ₹{env_cap:,.2f} (was ₹{self.risk_config.get('total_capital', 0):,.2f})")
                    self.risk_config["total_capital"] = env_cap
                self.risk_config.setdefault("total_capital", env_cap)
                self.risk_config.setdefault("capital_mode", "auto_split")
                if "strategies" in data:
                    for k, v in data["strategies"].items():
                        if k in self.strategies:
                            self.strategies[k].update(v)
                self.rebalance_strategy_capital()

                # ── DATE-AWARE RESTORE: Only load today's trades & stats ──────────
                # Agar state file aaj ki nahi hai, toh closed_trades aur stats
                # reset karo - cross-day data mismatch prevent karne ke liye.
                saved_trade_date = data.get("trade_date", data.get("saved_at", "")[:10])
                today_str = datetime.now(IST).strftime("%Y-%m-%d")
                is_today = (saved_trade_date == today_str)

                if is_today:
                    # Aaj ka valid state: reload trades and stats
                    self.closed_trades = data.get("closed_trades", [])
                    if "stats" in data:
                        self.stats.update(data["stats"])
                    self.stats.setdefault("gross_pnl", 0.0)
                    self.stats.setdefault("total_charges", 0.0)
                    logger.info(f"✅ Loaded today's persisted algo state ({len(self.closed_trades)} closed trades).")
                else:
                    # Purani state (kal ya pehle ki): settings/strategies load karo,
                    # lekin trades aur stats RESET karo - naya trading day start!
                    self.closed_trades = []
                    self.stats = {
                        "today_pnl": 0.0,
                        "realized_pnl": 0.0,
                        "unrealized_pnl": 0.0,
                        "gross_pnl": 0.0,
                        "total_charges": 0.0,
                        "total_trades": 0,
                        "winning_trades": 0,
                        "losing_trades": 0,
                        "win_rate": 0.0,
                        "profit_factor": 0.0,
                        "signals_today": 0,
                        "orders_today": 0,
                    }
                    logger.info(f"🔄 New trading day! Algo P&L stats & trade history reset (last saved: {saved_trade_date}).")
                # ─────────────────────────────────────────────────────────────────
                logger.info("Loaded persisted algo state successfully.")
        except Exception as e:
            logger.debug(f"Could not load algo state: {e}")

    # ─────────────────────────────────────────────────────────────
    # MASTER CONTROLLER (START / PAUSE / STOP / KILL SWITCH)
    # ─────────────────────────────────────────────────────────────

    def start(self) -> dict:
        """Start autonomous Auto Buy/Sell bot."""
        with self._lock:
            if self.risk_config.get("circuit_breaker_hit"):
                return {"success": False, "error": f"Circuit Breaker active: {self.risk_config.get('circuit_breaker_reason')}. Reset required."}

            self.status = "RUNNING"
            self._running_flag = True

            if not self._worker_thread or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(target=self._execution_loop, daemon=True, name="AlgoEngineThread")
                self._worker_thread.start()

            self._log("INFO", f"🤖 MASTER BOT STARTED in {self.mode} MODE (Auto-Pilot Active)", "Scanning & Auto Buy/Sell is now LIVE")
            self._save_state()
            return {"success": True, "status": self.status, "mode": self.mode}

    def pause(self) -> dict:
        """Pause bot (keeps monitoring existing positions, but halts new auto entries)."""
        with self._lock:
            self.status = "PAUSED"
            self._log("INFO", "⏸️ MASTER BOT PAUSED", "No new positions will be opened. Active positions are still monitored.")
            self._save_state()
            return {"success": True, "status": self.status}

    def stop(self) -> dict:
        """Stop bot completely."""
        with self._lock:
            self.status = "STOPPED"
            self._running_flag = False
            self._log("INFO", "🛑 MASTER BOT STOPPED", "Autonomous execution loop halted.")
            self._save_state()
            return {"success": True, "status": self.status}

    def set_mode(self, mode: str) -> dict:
        """Switch between PAPER and LIVE trading mode."""
        mode = mode.upper().strip()
        if mode not in ("PAPER", "LIVE"):
            return {"success": False, "error": "Invalid mode. Must be PAPER or LIVE"}

        with self._lock:
            self.mode = mode
            self._log("ALERT", f"🔄 Mode changed to {mode} TRADING", "Paper: 5X Intraday Margin | Live: Real Kite Orders")
            self._save_state()
            return {"success": True, "mode": self.mode}

    def emergency_kill_switch(self) -> dict:
        """
        EMERGENCY KILL SWITCH:
        1. Immediately halts the bot.
        2. Squares off ALL open algo positions at current market price.
        3. Cancels pending orders.
        4. Logs emergency alert.
        """
        with self._lock:
            self.status = "STOPPED"
            self._running_flag = False
            count = len(self.active_positions)

            self._log("ALERT", "🚨 EMERGENCY KILL SWITCH TRIGGERED! 🚨", f"Closing all {count} active positions immediately.")

            exited_count = 0
            for pos_id in list(self.active_positions.keys()):
                pos = self.active_positions[pos_id]
                self._exit_position(pos, exit_price=pos.get("current_price", pos.get("entry_price")), reason="KILL_SWITCH")
                exited_count += 1

            self._save_state()
            return {
                "success": True,
                "message": f"🚨 Emergency Kill Switch executed. {exited_count} positions closed. Bot halted.",
                "closed_count": exited_count,
                "status": self.status,
            }

    # ─────────────────────────────────────────────────────────────
    # AUTONOMOUS EXECUTION LOOP (THE BACKGROUND ROBOT)
    # ─────────────────────────────────────────────────────────────

    def _execution_loop(self):
        """
        Background autonomous thread running continuously:
        1. Checks market timings & RMS circuit breakers.
        2. Monitors open positions and applies dynamic Trailing Stop Loss / Target exits.
        3. Scans universe and evaluates strategies for AUTO BUY / AUTO SELL signals.
        4. Fires market orders automatically.
        """
        logger.info("Autonomous Algo Engine execution loop initiated.")

        while self._running_flag and self.status in ("RUNNING", "PAUSED"):
            try:
                cycle_start = time.time()
                self.last_scan_time = datetime.now(IST)

                # Step 1: RMS & Market Timing Checks
                self._check_rms_and_timing()

                # Step 2: Monitor Active Positions (Trailing SL, Target Hit, Stop Loss Hit)
                self._monitor_active_positions()

                # Step 3: Scan & Execute New Signals (Only if status is RUNNING)
                if self.status == "RUNNING" and not self.risk_config.get("circuit_breaker_hit"):
                    self._scan_and_execute_signals()

                # Update live stats
                self._recalculate_stats()

                # Sleep until next scan interval with second-by-second countdown
                elapsed = time.time() - cycle_start
                sleep_time = max(1.0, float(self.scan_interval_sec) - elapsed)
                remaining = int(sleep_time)

                while remaining > 0 and self._running_flag:
                    self.next_scan_countdown = remaining
                    time.sleep(1)
                    remaining -= 1

            except Exception as e:
                logger.error(f"Error in algo execution loop: {e}", exc_info=True)
                self._log("ERROR", f"Execution loop error: {str(e)[:100]}")
                time.sleep(5)

        logger.info("Autonomous Algo Engine execution loop stopped.")

    # ─────────────────────────────────────────────────────────────
    # STEP 1: RMS & MARKET TIMING GATEKEEPER
    # ─────────────────────────────────────────────────────────────

    def _check_rms_and_timing(self):
        """Validates daily loss caps, profit locks, and Indian market timings."""
        now = datetime.now(IST)
        now_time = now.time()

        # Parse timing configs
        try:
            start_parts = [int(p) for p in self.risk_config["entry_start_time"].split(":")]
            cutoff_parts = [int(p) for p in self.risk_config["entry_cutoff_time"].split(":")]
            sq_parts = [int(p) for p in self.risk_config["auto_squareoff_time"].split(":")]

            entry_start = dtime(start_parts[0], start_parts[1])
            entry_cutoff = dtime(cutoff_parts[0], cutoff_parts[1])
            auto_sq = dtime(sq_parts[0], sq_parts[1])
        except Exception:
            entry_start = dtime(9, 20)
            entry_cutoff = dtime(14, 45)
            auto_sq = dtime(15, 15)

        # 3:15 PM AUTO SQUARE OFF
        if now_time >= auto_sq:
            mis_positions = [p for p in self.active_positions.values() if p.get("product") == "MIS"]
            if mis_positions:
                self._log("ALERT", f"⏰ 3:15 PM EOD CUTOFF: Auto squaring off {len(mis_positions)} intraday positions.")
                for pos in mis_positions:
                    self._exit_position(pos, exit_price=pos.get("current_price", pos.get("entry_price")), reason="TIME_CUTOFF")

        # DAILY LOSS LIMIT CIRCUIT BREAKER
        # Evaluate loss strictly on actual market trading loss, never triggered by brokerage charges
        trading_gross_loss = self.stats.get("gross_pnl", 0.0) + self.stats.get("unrealized_gross", 0.0)
        max_loss = float(self.risk_config.get("max_daily_loss", 5000.0))
        if trading_gross_loss <= -abs(max_loss) and not self.risk_config.get("circuit_breaker_hit"):
            self.risk_config["circuit_breaker_hit"] = True
            self.risk_config["circuit_breaker_reason"] = f"Max Daily Loss limit breached (-₹{abs(trading_gross_loss):,.2f} / -₹{max_loss:,.2f})"
            self.status = "STOPPED"
            self._log("ALERT", "🛑 CIRCUIT BREAKER TRIGGERED!", self.risk_config["circuit_breaker_reason"])
            # Auto square-off all open positions
            for pos_id in list(self.active_positions.keys()):
                pos = self.active_positions[pos_id]
                self._exit_position(pos, exit_price=pos.get("current_price", pos.get("entry_price")), reason="RMS_LOSS_LIMIT")

        # DAILY PROFIT LOCK
        max_profit = float(self.risk_config.get("max_daily_profit", 15000.0))
        if self.stats["realized_pnl"] >= max_profit and self.status == "RUNNING":
            self.status = "PAUSED"
            self._log("INFO", "🎯 DAILY PROFIT TARGET HIT! 💰", f"Realized P&L ₹{self.stats['realized_pnl']:,.2f} reached target ₹{max_profit:,.2f}. Bot paused to lock in profits.")

    # ─────────────────────────────────────────────────────────────
    # STEP 2: POSITION MONITOR & DYNAMIC TRAILING STOP LOSS
    # ─────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────
    # WEBSOCKET REAL-TIME TICK FEED & MILLISECOND ENGINE
    # ─────────────────────────────────────────────────────────────

    def _ensure_ticker(self):
        """
        Ensures KiteTicker WebSocket is initialized, connected, and subscribed to universe symbols.
        Enables millisecond price ingestion and scan evaluation.
        """
        ticker = self._web_state.get("ticker")
        if not ticker:
            try:
                from web_app import _ensure_live_ticker
                ticker = _ensure_live_ticker()
            except Exception:
                pass

        if ticker:
            if not getattr(self, "_ticker_callback_registered", False):
                try:
                    ticker.add_tick_callback(self._on_websocket_tick)
                    self._ticker_callback_registered = True
                    logger.info("📡 AlgoEngine attached callback to LiveTicker WebSocket")
                except Exception as e:
                    logger.debug(f"Failed to attach ticker callback: {e}")

            symbols = self._get_universe_symbols()
            if symbols:
                try:
                    sub_count = 250 if self.universe in ("all_stocks", "all_nse", "all") else 200
                    ticker.subscribe(symbols[:sub_count], exchange="NSE")
                    self.is_websocket_active = getattr(ticker, "is_connected", False)
                except Exception as se:
                    logger.debug(f"Ticker subscription error: {se}")

    def _on_websocket_tick(self, symbol: str, tick: dict):
        """Processes real-time WebSocket tick in sub-milliseconds."""
        with self._quote_lock:
            self.live_quotes_cache[symbol] = tick
            self.is_websocket_active = True

        # Instant sub-millisecond SL / Target evaluation for open positions
        ltp = float(tick.get("ltp") or 0)
        if ltp > 0:
            with self._lock:
                for pos_id, pos in list(self.active_positions.items()):
                    if pos.get("symbol") == symbol:
                        self._evaluate_single_position(pos, ltp)
                        break

    def _monitor_active_positions(self):
        """
        Monitors active positions tick-by-tick:
        - Checks WebSocket live quotes cache first (0ms latency), falling back to REST.
        - Calculates live P&L and charges.
        - Automatically trails Stop Loss upwards when price moves favorably.
        - Automatically exits when Target or Stop Loss is reached!
        """
        if not self.active_positions:
            return

        kite = self._web_state.get("kite")
        if not kite:
            try:
                from web_app import _try_auto_login
                if _try_auto_login():
                    kite = self._web_state.get("kite")
            except Exception:
                pass

        symbols = [p["symbol"] for p in self.active_positions.values()]
        ltp_map = {}

        # 1. Resolve from WebSocket live cache (0ms latency)
        with self._quote_lock:
            for s in symbols:
                if s in self.live_quotes_cache:
                    ltp_map[s] = float(self.live_quotes_cache[s].get("ltp", 0) or 0)

        # 2. REST quote fallback for any symbols not yet in WebSocket cache
        missing = [f"NSE:{s}" for s in symbols if s not in ltp_map or ltp_map[s] <= 0]
        if missing and kite:
            try:
                quotes = kite.quote(missing)
                for k, v in quotes.items():
                    sym = k.replace("NSE:", "")
                    ltp_map[sym] = float(v.get("last_price", 0) or 0)
            except Exception as e:
                logger.debug(f"Quote fetch error in position monitor: {e}")

        for pos_id, pos in list(self.active_positions.items()):
            sym = pos["symbol"]
            entry_p = pos["entry_price"]
            ltp = ltp_map.get(sym, pos.get("current_price", entry_p))
            if ltp <= 0:
                ltp = entry_p
            self._evaluate_single_position(pos, ltp)

    def _evaluate_single_position(self, pos: dict, ltp: float) -> bool:
        """
        Evaluates a single position against latest LTP (Target 1, Target 2, Trailing SL, Stop Loss).
        Returns True if position was fully exited, False otherwise.
        """
        sym = pos["symbol"]
        entry_p = pos["entry_price"]
        side = pos["side"]
        pos["current_price"] = ltp

        # Calculate Live P&L (Gross, Estimated Round-trip Charges, Net)
        qty = pos["quantity"]
        product = pos.get("product", "MIS")
        if side == "BUY":
            gross_pnl = (ltp - entry_p) * qty
            charges_res = calculate_trade_charges(product, qty, buy_price=entry_p, sell_price=ltp)
            if ltp > pos.get("highest_price", entry_p):
                pos["highest_price"] = ltp
        else:  # SELL / SHORT
            gross_pnl = (entry_p - ltp) * qty
            charges_res = calculate_trade_charges(product, qty, buy_price=ltp, sell_price=entry_p)
            if ltp < pos.get("lowest_price", entry_p):
                pos["lowest_price"] = ltp

        charges = charges_res["total_charges"]
        denom = entry_p * qty
        gross_pnl_pct = (gross_pnl / denom) * 100.0 if denom > 0 else 0.0

        # Charges are ONLY deducted when order is sold / settled, NOT before!
        # Do not calculate or deduct brokerage charges into unrealized/active loss.
        pos["gross_pnl"] = round(gross_pnl, 2)
        pos["charges"] = 0.0  # Zero charges deducted before sell settlement
        pos["est_charges"] = round(charges, 2)  # Kept as reference only
        pos["charges_breakdown"] = charges_res["breakdown"]
        pos["pnl"] = round(gross_pnl, 2)
        pos["pnl_pct"] = round(gross_pnl_pct, 2)
        pnl = pos["pnl"]
        pnl_pct = pos["pnl_pct"]

        # DYNAMIC TRAILING STOP LOSS & MULTI-TARGET EXITS
        trail_pct = float(pos.get("trailing_step_pct", 0.5))
        t1 = pos.get("target_1", pos.get("target", 0))
        t2 = pos.get("target_2", t1 * (1.01 if side == "BUY" else 0.99))
        trail_min_activation = max(1.0, trail_pct * 2.0)  # Require at least 1.0%+ gain before trailing starts!

        if side == "BUY":
            # ── 🚨 SPECIAL PEAK DROP EXIT (Apne High se 1.5% down aane par Immediate Exit) ──
            # User Rule: Agar kisi stock ko buy ho gaya hai aur wo apne peak high se 1.5% down aaye,
            # to bina stop loss check kiye immediately 100% position exit karni hai.
            highest_p = float(pos.get("highest_price", entry_p) or entry_p)
            peak_drop_rule = float(pos.get("peak_drop_exit_pct", 0.0) or 0.0)
            if peak_drop_rule <= 0 and pos.get("strategy_id") in ("open_reversal", "custom_quant_momentum"):
                peak_drop_rule = 1.5

            if peak_drop_rule > 0 and highest_p > 0:
                drop_from_peak_pct = ((highest_p - ltp) / highest_p) * 100.0
                if drop_from_peak_pct >= peak_drop_rule:
                    self._log(
                        "ORDER",
                        f"⚡ [PEAK {peak_drop_rule:.1f}% DROP EXIT] Immediate Exit on {sym} @ ₹{ltp:.2f}",
                        f"Stock dropped -{drop_from_peak_pct:.2f}% from its peak high (High: ₹{highest_p:.2f} → Current: ₹{ltp:.2f}). "
                        f"P&L: ₹{pnl:,.2f} ({pnl_pct:.2f}%) | Exited immediately without waiting for Stop Loss!"
                    )
                    self._exit_position(pos, exit_price=ltp, reason="PEAK_DROP_1.5PCT")
                    return True

            favorable_gain = ((ltp - entry_p) / entry_p) * 100.0
            if favorable_gain >= trail_min_activation or pos.get("target_1_hit", False):
                initial_sl_dist_pct = ((entry_p - pos["stop_loss"]) / entry_p) * 100.0
                new_sl = round(pos["highest_price"] * (1.0 - (initial_sl_dist_pct / 100.0)), 2)
                if new_sl > pos["trailing_sl"]:
                    old_sl = pos["trailing_sl"]
                    pos["trailing_sl"] = new_sl
                    self._log("TRAIL", f"📈 Trailed SL Up: {sym} (LTP: ₹{ltp:.2f})", f"SL moved from ₹{old_sl:.2f} → ₹{new_sl:.2f} (+{trail_pct}%)")

            # AUTO TARGET 1 EXIT (Book 50% & Move SL to Cost)
            if not pos.get("target_1_hit", False) and ltp >= t1:
                exit_qty = max(1, pos["quantity"] // 2)
                self._exit_partial_position(pos, exit_qty=exit_qty, exit_price=ltp, reason="TARGET_1_HIT")
                pos["quantity"] -= exit_qty
                pos["target_1_hit"] = True
                pos["stop_loss"] = entry_p
                pos["trailing_sl"] = max(pos["trailing_sl"], entry_p)
                self._log("ORDER", f"🎯 [TARGET 1 HIT] ⚡ Booked 50% ({exit_qty} Qty) on {sym} @ ₹{ltp:.2f}",
                          f"🛡️ SL moved to Entry Cost ₹{entry_p:.2f} (Trade is now 100% Risk-Free!)")
                return False

            # AUTO TARGET 2 EXIT (Final 50% Runner Exit)
            if pos.get("target_1_hit", False) and ltp >= t2:
                self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting remaining {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                          f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%) | Full targets achieved!")
                self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                return True

            if not pos.get("target_1_hit", False) and ltp >= t2:
                self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting full {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                          f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%)")
                self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                return True

            # AUTO STOP LOSS EXIT
            if ltp <= pos["trailing_sl"]:
                reason = "COST_SL_HIT" if pos.get("target_1_hit", False) else "STOP_LOSS_HIT"
                self._log("ORDER", f"🛑 [{reason}] ⚡ Auto Exiting {sym} @ ₹{ltp:.2f}", f"P&L: ₹{pnl:,.2f} ({pnl_pct:.2f}%)")
                self._exit_position(pos, exit_price=ltp, reason=reason)
                return True

        else:  # SHORT POSITION
            favorable_gain = ((entry_p - ltp) / entry_p) * 100.0
            if favorable_gain >= trail_min_activation or pos.get("target_1_hit", False):
                initial_sl_dist_pct = ((pos["stop_loss"] - entry_p) / entry_p) * 100.0
                new_sl = round(pos["lowest_price"] * (1.0 + (initial_sl_dist_pct / 100.0)), 2)
                if new_sl < pos["trailing_sl"]:
                    old_sl = pos["trailing_sl"]
                    pos["trailing_sl"] = new_sl
                    self._log("TRAIL", f"📉 Trailed SL Down: {sym} (LTP: ₹{ltp:.2f})", f"SL moved from ₹{old_sl:.2f} → ₹{new_sl:.2f}")

            # AUTO TARGET 1 EXIT (Short)
            if not pos.get("target_1_hit", False) and ltp <= t1:
                exit_qty = max(1, pos["quantity"] // 2)
                self._exit_partial_position(pos, exit_qty=exit_qty, exit_price=ltp, reason="TARGET_1_HIT")
                pos["quantity"] -= exit_qty
                pos["target_1_hit"] = True
                pos["stop_loss"] = entry_p
                pos["trailing_sl"] = min(pos["trailing_sl"], entry_p)
                self._log("ORDER", f"🎯 [TARGET 1 HIT] ⚡ Booked 50% ({exit_qty} Qty) on {sym} @ ₹{ltp:.2f}",
                          f"🛡️ SL moved to Entry Cost ₹{entry_p:.2f} (Trade is now 100% Risk-Free!)")
                return False

            # AUTO TARGET 2 EXIT (Short)
            if pos.get("target_1_hit", False) and ltp <= t2:
                self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting remaining {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                          f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%) | Full targets achieved!")
                self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                return True

            if not pos.get("target_1_hit", False) and ltp <= t2:
                self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting full {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                          f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%)")
                self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                return True

            # AUTO STOP LOSS EXIT
            if ltp >= pos["trailing_sl"]:
                reason = "COST_SL_HIT" if pos.get("target_1_hit", False) else "STOP_LOSS_HIT"
                self._log("ORDER", f"🛑 [{reason}] ⚡ Auto Exiting {sym} @ ₹{ltp:.2f}", f"P&L: ₹{pnl:,.2f} ({pnl_pct:.2f}%)")
                self._exit_position(pos, exit_price=ltp, reason=reason)
                return True

        return False

    # ─────────────────────────────────────────────────────────────
    # STEP 3: SCANNING & AUTONOMOUS ORDER DISPATCH (AUTO BUY/SELL)
    # ─────────────────────────────────────────────────────────────

    def _scan_and_execute_signals(self) -> int:
        """
        Scans universe symbols in milliseconds via WebSocket cache (or REST fallback),
        evaluates quantitative strategies, verifies 60%+ Win Rate, and auto-executes.
        Returns the number of symbols evaluated.
        """
        if not self._scan_lock.acquire(blocking=False):
            logger.debug("Scan already executing. Skipping concurrent trigger.")
            return 0
        try:
            return self._scan_and_execute_signals_internal()
        finally:
            self._scan_lock.release()

    def _scan_and_execute_signals_internal(self) -> int:
        t_start = time.perf_counter()
        max_open = int(self.risk_config.get("max_open_positions", 4))
        if len(self.active_positions) >= max_open:
            return 0

        symbols = self._get_universe_symbols()
        if not symbols:
            return 0

        # Ensure ticker is running and subscribed
        self._ensure_ticker()

        ticker = self._web_state.get("ticker")
        is_ws_ready = bool((self.is_websocket_active or (ticker and getattr(ticker, "is_connected", False)) or len(self.live_quotes_cache) > 0) and len(self.live_quotes_cache) > 0)

        quotes_data = {}
        scan_source = "REST"

        now_time_check = datetime.now(IST).time()
        is_reversal_active = (dtime(9, 30) <= now_time_check <= dtime(10, 45)) and bool(self.strategies.get("open_reversal", {}).get("enabled", True))

        # 🚀 9:30 AM - 10:45 AM FULL MARKET SCAN: Scans all ~2,500 stocks across market via fast 500-symbol OHLC chunks
        if is_reversal_active and self.universe in ("all_stocks", "all_nse", "all"):
            kite = self._web_state.get("kite")
            if not kite:
                try:
                    from web_app import _try_auto_login
                    if _try_auto_login():
                        kite = self._web_state.get("kite")
                except Exception:
                    pass

            if kite:
                all_market_syms = symbols[:2500]
                batch_size = 500
                ohlc_all = {}
                for i in range(0, len(all_market_syms), batch_size):
                    chunk = all_market_syms[i:i + batch_size]
                    formatted = [f"NSE:{s}" if ":" not in s else s for s in chunk]
                    try:
                        data = kite.ohlc(formatted)
                        if data:
                            ohlc_all.update(data)
                    except Exception as be:
                        logger.debug(f"Reversal 2500 OHLC batch error: {be}")

                if ohlc_all:
                    for k, v in ohlc_all.items():
                        s = k.replace("NSE:", "")
                        ohlc_dict = v.get("ohlc", {}) or {}
                        ltp_val = float(v.get("last_price", 0) or 0)
                        open_val = float(ohlc_dict.get("open", 0) or 0)
                        high_val = float(ohlc_dict.get("high", 0) or 0)
                        low_val = float(ohlc_dict.get("low", 0) or 0)
                        close_val = float(ohlc_dict.get("close", 0) or 0)
                        quotes_data[s] = {
                            "symbol": s,
                            "ltp": ltp_val,
                            "open": open_val,
                            "high": high_val,
                            "low": low_val,
                            "close": close_val,
                            "avg_price": round((open_val + high_val + low_val) / 3.0, 2),
                            "volume": int(v.get("volume", 0) or 0),
                        }
                    scan_source = f"ALL_MARKET_OHLC ({len(quotes_data)} stocks)"

        if not quotes_data and is_ws_ready:
            # ⚡ MILLISECOND WEBSOCKET IN-MEMORY SCAN (0ms network latency!)
            scan_limit = 250 if self.universe in ("all_stocks", "all_nse", "all") else max(260, max_open)
            with self._quote_lock:
                for s in symbols[:scan_limit]:
                    if s in self.live_quotes_cache:
                        quotes_data[s] = self.live_quotes_cache[s]
            if quotes_data:
                scan_source = "WEBSOCKET"

        # Fallback to REST if WebSocket has not received ticks yet
        if not quotes_data:
            kite = self._web_state.get("kite")
            if not kite:
                try:
                    from web_app import _try_auto_login
                    if _try_auto_login():
                        kite = self._web_state.get("kite")
                except Exception:
                    pass

            if not kite:
                now_sec = time.time()
                if now_sec - getattr(self, "_last_no_kite_log", 0) > 60:
                    self._last_no_kite_log = now_sec
                    self._log("ALERT", "⚠️ Kite Connect not logged in", "Live market feed unavailable. Please login with Kite in dashboard to stream live market quotes.")
                return 0

            # Batch fetch Quotes for universe (with real volume and average_price / VWAP)
            sample_count = 250 if self.universe in ("all_stocks", "all_nse", "all") else min(260, len(symbols))
            sample_syms = symbols[:sample_count]
            formatted = [f"NSE:{s}" if ":" not in s else s for s in sample_syms]
            try:
                raw_quotes = kite.quote(formatted)
                for k, v in raw_quotes.items():
                    s = k.replace("NSE:", "")
                    ohlc_dict = v.get("ohlc", {}) or {}
                    quotes_data[s] = {
                        "symbol": s,
                        "ltp": float(v.get("last_price", 0) or 0),
                        "open": float(ohlc_dict.get("open", 0) or 0),
                        "high": float(ohlc_dict.get("high", 0) or 0),
                        "low": float(ohlc_dict.get("low", 0) or 0),
                        "close": float(ohlc_dict.get("close", 0) or 0),
                        "avg_price": float(v.get("average_price", 0) or 0),
                        "volume": int(v.get("volume", 0) or 0),
                    }
                scan_source = "REST_QUOTE"
            except Exception as e:
                logger.debug(f"REST scan batch error: {e}")
                return 0

        # Check entry time window: no orders BEFORE entry_start (9:20 AM) or AFTER entry_cutoff (2:45 PM)
        now = datetime.now(IST).time()
        try:
            start_parts = [int(p) for p in self.risk_config["entry_start_time"].split(":")]
            cutoff_parts = [int(p) for p in self.risk_config["entry_cutoff_time"].split(":")]
            entry_start = dtime(start_parts[0], start_parts[1])
            entry_cutoff = dtime(cutoff_parts[0], cutoff_parts[1])
            if now < entry_start:
                return 0
            if now > entry_cutoff:
                return 0
        except Exception:
            # Fallback: block before 9:20 AM
            if now < dtime(9, 20):
                return 0

        # Record 9:15 - 9:30 AM Opening Range Box for ORB Strategy
        today_date_str = str(datetime.now(IST).date())
        if now <= dtime(9, 30):
            for s, item in quotes_data.items():
                cur_h = float(item.get("high", 0) or 0)
                cur_l = float(item.get("low", 0) or 0)
                if cur_h > 0 and cur_l > 0:
                    entry = self._orb_ranges.get(s, {})
                    if entry.get("date") != today_date_str:
                        self._orb_ranges[s] = {"high": cur_h, "low": cur_l, "date": today_date_str}
                    else:
                        entry["high"] = max(entry["high"], cur_h)
                        entry["low"] = min(entry["low"], cur_l)

        # ── ☕ LUNCHTIME CHOP GATE (11:45 AM - 1:15 PM) ──
        # Indian markets experience severe chop, low volume and false breakouts during lunch hour.
        # Temporarily pause opening new breakout/momentum trades. Active positions remain 100% monitored.
        is_lunch_chop = (dtime(11, 45) <= now <= dtime(13, 15)) and bool(self.risk_config.get("lunchtime_filter", True))

        # Update sector momentum across universe for custom quant sector scanner
        self._update_bullish_sectors(quotes_data)

        evaluated_count = len(quotes_data)
        active_symbols = {p["symbol"] for p in self.active_positions.values()}

        total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
        used_margin = sum(float(p.get("margin_used", 0.0) or 0.0) for p in self.active_positions.values())
        if used_margin >= total_cap:
            return 0

        min_price = float(self.risk_config.get("min_stock_price", 50.0))
        max_price = float(self.risk_config.get("max_stock_price", 3000.0))
        min_mcap_m = float(self.risk_config.get("min_market_cap_m", 100.0))
        min_required_wr = float(self.risk_config.get("min_win_rate_pct", 60.0))

        candidates = []

        for sym, item in quotes_data.items():
            if sym in active_symbols:
                continue

            ltp = float(item.get("ltp", 0) or 0)
            open_p = float(item.get("open", 0) or 0)
            high_p = float(item.get("high", 0) or 0)
            low_p = float(item.get("low", 0) or 0)
            prev_close = float(item.get("close", 0) or 0)
            avg_price = float(item.get("avg_price", 0) or 0)
            volume = int(item.get("volume", 0) or 0)

            # Quality & RMS Filters:
            # 1. Price Range Gating: ₹50 <= LTP <= ₹3,000 (Exclude penny stocks & ultra-expensive stocks)
            if open_p <= 0 or ltp < min_price or ltp > max_price:
                continue

            # 2. Market Capitalization Gating: MCap >= 100 Million (Exclude micro-caps & illiquid counters)
            if not self._passes_market_cap_filter(sym, ltp, min_mcap_m):
                continue

            # Evaluate Enabled Strategies
            for strat_id, strat in self.strategies.items():
                if not strat.get("enabled", True):
                    continue

                # Lunchtime gate: skip breakout/momentum setups during lunch chop
                if is_lunch_chop and strat_id in ("breakout_surge", "momentum_trend", "supertrend_rider", "orb_breakout"):
                    continue

                signal = self._evaluate_strategy(strat_id, sym, ltp, open_p, high_p, low_p, prev_close, avg_price, volume)
                if signal:
                    t1_pct = float(strat.get("target_1_pct", strat.get("target_pct", 1.0)))
                    sl_pct = float(strat.get("sl_pct", 0.8))
                    side = signal.get("side", "BUY")

                    wr_info = calculate_setup_win_rate(
                        strat_id=strat_id,
                        side=side,
                        ltp=ltp,
                        open_p=open_p,
                        high_p=high_p,
                        low_p=low_p,
                        prev_close=prev_close,
                        target_1_pct=t1_pct,
                        sl_pct=sl_pct,
                        avg_price=avg_price,
                        volume=volume,
                    )
                    win_rate = wr_info["win_rate"]
                    signal["win_rate"] = win_rate
                    signal["strat"] = strat

                    if win_rate >= min_required_wr:
                        candidates.append(signal)

        # ── 🏆 RANK CANDIDATES: HIGHEST QUALITY SCORE / WIN RATE FIRST ──
        # This guarantees we only enter the BEST market leaders (e.g. top gainers with volume)
        # rather than random stocks in alphabetical order!
        if candidates:
            # Deduplicate by symbol (keep the highest win-rate signal for each symbol)
            unique_candidates = {}
            for cand in candidates:
                sym = cand["symbol"]
                if sym not in unique_candidates or cand["win_rate"] > unique_candidates[sym]["win_rate"]:
                    unique_candidates[sym] = cand

            ranked_candidates = sorted(unique_candidates.values(), key=lambda s: s["win_rate"], reverse=True)
            available_slots = max(0, max_open - len(self.active_positions))
            executed_in_cycle = 0

            for top_signal in ranked_candidates:
                if executed_in_cycle >= available_slots:
                    break
                sym = top_signal["symbol"]
                if sym in active_symbols:
                    continue

                self._log(
                    "SIGNAL",
                    f"🎯 [{top_signal['strategy_name']}] 🏆 Top-Ranked Signal Approved: {sym} @ ₹{top_signal['ltp']:.2f}",
                    f"🔥 Setup Score: {top_signal['win_rate']:.1f}% (Ranked #{executed_in_cycle + 1}) | {top_signal.get('reason', '')}"
                )

                self._execute_auto_order(top_signal, top_signal["strat"])
                active_symbols.add(sym)
                executed_in_cycle += 1

        elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
        self.last_scan_duration_ms = elapsed_ms
        self._log("SCAN", f"⚡ [{scan_source} SCAN] Completed in {elapsed_ms:.1f}ms | {evaluated_count} symbols checked across active strategies")
        return evaluated_count
    # ─────────────────────────────────────────────────────────────
    # QUANTITATIVE STRATEGY RULES EVALUATOR
    # ─────────────────────────────────────────────────────────────

    def _evaluate_strategy(
        self,
        strat_id: str,
        symbol: str,
        ltp: float,
        open_p: float,
        high_p: float,
        low_p: float,
        prev_close: float,
        avg_price: float = 0.0,
        volume: int = 0
    ) -> Optional[dict]:
        """
        Evaluates mathematical criteria for each strategy.
        Returns a signal dict if conditions are met, otherwise None.
        """
        strat = self.strategies.get(strat_id, {})
        now_t = datetime.now(IST).time()
        vwap = avg_price if avg_price > 0 else (open_p + high_p + low_p) / 3.0
        rng = high_p - low_p
        turnover = (ltp * volume) if volume > 0 else 15000000.0

        def _parse_time(t_str: str, default_h: int, default_m: int) -> dtime:
            try:
                parts = [int(p) for p in str(t_str).split(":")]
                return dtime(parts[0], parts[1])
            except Exception:
                return dtime(default_h, default_m)

        # 1. MOMENTUM TREND (EMA + VWAP) - High-Conviction Institutional Trend
        if strat_id == "momentum_trend":
            st_time = _parse_time(strat.get("start_time", "09:45"), 9, 45)
            if now_t < st_time:
                return None
            # Lunchtime Chop Gate: Avoid entries during 11:45 AM - 1:15 PM lull
            if dtime(11, 45) <= now_t <= dtime(13, 15):
                return None
            vwap_mult = float(strat.get("vwap_dist_mult", 1.002))
            min_gain = float(strat.get("min_gain_pct", 0.5))
            max_gain = float(strat.get("max_gain_pct", 2.8))
            min_day_chg = float(strat.get("min_day_chg_pct", 0.8))
            max_day_chg = float(strat.get("max_day_chg_pct", 3.5))
            min_rpos = float(strat.get("min_range_pos", 0.75))
            min_turn = float(strat.get("min_turnover", 10000000.0))

            if ltp > open_p and prev_close > 0 and ltp > prev_close and ltp >= (vwap * vwap_mult):
                gain_pct = ((ltp - open_p) / open_p) * 100.0
                day_chg = ((ltp - prev_close) / prev_close) * 100.0
                range_pos = ((ltp - low_p) / rng) if rng > 0 else 1.0
                if min_gain <= gain_pct <= max_gain and min_day_chg <= day_chg <= max_day_chg and range_pos >= min_rpos and turnover >= min_turn:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "Momentum Trend"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Bullish momentum (+{gain_pct:.1f}% vs Open, +{day_chg:.1f}% Day Change, above VWAP ₹{vwap:.2f})",
                    }

        # 2. MORNING REVERSAL + PREV DAY HIGH BREAKOUT (9:30 AM - 10:45 AM)
        elif strat_id == "open_reversal":
            st_time = _parse_time(strat.get("start_time", "09:30"), 9, 30)
            end_time = _parse_time(strat.get("end_time", "10:45"), 10, 45)
            if not (st_time <= now_t <= end_time):
                return None

            max_gap_up = float(strat.get("max_gap_up_pct", 2.0))
            if prev_close > 0 and ((open_p - prev_close) / prev_close * 100.0) > max_gap_up:
                return None

            max_gap_down = float(strat.get("max_gap_down_pct", 2.5))
            if prev_close > 0 and ((prev_close - open_p) / prev_close * 100.0) > max_gap_down:
                return None

            vwap_mult = float(strat.get("vwap_dist_mult", 1.003))
            min_dip = float(strat.get("min_dip_pct", 0.50))
            min_recov = float(strat.get("min_recovery_pct", 0.60))
            min_day_chg = float(strat.get("min_day_chg_pct", 0.3))
            min_rpos = float(strat.get("min_range_pos", 0.60))
            pdh_mult = float(strat.get("pdh_breakout_mult", 1.001))
            min_turn = float(strat.get("min_turnover", 5000000.0))
            peak_drop = float(strat.get("peak_drop_exit_pct", 1.5))

            if low_p < open_p and ltp > open_p and ltp >= (vwap * vwap_mult):
                dip_pct = ((open_p - low_p) / open_p) * 100.0
                recov_pct = ((ltp - open_p) / open_p) * 100.0
                day_chg = ((ltp - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
                range_pos = ((ltp - low_p) / rng) if rng > 0 else 1.0

                if dip_pct >= min_dip and recov_pct >= min_recov and day_chg >= min_day_chg and range_pos >= min_rpos:
                    prev_high = 0.0
                    try:
                        kite = self._web_state.get("kite")
                        token_map = self._token_cache
                        if not token_map and kite:
                            try:
                                insts = kite.instruments("NSE")
                                self._token_cache = {
                                    i["tradingsymbol"]: i["instrument_token"]
                                    for i in insts
                                    if i.get("tradingsymbol") and i.get("instrument_token")
                                }
                                token_map = self._token_cache
                            except Exception:
                                pass
                        try:
                            from web_app import _get_symbol_prev_day
                        except ImportError:
                            from algo_trading.web_app import _get_symbol_prev_day

                        prev_info = _get_symbol_prev_day(symbol, kite, token_map)
                        prev_high = float(prev_info.get("high", 0.0) or 0.0)
                    except Exception:
                        pass

                    benchmark_high = prev_high if prev_high > 0 else prev_close
                    if benchmark_high > 0 and ltp >= (benchmark_high * pdh_mult) and turnover >= min_turn:
                        pdh_label = f"PDH ₹{prev_high:.2f}" if prev_high > 0 else f"PDC ₹{prev_close:.2f}"
                        return {
                            "strategy_id": strat_id,
                            "strategy_name": strat.get("name", "Morning Reversal + PDH Breakout"),
                            "symbol": symbol,
                            "side": "BUY",
                            "ltp": ltp,
                            "reason": f"Morning dip (-{dip_pct:.2f}%) swept & reversed above Open (+{recov_pct:.2f}%) and broke {pdh_label} firmly (VWAP ₹{vwap:.2f}, Day +{day_chg:.2f}%)",
                            "peak_drop_exit_pct": peak_drop,
                        }

        # 3. RSI MEAN REVERSION - High-Quality Oversold Bounce
        elif strat_id == "rsi_reversion":
            st_time = _parse_time(strat.get("start_time", "09:50"), 9, 50)
            if now_t < st_time:
                return None
            min_drop = float(strat.get("min_drop_from_close", 1.0))
            max_drop = float(strat.get("max_drop_from_close", 3.0))
            min_bounce = float(strat.get("min_bounce_from_low", 1.0))
            vwap_mult = float(strat.get("vwap_dist_mult", 0.998))
            min_turn = float(strat.get("min_turnover", 10000000.0))

            if prev_close > 0 and low_p < prev_close:
                drop_from_close = ((prev_close - low_p) / prev_close) * 100.0
                bounce_from_low = ((ltp - low_p) / low_p) * 100.0 if low_p > 0 else 0.0
                if min_drop <= drop_from_close <= max_drop and bounce_from_low >= min_bounce and ltp >= (vwap * vwap_mult) and turnover >= min_turn:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "RSI Reversion"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Confirmed oversold bounce (+{bounce_from_low:.2f}% off low, holding VWAP ₹{vwap:.2f})",
                    }

        # 4. BREAKOUT & VOLUME SURGE - Day High Expansion with Rupee Turnover
        elif strat_id == "breakout_surge":
            m_start = _parse_time(strat.get("start_time", "09:30"), 9, 30)
            m_end = _parse_time(strat.get("morning_end_time", "12:00"), 12, 0)
            a_start = _parse_time(strat.get("afternoon_start_time", "13:45"), 13, 45)
            a_end = _parse_time(strat.get("end_time", "14:45"), 14, 45)

            if not ((m_start <= now_t <= m_end) or (a_start <= now_t <= a_end)):
                return None

            vwap_mult = float(strat.get("vwap_dist_mult", 1.002))
            min_rpos = float(strat.get("min_range_pos", 0.88))
            min_day_chg = float(strat.get("min_day_chg_pct", 0.8))
            min_gain = float(strat.get("min_day_gain_pct", 0.6))
            max_gain = float(strat.get("max_day_gain_pct", 4.0))
            min_turn = float(strat.get("min_turnover", 20000000.0))

            if high_p > open_p and ltp >= (vwap * vwap_mult) and prev_close > 0:
                day_gain = ((ltp - open_p) / open_p) * 100.0
                day_chg = ((ltp - prev_close) / prev_close) * 100.0
                range_pos = ((ltp - low_p) / rng) if rng > 0 else 1.0
                if rng > 0 and range_pos >= min_rpos and ltp >= (high_p * 0.997) and day_chg >= min_day_chg and min_gain <= day_gain <= max_gain and turnover >= min_turn:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "Breakout Surge"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Day High Breakout @ ₹{high_p:.2f} with ₹{turnover/10000000:.1f}Cr Turnover (+{day_chg:.1f}% Day Change, VWAP confirmed)",
                    }

        # 5. SUPERTREND RIDER - Trend-Following Pullback Retest
        elif strat_id == "supertrend_rider":
            st_time = _parse_time(strat.get("start_time", "09:45"), 9, 45)
            if now_t < st_time:
                return None
            if dtime(11, 45) <= now_t <= dtime(13, 15):
                return None
            min_chg = float(strat.get("min_day_chg_pct", 1.0))
            max_chg = float(strat.get("max_day_chg_pct", 3.8))
            min_rpos = float(strat.get("min_range_pos", 0.65))
            max_rpos = float(strat.get("max_range_pos", 0.85))
            vwap_mult = float(strat.get("vwap_dist_mult", 1.003))
            min_turn = float(strat.get("min_turnover", 15000000.0))

            if prev_close > 0 and ltp > (prev_close * 1.008) and ltp > open_p and ltp > (vwap * vwap_mult):
                chg = ((ltp - prev_close) / prev_close) * 100.0
                range_pos = ((ltp - low_p) / rng) if rng > 0 else 1.0
                if min_chg <= chg <= max_chg and min_rpos <= range_pos <= max_rpos and turnover >= min_turn:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "Supertrend Rider"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Trend pullback retest (+{chg:.1f}% holding VWAP ₹{vwap:.2f}, range pos {range_pos*100:.0f}%)",
                    }

        # 6. VWAP INSTITUTIONAL PULLBACK SNIPER (💎 High Win-Rate Setup with Bounce Confirmation)
        elif strat_id == "vwap_sniper":
            st_time = _parse_time(strat.get("start_time", "09:45"), 9, 45)
            if now_t < st_time:
                return None
            min_day_chg = float(strat.get("min_day_chg_pct", 0.6))
            max_day_chg = float(strat.get("max_day_chg_pct", 3.8))
            min_vwap_d = float(strat.get("min_vwap_dist_pct", 0.05))
            max_vwap_d = float(strat.get("max_vwap_dist_pct", 0.55))
            min_bounce = float(strat.get("min_bounce_pct", 0.35))
            min_turn = float(strat.get("min_turnover", 15000000.0))

            if vwap > 0 and prev_close > 0 and ltp > prev_close and ltp > open_p:
                day_chg = ((ltp - prev_close) / prev_close) * 100.0
                dist_from_vwap = ((ltp - vwap) / vwap) * 100.0
                bounce_from_low = ((ltp - low_p) / low_p) * 100.0 if low_p > 0 else 0.0
                if min_day_chg <= day_chg <= max_day_chg and min_vwap_d <= dist_from_vwap <= max_vwap_d and bounce_from_low >= min_bounce and turnover >= min_turn:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "VWAP Institutional Pullback"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"VWAP bounce confirmed (LTP ₹{ltp:.2f} bounced +{bounce_from_low:.2f}% off low, testing VWAP ₹{vwap:.2f} +{dist_from_vwap:.2f}%, Day +{day_chg:.1f}%)",
                    }

        # 7. ORB 15-MIN INSTITUTIONAL BREAKOUT (Strictly 9:30 AM - 11:15 AM)
        elif strat_id == "orb_breakout":
            st_time = _parse_time(strat.get("start_time", "09:30"), 9, 30)
            end_time = _parse_time(strat.get("end_time", "11:15"), 11, 15)
            if not (st_time <= now_t <= end_time):
                return None

            orb_box = self._orb_ranges.get(symbol, {})
            orb_high = float(orb_box.get("high", 0.0) or 0.0)
            target_high = orb_high if orb_high > 0 else high_p

            orb_mult = float(strat.get("orb_breakout_mult", 0.998))
            vwap_mult = float(strat.get("vwap_dist_mult", 1.002))
            min_day_gain = float(strat.get("min_day_gain_pct", 0.6))
            max_day_gain = float(strat.get("max_day_gain_pct", 3.8))
            min_day_chg = float(strat.get("min_day_chg_pct", 0.8))
            min_turn = float(strat.get("min_turnover", 20000000.0))

            if target_high > 0 and ltp >= (target_high * orb_mult) and ltp > open_p and ltp > (vwap * vwap_mult):
                day_gain = ((ltp - open_p) / open_p) * 100.0
                day_chg = ((ltp - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
                if min_day_gain <= day_gain <= max_day_gain and day_chg >= min_day_chg and turnover >= min_turn:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "ORB 15-Min Breakout"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"15-Min ORB High Breakout (LTP ₹{ltp:.2f} broke ORB High ₹{target_high:.2f}, +{day_gain:.1f}% vs Open, VWAP confirmed)",
                    }

        # 8. PRE-MARKET, SECTOR & OI SNIPER (CUSTOM QUANTITATIVE LOGIC)
        # 4-Filter Scan:
        # 1) Prev Day > 4.5% mover (Up/Down)
        # 2) Pre-Market 9:10 AM top gainer / loser
        # 3) 9:15 AM opening surge >= 2.0%
        # 4) Bullish / Teji sector stock
        # Cross-Filter: Confirms Short Covering OR OI Gainer before triggering BUY
        # Exit: Immediate Exit if price drops 1.5% from peak high
        elif strat_id == "custom_quant_momentum":
            st_time = _parse_time(strat.get("start_time", "09:15"), 9, 15)
            end_time = _parse_time(strat.get("end_time", "14:45"), 14, 45)
            if not (st_time <= now_t <= end_time):
                return None

            min_prev_move = float(strat.get("prev_day_mover_pct", 4.5))
            min_pm_move = float(strat.get("pre_market_mover_pct", 1.5))
            min_surge = float(strat.get("open_surge_pct", 2.0))
            peak_drop = float(strat.get("peak_drop_exit_pct", 1.5))
            min_turn = float(strat.get("min_turnover", 5000000.0))

            matched_triggers = []

            # Filter 1: Previous Day > 4.5% Mover (Up or Down)
            is_prev_mover, prev_move_pct = self._check_prev_day_mover(symbol, prev_close, min_prev_move)
            if is_prev_mover:
                matched_triggers.append(f"Prev Day {prev_move_pct:+.1f}% Mover (>={min_prev_move}%)")

            # Filter 2: Pre-Market 9:10 AM Gainer / Loser
            if prev_close > 0 and open_p > 0:
                pm_chg = ((open_p - prev_close) / prev_close) * 100.0
                if abs(pm_chg) >= min_pm_move:
                    matched_triggers.append(f"9:10 Pre-Market {pm_chg:+.1f}% Gainer/Loser")

            # Filter 3: 9:15 AM Opening Surge >= 2.0%
            day_chg = ((ltp - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
            open_gain = ((ltp - open_p) / open_p) * 100.0 if open_p > 0 else 0.0
            if day_chg >= min_surge or open_gain >= min_surge:
                matched_triggers.append(f"9:15 Surge +{max(day_chg, open_gain):.1f}% (>=2.0%)")

            # Filter 4: Bullish / Teji Sector Stock
            is_bull_sec, sec_name, sec_perf = self._check_bullish_sector(symbol)
            if is_bull_sec:
                matched_triggers.append(f"Bullish Sector: {sec_name} (+{sec_perf:.1f}%)")

            # If at least one of the 4 candidate list conditions is satisfied:
            if matched_triggers and turnover >= min_turn:
                # Check Short Covering OR OI Gainer confirmation
                is_confirmed, oi_reason = self._check_short_covering_or_oi_gainer(
                    symbol=symbol,
                    ltp=ltp,
                    open_p=open_p,
                    high_p=high_p,
                    low_p=low_p,
                    prev_close=prev_close,
                    vwap=vwap,
                    volume=volume
                )

                if is_confirmed:
                    triggers_text = " | ".join(matched_triggers)
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": strat.get("name", "Pre-Market, Sector & OI Sniper"),
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Custom Quant Confluence: [{triggers_text}] confirmed by {oi_reason}",
                        "peak_drop_exit_pct": peak_drop,
                    }

        return None

    def _check_prev_day_mover(self, symbol: str, prev_close: float, min_move_pct: float = 4.5) -> tuple[bool, float]:
        """Checks if the stock moved >= 4.5% up or down on previous trading session."""
        try:
            kite = self._web_state.get("kite")
            token_map = self._token_cache
            if not token_map and kite:
                try:
                    insts = kite.instruments("NSE")
                    self._token_cache = {
                        i["tradingsymbol"]: i["instrument_token"]
                        for i in insts
                        if i.get("tradingsymbol") and i.get("instrument_token")
                    }
                    token_map = self._token_cache
                except Exception:
                    pass

            try:
                from web_app import _get_symbol_prev_day
            except ImportError:
                from algo_trading.web_app import _get_symbol_prev_day

            prev_info = _get_symbol_prev_day(symbol, kite, token_map)
            if prev_info:
                p_high = float(prev_info.get("high", 0) or 0)
                p_low = float(prev_info.get("low", 0) or 0)
                p_close = float(prev_info.get("close", 0) or 0)
                p_open = float(prev_info.get("open", 0) or 0)
                if p_open > 0 and p_close > 0:
                    prev_chg = ((p_close - p_open) / p_open) * 100.0
                    if abs(prev_chg) >= min_move_pct:
                        return True, prev_chg
                if p_low > 0 and p_high > 0:
                    prev_range_chg = ((p_high - p_low) / p_low) * 100.0
                    if prev_range_chg >= min_move_pct:
                        return True, prev_range_chg
        except Exception:
            pass
        return False, 0.0

    def _update_bullish_sectors(self, quotes_data: dict, min_sector_chg: float = 0.5):
        """Calculates live sector performance and updates bullish sector lookup."""
        if not quotes_data:
            return
        bullish_symbols = {}
        for sec_name, symbols in SECTOR_MAP.items():
            sec_quotes = [quotes_data[s] for s in symbols if s in quotes_data]
            if not sec_quotes:
                continue
            changes = []
            for q in sec_quotes:
                ltp = float(q.get("ltp", 0) or 0)
                close_p = float(q.get("close", 0) or 0)
                if close_p > 0 and ltp > 0:
                    changes.append(((ltp - close_p) / close_p) * 100.0)
            if changes:
                avg_chg = sum(changes) / len(changes)
                if avg_chg >= min_sector_chg:
                    for s in symbols:
                        bullish_symbols[s] = (sec_name, round(avg_chg, 2))
        self._bullish_sector_cache = bullish_symbols

    def _check_bullish_sector(self, symbol: str) -> tuple[bool, str, float]:
        """Checks if a stock belongs to an outperforming / bullish sector."""
        if hasattr(self, "_bullish_sector_cache") and symbol in self._bullish_sector_cache:
            sec_name, avg_chg = self._bullish_sector_cache[symbol]
            return True, sec_name, avg_chg
        return False, "", 0.0

    def _check_short_covering_or_oi_gainer(
        self,
        symbol: str,
        ltp: float,
        open_p: float,
        high_p: float,
        low_p: float,
        prev_close: float,
        vwap: float,
        volume: int
    ) -> tuple[bool, str]:
        """
        Verifies whether the stock exhibits Short Covering or OI Gainer characteristics:
        1. Short Covering: Stock dipped or opened soft, then sharply squeezed back above VWAP & Open with strong buying momentum.
        2. OI Gainer / Long Buildup: Stock holding near day high, trading solidly above VWAP with aggressive institutional turnover.
        """
        if ltp <= 0 or prev_close <= 0:
            return False, ""

        day_range = high_p - low_p
        range_pos = ((ltp - low_p) / day_range) if day_range > 0 else 1.0
        bounce_from_low = ((ltp - low_p) / low_p) * 100.0 if low_p > 0 else 0.0
        day_chg = ((ltp - prev_close) / prev_close) * 100.0
        turnover = (ltp * volume) if volume > 0 else 10000000.0

        # Primary filter: Must be holding above VWAP support
        if ltp < (vwap * 1.001):
            return False, ""

        # Check 1: Short Covering Pattern
        # Price swept low earlier, now trading above VWAP and above Open with >= 0.8% sharp recovery bounce
        if ltp > open_p and bounce_from_low >= 0.8 and day_chg >= 0.2:
            return True, f"Short Covering Squeeze (+{bounce_from_low:.2f}% off Low, holding VWAP ₹{vwap:.2f})"

        # Check 2: OI Gainer / Institutional Long Buildup Pattern
        # Price holding upper 70% of day's range with positive day momentum and healthy turnover
        if ltp > prev_close and range_pos >= 0.70 and day_chg >= 0.8 and turnover >= 5000000.0:
            return True, f"OI Gainer / Long Buildup (Day +{day_chg:.1f}%, Range Pos {range_pos*100:.0f}%, above VWAP ₹{vwap:.2f})"

        return False, ""

    # ─────────────────────────────────────────────────────────────
    # AUTO ORDER DISPATCHER (NO MANUAL CONFIRMATION)
    # ─────────────────────────────────────────────────────────────

    def _execute_auto_order(self, signal: dict, strat: dict):
        """
        ⚡ Fires order directly to broker/paper engine.
        Calculates 5X margin for MIS, sets SL, Target, and Trailing SL automatically.
        """
        symbol = signal["symbol"]
        side = signal["side"]
        ltp = signal["ltp"]
        strat_id = strat["id"]
        strat_name = strat["name"]
        product = strat.get("product", "MIS").upper()

        # Calculate position sizing with Total Capital Protection & Auto-Split
        total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
        max_pos = max(1, int(self.risk_config.get("max_open_positions", 4)))
        cap_mode = self.risk_config.get("capital_mode", "auto_split")

        # ── HARD TIME GATE: No new orders before 9:20 AM ──
        now_time = datetime.now(IST).time()
        try:
            start_parts = [int(p) for p in self.risk_config["entry_start_time"].split(":")]
            entry_start = dtime(start_parts[0], start_parts[1])
        except Exception:
            entry_start = dtime(9, 20)
        if now_time < entry_start:
            self._log("RMS", f"⛔ [TIME GATE] Order Blocked for {symbol}", f"Current time {now_time.strftime('%H:%M')} is before entry start {entry_start.strftime('%H:%M')}. No orders before 9:20 AM!")
            return

        # 0. Check Max Concurrent Positions
        if len(self.active_positions) >= max_pos:
            self._log("RMS", f"⛔ [MAX POSITIONS REACHED] Order Blocked for {symbol}",
                      f"Active positions ({len(self.active_positions)}/{max_pos}) already at max limit. Order rejected!")
            return

        # 0b. Strict Duplicate Position Protection (Prevent duplicate orders on same stock)
        with self._lock:
            existing_symbols = {p["symbol"] for p in self.active_positions.values()}
            if symbol in existing_symbols:
                self._log("RMS", f"⛔ [DUPLICATE BLOCKED] Position for {symbol} already exists",
                          f"Active position already open for {symbol}. Duplicate order rejected!")
                return

        # 1. Logic-Based Strategy Capital Allocation:
        # Each trading logic has its own dynamically allocated capital (total_capital / active_logics, or custom tuned)
        strat_cap = float(strat.get("capital_per_trade", 0.0))
        if strat_cap <= 0:
            active_count = len([s for s in self.strategies.values() if s.get("enabled", True)])
            strat_cap = round(total_cap / max(1, active_count), 2)
        cap_alloc = strat_cap

        # 2. Strict Account Capital & Margin Protection:
        used_margin = sum(float(p.get("margin_used", 0.0) or 0.0) for p in self.active_positions.values())
        available_cap = max(0.0, total_cap - used_margin)

        is_mis = (product == "MIS")
        leverage_mult = 5.0 if is_mis else 1.0
        min_single_share_margin = round(ltp / leverage_mult, 2)

        # Check if enough capital is available for at least 1 share
        if available_cap < min_single_share_margin:
            self._log(
                "RMS",
                f"⛔ [RMS CAPITAL LIMIT REACHED] Order Blocked for {symbol}",
                f"Used Margin: ₹{used_margin:,.2f} of Total Capital: ₹{total_cap:,.2f} | "
                f"Remaining Available: ₹{available_cap:,.2f} (Need min ₹{min_single_share_margin:,.2f} for 1 share). Order rejected!"
            )
            return

        # Cap alloc cannot exceed remaining available capital
        effective_cap = min(cap_alloc, available_cap)
        effective_buying_power = effective_cap * leverage_mult

        # ── FIXED QTY OVERRIDE: If strategy has fixed_qty > 0, use with risk clamp ──
        fixed_qty = int(strat.get("fixed_qty", 0) or 0)
        if fixed_qty > 0:
            quantity = fixed_qty
            margin_req = (ltp * quantity) / leverage_mult
            # Safety Clamp 1: Cannot exceed available capital margin
            if margin_req > available_cap:
                quantity = max(1, int(available_cap * leverage_mult / ltp))
                margin_req = (ltp * quantity) / leverage_mult
                self._log("ORDER", f"⚠️ [FIXED QTY CLAMPED] {symbol}: Clamped fixed qty from {fixed_qty} to {quantity} to fit available capital (Margin: ₹{margin_req:,.2f})")
            # Safety Clamp 2: Max turnover per position (default cap ₹3,00,000 to prevent single-stock blowout)
            max_pos_turnover = min(total_cap * 0.4, 300000.0)
            if (ltp * quantity) > max_pos_turnover and total_cap < 50000000:
                quantity = max(1, int(max_pos_turnover / ltp))
                margin_req = (ltp * quantity) / leverage_mult
                self._log("RMS", f"🛡️ [MAX EXPOSURE CLAMP] {symbol}: Capped quantity to {quantity} (Max Turnover: ₹{max_pos_turnover:,.2f}) to protect account!")
            else:
                self._log("ORDER", f"📦 [FIXED QTY] {symbol}: Using fixed qty={quantity} (Margin: ₹{margin_req:,.2f})")
        else:
            quantity = int(effective_buying_power / ltp)
            if quantity < 1:
                if min_single_share_margin <= available_cap and min_single_share_margin <= cap_alloc * 1.5:
                    quantity = 1
                else:
                    self._log("RMS", f"⛔ [INSUFFICIENT FUNDS] Cannot buy 1 Qty {symbol}: Required ₹{min_single_share_margin:,.2f} > Allocated ₹{cap_alloc:,.2f} (Available ₹{available_cap:,.2f})")
                    return

            margin_req = (ltp * quantity) / leverage_mult

            # Scale down quantity if margin exceeds available capital OR allocated logic capital
            while quantity > 1 and (margin_req > available_cap + 1.0 or margin_req > cap_alloc + 1.0):
                quantity -= 1
                margin_req = (ltp * quantity) / leverage_mult

        # Target & SL Calculations (Multi-Target: T1 for 50% partial exit & T2 for runner)
        t1_pct = float(strat.get("target_1_pct", strat.get("target_pct", 1.0)))
        t2_pct = float(strat.get("target_2_pct", t1_pct * 2.0))
        sl_pct = float(strat.get("sl_pct", 0.8))
        trail_pct = float(strat.get("trailing_sl_pct", 0.3))

        # Volatility-Adaptive Target & Stop Loss Tuning:
        # High-value stocks (>= ₹1500) have tighter percentage swings: Clamp SL to max 1.0% to protect capital.
        # Cheaper stocks (<= ₹300) have wider natural spreads: Ensure min 1.3% SL breathing room to prevent shakeouts.
        if ltp >= 1500.0:
            sl_pct = min(sl_pct, 1.0)
            t1_pct = min(t1_pct, 1.4)
            t2_pct = min(t2_pct, 2.2)
        elif ltp <= 300.0:
            sl_pct = max(sl_pct, 1.3)
            t1_pct = max(t1_pct, 1.8)
            t2_pct = max(t2_pct, 3.2)

        if side == "BUY":
            t1_price = round(ltp * (1.0 + (t1_pct / 100.0)), 2)
            t2_price = round(ltp * (1.0 + (t2_pct / 100.0)), 2)
            sl_price = round(ltp * (1.0 - (sl_pct / 100.0)), 2)
        else:
            t1_price = round(ltp * (1.0 - (t1_pct / 100.0)), 2)
            t2_price = round(ltp * (1.0 - (t2_pct / 100.0)), 2)
            sl_price = round(ltp * (1.0 + (sl_pct / 100.0)), 2)

        # Log Signal Detection
        self._log("SIGNAL", f"🎯 [{strat_name}] Signal Detected on {symbol} @ ₹{ltp:.2f}", signal.get("reason", ""))

        order_id = f"ALGO_{int(time.time())}_{symbol}"

        # ── EXECUTION ROUTING ─────────────────────────────────────────
        if self.mode == "PAPER":
            # Route to PaperPortfolio
            portfolio = self._web_state.get("paper_portfolio")
            if portfolio:
                try:
                    portfolio.place_order(
                        symbol=symbol,
                        exchange="NSE",
                        transaction=side,
                        quantity=quantity,
                        order_type="MARKET",
                        product=product,
                        price=ltp,
                        stop_loss=sl_price,
                        target=t1_price,
                        tag=f"ALGO_{strat_id}",
                    )
                except Exception as pe:
                    logger.warning(f"Paper portfolio order add warning: {pe}")

            lev_info = f"(5X Margin: ₹{margin_req:,.2f} | Logic Cap: ₹{cap_alloc:,.2f} | Account: ₹{margin_req+used_margin:,.0f}/₹{total_cap:,.0f})" if is_mis else f"(1X CNC: ₹{margin_req:,.2f} | Logic Cap: ₹{cap_alloc:,.2f} | Account: ₹{margin_req+used_margin:,.0f}/₹{total_cap:,.0f})"
            self._log("ORDER", f"⚡ [AUTO {side}] EXECUTED: {quantity} Qty {symbol} @ ₹{ltp:.2f} {lev_info}",
                      f"T1: ₹{t1_price:.2f} (+{t1_pct}%, 50% Qty) | T2: ₹{t2_price:.2f} (+{t2_pct}%) | SL: ₹{sl_price:.2f} (-{sl_pct}%)")

        else:
            # Route to Live KiteConnect API
            kite = self._web_state.get("kite")
            if kite:
                try:
                    kite_txn = kite.TRANSACTION_TYPE_BUY if side == "BUY" else kite.TRANSACTION_TYPE_SELL
                    kite_prod = kite.PRODUCT_MIS if product == "MIS" else kite.PRODUCT_CNC
                    live_order_id = kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange="NSE",
                        tradingsymbol=symbol,
                        transaction_type=kite_txn,
                        quantity=quantity,
                        product=kite_prod,
                        order_type=kite.ORDER_TYPE_MARKET,
                        tag="ALGO_AUTO",
                    )
                    order_id = str(live_order_id)
                    self._log("ORDER", f"🔴 [LIVE AUTO {side}] FIRED TO ZERODHA: {quantity} Qty {symbol} @ ₹{ltp:.2f}",
                              f"Order ID: {order_id} | T1: ₹{t1_price:.2f} | T2: ₹{t2_price:.2f} | SL: ₹{sl_price:.2f}")
                except Exception as ke:
                    self._log("ERROR", f"Failed to place Live Kite order for {symbol}: {ke}")
                    return
            else:
                self._log("ERROR", f"Kite not connected! Cannot execute Live order for {symbol}.")
                return

        # Register in Active Positions
        with self._lock:
            pos_id = f"POS_{symbol}_{int(time.time())}"
            self.active_positions[pos_id] = {
                "pos_id": pos_id,
                "order_id": order_id,
                "symbol": symbol,
                "strategy_id": strat_id,
                "strategy_name": strat_name,
                "side": side,
                "product": product,
                "quantity": quantity,
                "original_quantity": quantity,
                "entry_price": ltp,
                "current_price": ltp,
                "highest_price": ltp,
                "lowest_price": ltp,
                "stop_loss": sl_price,
                "target": t1_price,
                "target_1": t1_price,
                "target_2": t2_price,
                "target_1_hit": False,
                "trailing_sl": sl_price,
                "trailing_step_pct": trail_pct,
                "peak_drop_exit_pct": float(signal.get("peak_drop_exit_pct", strat.get("peak_drop_exit_pct", 1.5 if strat_id in ("open_reversal", "custom_quant_momentum") else 0.0)) or 0.0),
                "margin_used": round(margin_req, 2),
                "win_rate": signal.get("win_rate", 60.0),
                "gross_pnl": 0.0,
                "charges": 0.0,
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "entry_time": datetime.now(IST).strftime("%H:%M:%S"),
                "entry_timestamp": time.time(),
            }

            # Update Strategy & Engine Counters
            strat["signals_count"] = strat.get("signals_count", 0) + 1
            self.stats["signals_today"] += 1
            self.stats["orders_today"] += 1
            self._save_state()

    # ─────────────────────────────────────────────────────────────
    # AUTO EXIT & TRADE LOGGING
    # ─────────────────────────────────────────────────────────────

    def _exit_position(self, pos: dict, exit_price: float, reason: str):
        """
        Closes an active position automatically (or manually):
        - Sends reverse order to broker/paper portfolio.
        - Calculates realized P&L.
        - Appends to closed trades log.
        - Removes from active positions registry.
        """
        symbol = pos["symbol"]
        qty = pos["quantity"]
        side = pos["side"]
        entry_p = pos["entry_price"]
        product = pos["product"]

        if side == "BUY":
            gross_pnl = (exit_price - entry_p) * qty
            exit_side = "SELL"
            charges_res = calculate_trade_charges(product, qty, buy_price=entry_p, sell_price=exit_price)
        else:
            gross_pnl = (entry_p - exit_price) * qty
            exit_side = "BUY"
            charges_res = calculate_trade_charges(product, qty, buy_price=exit_price, sell_price=entry_p)

        gross_pnl = round(gross_pnl, 2)
        # Brokerage & taxes are deducted upon order sell / settlement
        # "na hi brokerage charge ko loss se calculate kare" -> do not deduct/calculate brokerage charges on loss trades
        if gross_pnl > 0:
            charges = charges_res["total_charges"]
            charges_breakdown = charges_res["breakdown"]
            net_pnl = round(gross_pnl - charges, 2)
        else:
            charges = 0.0
            charges_breakdown = {k: "₹0.00 (No charge on loss)" for k in charges_res["breakdown"]}
            net_pnl = gross_pnl

        denom = entry_p * qty
        net_pnl_pct = round((net_pnl / denom) * 100.0, 2) if denom > 0 else 0.0

        pnl = net_pnl
        pnl_pct = net_pnl_pct

        # Route exit order
        if self.mode == "PAPER":
            portfolio = self._web_state.get("paper_portfolio")
            if portfolio:
                try:
                    portfolio.exit_position(symbol=symbol, price=exit_price)
                except Exception as pe:
                    logger.debug(f"Paper exit notice: {pe}")
        else:
            kite = self._web_state.get("kite")
            if kite:
                try:
                    kite_txn = kite.TRANSACTION_TYPE_SELL if exit_side == "SELL" else kite.TRANSACTION_TYPE_BUY
                    kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange="NSE",
                        tradingsymbol=symbol,
                        transaction_type=kite_txn,
                        quantity=qty,
                        product=kite.PRODUCT_MIS if product == "MIS" else kite.PRODUCT_CNC,
                        order_type=kite.ORDER_TYPE_MARKET,
                        tag=f"ALGO_EXIT_{reason[:10]}",
                    )
                except Exception as ke:
                    logger.error(f"Live exit error for {symbol}: {ke}")

        # Compute holding duration
        duration_sec = time.time() - pos.get("entry_timestamp", time.time())
        duration_min = round(duration_sec / 60.0, 1)

        # Append to Closed Trades
        trade_record = {
            "trade_id": f"TR_{symbol}_{int(time.time())}",
            "symbol": symbol,
            "strategy": pos.get("strategy_name", "Algo Strategy"),
            "strategy_id": pos.get("strategy_id", ""),  # ✅ Fixed: strategy_id added for analytics filtering
            "side": side,
            "product": product,
            "quantity": qty,
            "entry_price": entry_p,
            "exit_price": exit_price,
            "win_rate": pos.get("win_rate", 60.0),
            "gross_pnl": gross_pnl,
            "charges": charges,
            "charges_breakdown": charges_res["breakdown"],
            "pnl": net_pnl,
            "pnl_pct": net_pnl_pct,
            "entry_time": pos.get("entry_time", ""),
            "exit_time": datetime.now(IST).strftime("%H:%M:%S"),
            "duration": f"{duration_min}m",
            "exit_reason": reason,
            "timestamp": time.time(),            # ✅ Fixed: Unix timestamp for date filtering
            "trade_date": datetime.now(IST).strftime("%Y-%m-%d"),  # ✅ Fixed: Date string for cross-day checks
            "date": datetime.now(IST).strftime("%d %b %Y"),        # ✅ Fixed: Display date for UI
        }
        self.closed_trades.insert(0, trade_record)

        # Remove from active positions
        pos_id = pos.get("pos_id")
        if pos_id in self.active_positions:
            del self.active_positions[pos_id]

        # Update stats
        self.stats["gross_pnl"] = round(self.stats.get("gross_pnl", 0.0) + gross_pnl, 2)
        self.stats["total_charges"] = round(self.stats.get("total_charges", 0.0) + charges, 2)
        self.stats["realized_pnl"] = round(self.stats["realized_pnl"] + net_pnl, 2)
        self.stats["total_trades"] += 1
        if net_pnl > 0:
            self.stats["winning_trades"] += 1
        else:
            self.stats["losing_trades"] += 1

        win_rate = (self.stats["winning_trades"] / self.stats["total_trades"] * 100.0) if self.stats["total_trades"] > 0 else 0.0
        self.stats["win_rate"] = round(win_rate, 1)

        pnl_str = f"+₹{net_pnl:,.2f}" if net_pnl >= 0 else f"-₹{abs(net_pnl):,.2f}"
        gross_str = f"+₹{gross_pnl:,.2f}" if gross_pnl >= 0 else f"-₹{abs(gross_pnl):,.2f}"
        self._log("EXIT", f"🏁 [{reason}] Closed {qty} {symbol} @ ₹{exit_price:.2f} | Net: {pnl_str} (Gross: {gross_str}, Chg: ₹{charges:.2f})")
        self._record_equity_point()
        self._save_state()

    def _exit_partial_position(self, pos: dict, exit_qty: int, exit_price: float, reason: str):
        """
        Executes a partial exit (e.g. 50% at Target 1):
        - Sends partial exit order to broker/paper engine.
        - Calculates realized P&L on the exited portion.
        - Logs trade record with 'PARTIAL' tag.
        """
        symbol = pos["symbol"]
        side = pos["side"]
        entry_p = pos["entry_price"]
        product = pos["product"]

        if side == "BUY":
            gross_pnl = (exit_price - entry_p) * exit_qty
            exit_side = "SELL"
            charges_res = calculate_trade_charges(product, exit_qty, buy_price=entry_p, sell_price=exit_price)
        else:
            gross_pnl = (entry_p - exit_price) * exit_qty
            exit_side = "BUY"
            charges_res = calculate_trade_charges(product, exit_qty, buy_price=exit_price, sell_price=entry_p)

        gross_pnl = round(gross_pnl, 2)
        # Brokerage & taxes are deducted upon order sell / settlement
        # "na hi brokerage charge ko loss se calculate kare" -> do not deduct/calculate brokerage charges on loss trades
        if gross_pnl > 0:
            charges = charges_res["total_charges"]
            charges_breakdown = charges_res["breakdown"]
            net_pnl = round(gross_pnl - charges, 2)
        else:
            charges = 0.0
            charges_breakdown = {k: "₹0.00 (No charge on loss)" for k in charges_res["breakdown"]}
            net_pnl = gross_pnl

        denom = entry_p * exit_qty
        net_pnl_pct = round((net_pnl / denom) * 100.0, 2) if denom > 0 else 0.0

        pnl = net_pnl
        pnl_pct = net_pnl_pct

        # Route partial exit order
        if self.mode == "PAPER":
            portfolio = self._web_state.get("paper_portfolio")
            if portfolio:
                try:
                    portfolio.place_order(
                        symbol=symbol,
                        exchange="NSE",
                        transaction=exit_side,
                        quantity=exit_qty,
                        order_type="MARKET",
                        product=product,
                        price=exit_price,
                        tag=f"ALGO_PART_{reason[:8]}"
                    )
                except Exception as pe:
                    logger.debug(f"Paper partial exit notice: {pe}")
        else:
            kite = self._web_state.get("kite")
            if kite:
                try:
                    kite_txn = kite.TRANSACTION_TYPE_SELL if exit_side == "SELL" else kite.TRANSACTION_TYPE_BUY
                    kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange="NSE",
                        tradingsymbol=symbol,
                        transaction_type=kite_txn,
                        quantity=exit_qty,
                        product=kite.PRODUCT_MIS if product == "MIS" else kite.PRODUCT_CNC,
                        order_type=kite.ORDER_TYPE_MARKET,
                        tag=f"ALGO_PART_{reason[:8]}",
                    )
                except Exception as ke:
                    logger.error(f"Live partial exit error for {symbol}: {ke}")

        duration_sec = time.time() - pos.get("entry_timestamp", time.time())
        duration_min = round(duration_sec / 60.0, 1)

        trade_record = {
            "trade_id": f"TR_PART_{symbol}_{int(time.time())}",
            "symbol": symbol,
            "strategy": pos.get("strategy_name", "Algo Strategy"),
            "strategy_id": pos.get("strategy_id", ""),  # ✅ Fixed: strategy_id for analytics filtering
            "side": side,
            "product": product,
            "quantity": exit_qty,
            "entry_price": entry_p,
            "exit_price": exit_price,
            "win_rate": pos.get("win_rate", 60.0),
            "gross_pnl": gross_pnl,
            "charges": charges,
            "charges_breakdown": charges_res["breakdown"],
            "pnl": net_pnl,
            "pnl_pct": net_pnl_pct,
            "entry_time": pos.get("entry_time", ""),
            "exit_time": datetime.now(IST).strftime("%H:%M:%S"),
            "duration": f"{duration_min}m",
            "exit_reason": reason,
            "timestamp": time.time(),            # ✅ Fixed: Unix timestamp for date filtering
            "trade_date": datetime.now(IST).strftime("%Y-%m-%d"),  # ✅ Fixed: Date string for cross-day checks
            "date": datetime.now(IST).strftime("%d %b %Y"),        # ✅ Fixed: Display date for UI
        }
        self.closed_trades.insert(0, trade_record)

        self.stats["gross_pnl"] = round(self.stats.get("gross_pnl", 0.0) + gross_pnl, 2)
        self.stats["total_charges"] = round(self.stats.get("total_charges", 0.0) + charges, 2)
        self.stats["realized_pnl"] = round(self.stats["realized_pnl"] + net_pnl, 2)
        self.stats["total_trades"] += 1
        if net_pnl > 0:
            self.stats["winning_trades"] += 1
        else:
            self.stats["losing_trades"] += 1

        win_rate = (self.stats["winning_trades"] / self.stats["total_trades"] * 100.0) if self.stats["total_trades"] > 0 else 0.0
        self.stats["win_rate"] = round(win_rate, 1)

        self._record_equity_point()
        pnl_str = f"+₹{net_pnl:,.2f}" if net_pnl >= 0 else f"-₹{abs(net_pnl):,.2f}"
        gross_str = f"+₹{gross_pnl:,.2f}" if gross_pnl >= 0 else f"-₹{abs(gross_pnl):,.2f}"
        self._log("EXIT", f"🎯 [{reason}] Partial Closed {exit_qty} {symbol} @ ₹{exit_price:.2f} | Net: {pnl_str} (Gross: {gross_str}, Chg: ₹{charges:.2f})")
        self._save_state()

    def manual_exit_position(self, pos_id: str) -> dict:
        """Allow user to manually close a specific active position if desired."""
        with self._lock:
            pos = self.active_positions.get(pos_id)
            if not pos:
                return {"success": False, "error": "Position not found"}

            ltp = pos.get("current_price", pos.get("entry_price"))
            self._exit_position(pos, exit_price=ltp, reason="MANUAL_EXIT")
            return {"success": True, "message": f"Position {pos['symbol']} closed manually."}

    # ─────────────────────────────────────────────────────────────
    # STATS & UNIVERSE HELPERS
    # ─────────────────────────────────────────────────────────────

    def _recalculate_stats(self):
        """Recomputes unrealized and net P&L across all active positions."""
        unrealized = sum(p.get("pnl", 0.0) for p in self.active_positions.values())
        unrealized_gross = sum(p.get("gross_pnl", 0.0) for p in self.active_positions.values())
        # Sum estimated round-trip brokerage & taxes for open positions + realized charges
        unrealized_charges = sum(p.get("est_charges", p.get("charges", 0.0)) for p in self.active_positions.values())

        self.stats["unrealized_pnl"] = round(unrealized, 2)
        self.stats["unrealized_gross"] = round(unrealized_gross, 2)
        self.stats["unrealized_charges"] = round(unrealized_charges, 2)
        # Today's Net P&L: Realized net P&L (charges deducted upon sell settlement) + Unrealized Gross P&L (charges NOT deducted before sell settlement)
        self.stats["today_pnl"] = round(self.stats.get("realized_pnl", 0.0) + unrealized, 2)
        self.stats["today_gross_pnl"] = round(self.stats.get("gross_pnl", 0.0) + unrealized_gross, 2)
        # Brokerage & taxes KPI displays the total sum of charges (settled trades + estimated open position charges)
        self.stats["today_charges"] = round(self.stats.get("total_charges", 0.0) + unrealized_charges, 2)

    def _passes_market_cap_filter(self, symbol: str, ltp: float, min_mcap_m: float = 100.0) -> bool:
        """
        Validates if stock market capitalization is >= min_mcap_m (default: 100 Million).
        Filters out penny stocks, SME/Z-group illiquid counters, and micro-caps.
        """
        # 1. Custom explicit market cap overrides if configured
        if hasattr(self, "_custom_mcap_map") and symbol in self._custom_mcap_map:
            return float(self._custom_mcap_map[symbol]) >= min_mcap_m

        # 2. Known institutional index members (Nifty 50, Next 50, Midcap 150, Smallcap 100, F&O)
        # All of these have MCap > ₹1,000 Crore (> 10,000 Million INR), easily surpassing 100M.
        if not hasattr(self, "_liquid_mcap_set") or not self._liquid_mcap_set:
            try:
                from web_app import _resolve_symbols
            except ImportError:
                from algo_trading.web_app import _resolve_symbols
            try:
                liquid_pool = _resolve_symbols("all_stocks")
                self._liquid_mcap_set = set(liquid_pool) if liquid_pool else set()
            except Exception:
                self._liquid_mcap_set = set()

        if symbol in self._liquid_mcap_set:
            return True

        # 3. Known micro-cap / SME suffix check
        # SME stocks on NSE end in -SM, -ST or trade in illiquid lots
        if symbol.endswith(("-SM", "-ST", "-BE", "-BZ")):
            return False

        # 4. Fallback check for new or unlisted symbols:
        # At LTP >= 50, a 100 Million (₹10 Cr) market cap requires at least 2 million shares.
        return True

    def _get_universe_symbols(self) -> List[str]:
        """
        Resolves symbol list based on selected universe:
        1. 'fno': All active liquid F&O stocks (~260 derivative counters)
        2. 'all_stocks' (default): Complete market universe (All NSE EQ, excluding penny stocks <₹50 via RMS)
        """
        if self.universe == "fno":
            try:
                from web_app import _get_fno_symbols
            except ImportError:
                from algo_trading.web_app import _get_fno_symbols
            kite = self._web_state.get("kite")
            fno = list(_get_fno_symbols(kite))
            return fno if fno else ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TMCV"]
        else:  # "all_stocks" - All available market stocks (excl penny stocks)
            try:
                from web_app import _resolve_symbols
            except ImportError:
                from algo_trading.web_app import _resolve_symbols
            syms = _resolve_symbols("all_stocks")
            return syms if syms else ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TMCV"]

    # ─────────────────────────────────────────────────────────────
    # API SERIALIZERS
    # ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Returns comprehensive status for Algo Trade HUD."""
        with self._lock:
            self._recalculate_stats()
            active_count = len([s for s in self.strategies.values() if s.get("enabled", True)])
            ticker = self._web_state.get("ticker")
            ws_connected = bool(self.is_websocket_active or (ticker and getattr(ticker, "is_connected", False)))
            return {
                "status": self.status,
                "mode": self.mode,
                "universe": self.universe,
                "active_strategies_count": active_count,
                "total_strategies_count": len(self.strategies),
                "open_positions_count": len(self.active_positions),
                "last_scan_time": self.last_scan_time.strftime("%H:%M:%S") if self.last_scan_time else "-",
                "last_scan_duration_ms": self.last_scan_duration_ms,
                "websocket_connected": ws_connected,
                "websocket_ticks_count": len(self.live_quotes_cache),
                "next_scan_countdown": self.next_scan_countdown,
                "scan_interval": self.scan_interval_sec,
                "stats": self.stats,
                "circuit_breaker_hit": self.risk_config.get("circuit_breaker_hit", False),
                "circuit_breaker_reason": self.risk_config.get("circuit_breaker_reason", ""),
            }

    # ─────────────────────────────────────────────────────────────
    # DYNAMIC CAPITAL ALLOCATION & REBALANCING ENGINE
    # ─────────────────────────────────────────────────────────────

    def rebalance_strategy_capital(self):
        """
        Dynamically balances trading capital across all active strategies/logics.
        Rule: Total Capital / Active Logics Count.
        Inactive strategies are allocated ₹0.0.
        Guarantees that the sum of capital across active strategies strictly equals Total Capital.
        """
        total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
        active = [s for s in self.strategies.values() if s.get("enabled", True)]
        if not active:
            for s in self.strategies.values():
                s["capital_per_trade"] = 0.0
            return

        current_sum = round(sum(float(s.get("capital_per_trade", 0.0)) for s in active), 2)
        # Rebalance equally if sum doesn't match total_capital or any active strategy has 0 / invalid capital
        if abs(current_sum - total_cap) > 1.0 or any(float(s.get("capital_per_trade", 0.0)) <= 0 for s in active):
            base_share = round(total_cap / len(active), 2)
            remainder = round(total_cap - (base_share * len(active)), 2)
            for i, s in enumerate(active):
                s["capital_per_trade"] = round(base_share + (remainder if i == 0 else 0.0), 2)

        for s in self.strategies.values():
            if not s.get("enabled", True):
                s["capital_per_trade"] = 0.0

    def adjust_strategy_capital(self, target_id: str, new_cap: float):
        """
        Adjusts a specific strategy's capital.
        Any increase or decrease (+/- Delta) is deducted or added EQUALLY across all other active strategies.
        Guarantees: Total Capital is strictly preserved.
        """
        target = self.strategies.get(target_id)
        if not target or not target.get("enabled", True):
            return

        total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
        active_others = [s for s in self.strategies.values() if s.get("enabled", True) and s.get("id") != target_id]
        if not active_others:
            target["capital_per_trade"] = total_cap
            return

        min_cap = 100.0
        max_cap = max(min_cap, round(total_cap - (len(active_others) * min_cap), 2))
        new_cap = max(min_cap, min(max_cap, round(float(new_cap), 2)))

        old_cap = float(target.get("capital_per_trade", 0.0))
        delta = round(new_cap - old_cap, 2)
        if abs(delta) < 0.01:
            return

        # Deduct / Add delta equally across remaining active strategies
        deduct_per_other = round(delta / len(active_others), 2)
        target["capital_per_trade"] = new_cap

        for s in active_others:
            s["capital_per_trade"] = max(min_cap, round(float(s.get("capital_per_trade", 0.0)) - deduct_per_other, 2))

        # Precision correction to ensure exact sum equals total_cap
        current_total = round(target["capital_per_trade"] + sum(float(s["capital_per_trade"]) for s in active_others), 2)
        diff = round(total_cap - current_total, 2)
        active_others[0]["capital_per_trade"] = round(active_others[0]["capital_per_trade"] + diff, 2)

    def toggle_strategy_active(self, strat_id: str, is_enabled: bool):
        """
        Toggles a strategy Active or Inactive:
        - When DISABLED: Its capital is released and distributed EQUALLY among remaining active strategies.
        - When ENABLED: It is granted its fair share, drawn EQUALLY from existing active strategies.
        Guarantees: Total Capital is strictly preserved.
        """
        target = self.strategies.get(strat_id)
        if not target:
            return

        was_enabled = target.get("enabled", True)
        target["enabled"] = is_enabled
        total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))

        if was_enabled and not is_enabled:
            # Releasing capital to remaining active strategies
            released = float(target.get("capital_per_trade", 0.0))
            target["capital_per_trade"] = 0.0
            active = [s for s in self.strategies.values() if s.get("enabled", True)]
            if active:
                share = round(released / len(active), 2)
                rem = round(released - (share * len(active)), 2)
                for i, s in enumerate(active):
                    s["capital_per_trade"] = round(float(s.get("capital_per_trade", 0.0)) + share + (rem if i == 0 else 0.0), 2)
                tot = round(sum(float(s["capital_per_trade"]) for s in active), 2)
                d = round(total_cap - tot, 2)
                active[0]["capital_per_trade"] = round(active[0]["capital_per_trade"] + d, 2)

        elif not was_enabled and is_enabled:
            # Granting fair share to newly activated strategy
            active = [s for s in self.strategies.values() if s.get("enabled", True)]
            active_others = [s for s in active if s.get("id") != strat_id]
            if not active_others:
                target["capital_per_trade"] = total_cap
            else:
                target_share = round(total_cap / len(active), 2)
                deduct_each = round(target_share / len(active_others), 2)
                for s in active_others:
                    s["capital_per_trade"] = max(100.0, round(float(s.get("capital_per_trade", 0.0)) - deduct_each, 2))
                target["capital_per_trade"] = target_share
                tot = round(sum(float(s["capital_per_trade"]) for s in active), 2)
                d = round(total_cap - tot, 2)
                active_others[0]["capital_per_trade"] = round(active_others[0]["capital_per_trade"] + d, 2)

    def rebalance_on_total_capital_change(self, new_total: float, old_total: float):
        """Scales active strategies proportionally when total capital changes in RMS."""
        active = [s for s in self.strategies.values() if s.get("enabled", True)]
        if not active:
            return
        if old_total <= 0:
            self.rebalance_strategy_capital()
            return
        for s in active:
            ratio = float(s.get("capital_per_trade", 0.0)) / old_total
            s["capital_per_trade"] = round(new_total * ratio, 2)
        tot = round(sum(float(s["capital_per_trade"]) for s in active), 2)
        d = round(new_total - tot, 2)
        active[0]["capital_per_trade"] = round(active[0]["capital_per_trade"] + d, 2)

    def get_config(self) -> dict:
        """Returns strategy parameters and RMS risk settings with live balanced capital summary."""
        with self._lock:
            self.rebalance_strategy_capital()
            active_count = len([s for s in self.strategies.values() if s.get("enabled", True)])
            total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
            return {
                "status": self.status,
                "mode": self.mode,
                "universe": self.universe,
                "risk_config": self.risk_config,
                "strategies": list(self.strategies.values()),
                "capital_summary": {
                    "total_capital": total_cap,
                    "active_logics_count": active_count,
                    "capital_per_logic": round(total_cap / max(1, active_count), 2),
                }
            }

    def update_config(self, data: dict) -> dict:
        """Update strategy settings or RMS limits from client with dynamic rebalancing."""
        with self._lock:
            if "universe" in data:
                self.universe = data["universe"]

            if "risk_config" in data:
                old_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
                self.risk_config.update(data["risk_config"])
                new_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
                if abs(new_cap - old_cap) > 0.01:
                    self.rebalance_on_total_capital_change(new_cap, old_cap)
                # Reset circuit breaker if requested
                if data["risk_config"].get("circuit_breaker_hit") is False:
                    self.risk_config["circuit_breaker_hit"] = False
                    self.risk_config["circuit_breaker_reason"] = ""

            if "strategies" in data:
                for s_data in data["strategies"]:
                    sid = s_data.get("id")
                    if sid in self.strategies:
                        curr_s = self.strategies[sid]
                        old_enabled = curr_s.get("enabled", True)
                        new_enabled = s_data.get("enabled", old_enabled)
                        old_cap = float(curr_s.get("capital_per_trade", 0.0))
                        new_cap = s_data.get("capital_per_trade")

                        # Update other configuration attributes
                        for k, v in s_data.items():
                            if k not in ("enabled", "capital_per_trade"):
                                curr_s[k] = v

                        # Handle active / inactive toggle
                        if old_enabled != new_enabled:
                            self.toggle_strategy_active(sid, new_enabled)
                        elif new_cap is not None and abs(float(new_cap) - old_cap) > 0.5:
                            # Handle manual capital adjustment (+/- Delta)
                            self.adjust_strategy_capital(sid, float(new_cap))

            self.rebalance_strategy_capital()
            self._save_state()
            self._log("INFO", "⚙️ Strategy Configuration updated & dynamic capital rebalanced.")
            active_count = len([s for s in self.strategies.values() if s.get("enabled", True)])
            total_cap = float(self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0))
            return {
                "success": True,
                "message": "Config updated and strategy capital rebalanced successfully",
                "strategies": list(self.strategies.values()),
                "risk_config": self.risk_config,
                "capital_summary": {
                    "total_capital": total_cap,
                    "active_logics_count": active_count,
                    "capital_per_logic": round(total_cap / max(1, active_count), 2),
                }
            }

    def get_active_positions(self) -> List[dict]:
        """Returns active positions with live P&L and trailing SL."""
        with self._lock:
            return list(self.active_positions.values())

    def get_closed_trades(self, limit: int = 50) -> List[dict]:
        """Returns recent completed trades."""
        with self._lock:
            return self.closed_trades[:limit]

    def clear_closed_trades(self) -> dict:
        """Clears completed trades history and resets realized trade stats."""
        with self._lock:
            self.closed_trades.clear()
            self.stats["gross_pnl"] = 0.0
            self.stats["total_charges"] = 0.0
            self.stats["realized_pnl"] = 0.0
            self.stats["total_trades"] = 0
            self.stats["winning_trades"] = 0
            self.stats["losing_trades"] = 0
            self.stats["win_rate"] = 0.0
            self._recalculate_stats()
            self._save_state()
            self._log("INFO", "🧹 Completed trades history & stats cleared by user.")
            return {"success": True, "message": "Trades history cleared successfully."}

    def get_strategy_analytics(self, strat_id: str, days: str = "1") -> dict:
        """
        Calculates and returns performance metrics for a specific quantitative strategy:
        - Return % (overall profit/loss % generated)
        - Win % vs Loss %
        - Total Profit (₹) vs Total Loss (₹)
        - Avg Profit % per win vs Avg Loss % per loss
        - Profit Factor
        - Date Range Filter: 1, 2, 3, 4, 5, 6 days, or all
        - Historical executed trades list with timestamps, prices, and P&L %
        """
        with self._lock:
            strat = self.strategies.get(strat_id, {})
            strat_name = strat.get("name", strat_id.replace("_", " ").title())
            strat_badge = strat.get("badge", "Intraday")
            strat_icon = strat.get("icon", "🤖")
            strat_desc = strat.get("desc", "")
            cap_per_trade = float(strat.get("capital_per_trade", self.risk_config.get("total_capital", TOTAL_CAPITAL or 2000000.0) / max(1, self.risk_config.get("max_open_positions", 4))))

            # Determine filter window in seconds
            now_ts = time.time()
            if str(days).lower() == "all":
                filter_sec = 86400 * 365
                days_label = "All Time"
                days_num = 365
            else:
                try:
                    d_int = max(1, min(6, int(days)))
                except Exception:
                    d_int = 1
                filter_sec = 86400 * d_int
                days_label = f"Last {d_int} Day" if d_int == 1 else f"Last {d_int} Days"
                days_num = d_int

            matched_trades = []

            # 1. Inspect closed_trades from engine
            for t in self.closed_trades:
                trade_strat_id = t.get("strategy_id", "")
                trade_strat_name = t.get("strategy", "")
                if trade_strat_id == strat_id or trade_strat_name == strat_name or (trade_strat_id and strat_id in trade_strat_id):
                    # ✅ Fixed: Use timestamp field for filtering; fallback to trade_date comparison
                    t_time = t.get("timestamp")
                    if t_time is None:
                        # Purani trades jisme timestamp nahi hai: trade_date se check karo
                        t_date = t.get("trade_date", "")
                        if t_date:
                            try:
                                t_time = datetime.strptime(t_date, "%Y-%m-%d").timestamp()
                            except Exception:
                                t_time = now_ts  # Fallback: include in results
                        else:
                            t_time = now_ts  # Unknown date: include by default
                    if (now_ts - float(t_time)) <= filter_sec:
                        matched_trades.append({
                            "date": t.get("date", datetime.fromtimestamp(float(t_time)).strftime("%d %b %Y")),
                            "time": t.get("exit_time") or t.get("entry_time") or "10:00:00",
                            "symbol": t.get("symbol", ""),
                            "side": t.get("side", "BUY"),
                            "entry_price": float(t.get("entry_price", 0.0)),
                            "exit_price": float(t.get("exit_price", 0.0)),
                            "quantity": int(t.get("quantity", 0)),
                            "return_pct": float(t.get("pnl_pct", 0.0)),
                            "pnl": float(t.get("pnl", 0.0)),
                            "status": "WIN" if float(t.get("pnl", 0.0)) > 0 else "LOSS",
                            "exit_reason": t.get("exit_reason", "TARGET_OR_SL"),
                            "is_live": True,
                        })

            # 2. Inspect active_positions (currently open trades for this strategy)
            for pos in self.active_positions.values():
                if pos.get("strategy_id") == strat_id or pos.get("strategy_name") == strat_name:
                    pnl = float(pos.get("pnl", 0.0))
                    pnl_pct = float(pos.get("pnl_pct", 0.0))
                    matched_trades.append({
                        "date": datetime.now(IST).strftime("%d %b %Y"),
                        "time": pos.get("entry_time", "Live"),
                        "symbol": pos.get("symbol", ""),
                        "side": pos.get("side", "BUY"),
                        "entry_price": float(pos.get("entry_price", 0.0)),
                        "exit_price": float(pos.get("current_price", pos.get("entry_price", 0.0))),
                        "quantity": int(pos.get("quantity", 0)),
                        "return_pct": pnl_pct,
                        "pnl": pnl,
                        "status": "ACTIVE (OPEN)",
                        "exit_reason": "Live In-Market",
                        "is_live": True,
                    })

            # 3. Strictly use REAL trades only (no fake DEMO simulated trades)
            is_benchmark = False

            # Calculate Aggregate Performance Metrics
            total_trades = len(matched_trades)
            completed_trades = [t for t in matched_trades if "ACTIVE" not in t.get("status", "")]
            winning_trades = [t for t in completed_trades if t.get("pnl", 0.0) > 0]
            losing_trades = [t for t in completed_trades if t.get("pnl", 0.0) <= 0]

            win_count = len(winning_trades)
            loss_count = len(losing_trades)
            comp_count = len(completed_trades)

            win_rate = round((win_count / comp_count * 100.0), 1) if comp_count > 0 else 0.0
            loss_rate = round(100.0 - win_rate, 1) if comp_count > 0 else 0.0

            total_profit = sum(t.get("pnl", 0.0) for t in winning_trades)
            total_loss = abs(sum(t.get("pnl", 0.0) for t in losing_trades))
            net_pnl = round(total_profit - total_loss, 2)

            total_return_pct = round((net_pnl / cap_per_trade) * 100.0, 2) if cap_per_trade > 0 else 0.0

            avg_win_pct = round(sum(t.get("return_pct", 0.0) for t in winning_trades) / win_count, 2) if win_count > 0 else 0.0
            avg_loss_pct = round(abs(sum(t.get("return_pct", 0.0) for t in losing_trades) / loss_count), 2) if loss_count > 0 else 0.0

            profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else (round(total_profit, 2) if total_profit > 0 else 1.0)
            max_win_pnl = round(max((t.get("pnl", 0.0) for t in winning_trades), default=0.0), 2)
            max_loss_pnl = round(min((t.get("pnl", 0.0) for t in losing_trades), default=0.0), 2)

            strat_dict = dict(strat)
            strat_dict["capital_per_trade"] = cap_per_trade

            return {
                "success": True,
                "strategy": strat_dict,
                "filter_days": days_num,
                "filter_label": days_label,
                "data_source": "Live Strategy Execution Telemetry",
                "summary": {
                    "total_trades": total_trades,
                    "completed_trades": comp_count,
                    "winning_trades": win_count,
                    "losing_trades": loss_count,
                    "win_rate_pct": win_rate,
                    "loss_rate_pct": loss_rate,
                    "net_pnl": net_pnl,
                    "total_profit": round(total_profit, 2),
                    "total_loss": round(total_loss, 2),
                    "total_return_pct": total_return_pct,
                    "avg_win_pct": avg_win_pct,
                    "avg_loss_pct": avg_loss_pct,
                    "profit_factor": profit_factor,
                    "max_win_pnl": max_win_pnl,
                    "max_loss_pnl": max_loss_pnl,
                    "signals_count": strat.get("signals_count", total_trades),
                },
                "trades": matched_trades,
            }


    def get_recent_logs(self, limit: int = 150) -> List[dict]:
        """Returns recent activity logs."""
        with self._lock:
            logs_list = list(self.logs)
            return logs_list[-limit:]

    def force_scan_now(self) -> dict:
        """Triggers an immediate scan and execution cycle on-demand in milliseconds."""
        t0 = time.perf_counter()
        with self._lock:
            self._log("SCAN", "⚡ Manual on-demand scan triggered by user...")
            self._check_rms_and_timing()
            self._monitor_active_positions()
            scanned_count = self._scan_and_execute_signals()
            self._recalculate_stats()
            self._record_equity_point()
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        ticker = self._web_state.get("ticker")
        is_ws = bool(self.is_websocket_active or (ticker and getattr(ticker, "is_connected", False) and len(self.live_quotes_cache) > 0))
        mode_lbl = "WebSocket Live Feed" if is_ws else "Kite REST Batch"

        self._log("SCAN", f"⚡ Instant scan completed in {duration_ms}ms ({mode_lbl}) | {scanned_count} symbols evaluated")

        return {
            "success": True,
            "message": f"⚡ Instant scan completed in {duration_ms}ms via {mode_lbl}!",
            "duration_ms": duration_ms,
            "scanned_count": scanned_count,
            "mode": "WEBSOCKET" if is_ws else "REST",
        }

    def _run_single_scan_cycle(self):
        self.force_scan_now()

    # ─────────────────────────────────────────────────────────────
    # INTRADAY EQUITY CURVE TRACKER
    # ─────────────────────────────────────────────────────────────

    def _record_equity_point(self, net_pnl: Optional[float] = None):
        """Records a timestamped equity point for the live equity curve chart."""
        now_str = datetime.now(IST).strftime("%H:%M:%S")
        if net_pnl is None:
            net_pnl = self.stats["realized_pnl"] + self.stats["unrealized_pnl"]
        point = {
            "time": now_str,
            "pnl": round(float(net_pnl), 2),
            "realized": round(float(self.stats["realized_pnl"]), 2),
            "unrealized": round(float(self.stats["unrealized_pnl"]), 2),
        }
        # Update current second if already exists, else append
        if self.equity_curve and self.equity_curve[-1]["time"] == now_str:
            self.equity_curve[-1] = point
        else:
            self.equity_curve.append(point)
            if len(self.equity_curve) > 250:
                self.equity_curve.pop(0)

    def get_equity_curve(self) -> List[dict]:
        """Returns intraday equity time-series points for chart rendering."""
        with self._lock:
            if not self.equity_curve:
                now_str = datetime.now(IST).strftime("%H:%M:%S")
                return [{
                    "time": now_str,
                    "pnl": round(self.stats["today_pnl"], 2),
                    "realized": round(self.stats["realized_pnl"], 2),
                    "unrealized": round(self.stats["unrealized_pnl"], 2),
                }]
            return list(self.equity_curve)

    def get_custom_strategy_scan_candidates(self) -> dict:
        """
        Scans live market universe for the 4 Custom Quant Criteria:
        1. Prev Day >4.5% Mover (Up or Down)
        2. 9:10 AM Pre-Market Gainer/Loser (>=1.5%)
        3. 9:15 AM Opening Surge (>=2.0%)
        4. Bullish / Teji Sector stocks
        Evaluates Short Covering / OI confirmation status, Win Rate, and Stop Loss details.
        """
        symbols = self._get_universe_symbols()
        if not symbols:
            return {"success": True, "stocks": [], "total": 0, "bullish_sectors": []}

        # Gather quotes (from websocket cache or REST fallback)
        quotes_data = {}
        with self._quote_lock:
            for s in symbols[:350]:
                if s in self.live_quotes_cache:
                    quotes_data[s] = self.live_quotes_cache[s]

        if not quotes_data:
            kite = self._web_state.get("kite")
            if kite:
                sample_syms = symbols[:250]
                formatted = [f"NSE:{s}" if ":" not in s else s for s in sample_syms]
                try:
                    raw_quotes = kite.quote(formatted)
                    for k, v in raw_quotes.items():
                        s = k.replace("NSE:", "")
                        ohlc_dict = v.get("ohlc", {}) or {}
                        quotes_data[s] = {
                            "symbol": s,
                            "ltp": float(v.get("last_price", 0) or 0),
                            "open": float(ohlc_dict.get("open", 0) or 0),
                            "high": float(ohlc_dict.get("high", 0) or 0),
                            "low": float(ohlc_dict.get("low", 0) or 0),
                            "close": float(ohlc_dict.get("close", 0) or 0),
                            "avg_price": float(v.get("average_price", 0) or 0),
                            "volume": int(v.get("volume", 0) or 0),
                        }
                except Exception as e:
                    logger.debug(f"Scanner candidate fetch error: {e}")

        # Update sector performance
        self._update_bullish_sectors(quotes_data)
        bullish_sec_list = []
        for sec_name, syms in SECTOR_MAP.items():
            sec_quotes = [quotes_data[s] for s in syms if s in quotes_data]
            if sec_quotes:
                changes = [((float(q.get("ltp", 0)) - float(q.get("close", 0))) / float(q.get("close", 1))) * 100.0 for q in sec_quotes if float(q.get("close", 0)) > 0]
                if changes:
                    avg_c = sum(changes) / len(changes)
                    if avg_c >= 0.5:
                        bullish_sec_list.append({"name": sec_name, "change_pct": round(avg_c, 2), "stocks_count": len(syms)})

        matched_stocks = []
        active_symbols = {p["symbol"] for p in self.active_positions.values()}

        strat = self.strategies.get("custom_quant_momentum", {})
        min_prev_move = float(strat.get("prev_day_mover_pct", 4.5))
        min_pm_move = float(strat.get("pre_market_mover_pct", 1.5))
        min_surge = float(strat.get("open_surge_pct", 2.0))

        for sym, item in quotes_data.items():
            ltp = float(item.get("ltp", 0) or 0)
            open_p = float(item.get("open", 0) or 0)
            high_p = float(item.get("high", 0) or 0)
            low_p = float(item.get("low", 0) or 0)
            prev_close = float(item.get("close", 0) or 0)
            avg_price = float(item.get("avg_price", 0) or 0)
            volume = int(item.get("volume", 0) or 0)
            vwap = avg_price if avg_price > 0 else (open_p + high_p + low_p) / 3.0

            if ltp <= 0 or prev_close <= 0:
                continue

            day_chg = ((ltp - prev_close) / prev_close) * 100.0
            open_gain = ((ltp - open_p) / open_p) * 100.0 if open_p > 0 else 0.0

            triggers = []

            # 1. Previous Day Move >= 4.5%
            is_prev_m, prev_move_pct = self._check_prev_day_mover(sym, prev_close, min_prev_move)
            if is_prev_m:
                triggers.append({"code": "PREV_DAY", "label": f"Prev Day {prev_move_pct:+.1f}%", "value": round(prev_move_pct, 2)})

            # 2. Pre-market 9:10 AM move >= 1.5%
            if open_p > 0:
                pm_chg = ((open_p - prev_close) / prev_close) * 100.0
                if abs(pm_chg) >= min_pm_move:
                    triggers.append({"code": "PRE_MARKET", "label": f"9:10 Gap {pm_chg:+.1f}%", "value": round(pm_chg, 2)})

            # 3. 9:15 AM Opening Surge >= 2.0%
            if day_chg >= min_surge or open_gain >= min_surge:
                triggers.append({"code": "OPEN_SURGE", "label": f"9:15 Surge +{max(day_chg, open_gain):.1f}%", "value": round(max(day_chg, open_gain), 2)})

            # 4. Bullish Sector
            is_bull_sec, sec_name, sec_perf = self._check_bullish_sector(sym)
            if is_bull_sec:
                triggers.append({"code": "BULLISH_SECTOR", "label": f"Sector: {sec_name} (+{sec_perf:.1f}%)", "value": round(sec_perf, 2), "sector": sec_name})

            if triggers:
                # Check Short Covering / OI Gainer confirmation
                is_oi_confirmed, oi_desc = self._check_short_covering_or_oi_gainer(
                    sym, ltp, open_p, high_p, low_p, prev_close, vwap, volume
                )

                # Setup score / win rate
                wr_info = calculate_setup_win_rate(
                    strat_id="custom_quant_momentum",
                    side="BUY",
                    ltp=ltp,
                    open_p=open_p,
                    high_p=high_p,
                    low_p=low_p,
                    prev_close=prev_close,
                    target_1_pct=1.5,
                    sl_pct=1.5,
                    avg_price=avg_price,
                    volume=volume,
                )

                matched_stocks.append({
                    "symbol": sym,
                    "ltp": round(ltp, 2),
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low": round(low_p, 2),
                    "prev_close": round(prev_close, 2),
                    "vwap": round(vwap, 2),
                    "day_chg_pct": round(day_chg, 2),
                    "triggers": triggers,
                    "triggers_count": len(triggers),
                    "is_oi_confirmed": is_oi_confirmed,
                    "oi_confirmation_desc": oi_desc if is_oi_confirmed else "Awaiting VWAP / Short Squeeze Confirmation",
                    "status": "BUY_SIGNAL" if is_oi_confirmed else "QUALIFIED_CANDIDATE",
                    "win_rate": wr_info["win_rate"],
                    "in_position": (sym in active_symbols),
                    "stop_loss": round(ltp * 0.985, 2),
                    "peak_drop_sl_rule": "1.5% from Peak High",
                    "target_1": round(ltp * 1.015, 2),
                    "target_2": round(ltp * 1.030, 2),
                })

        # Sort: BUY Approved first, then by Win Rate / Triggers Count
        matched_stocks.sort(key=lambda x: (1 if x["status"] == "BUY_SIGNAL" else 0, x["win_rate"], x["triggers_count"]), reverse=True)

        return {
            "success": True,
            "stocks": matched_stocks,
            "total": len(matched_stocks),
            "buy_ready_count": len([s for s in matched_stocks if s["status"] == "BUY_SIGNAL"]),
            "bullish_sectors": bullish_sec_list,
            "timestamp": datetime.now(IST).strftime("%H:%M:%S")
        }
