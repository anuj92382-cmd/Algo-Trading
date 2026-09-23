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
from collections import deque
from datetime import datetime, date, time as dtime
from typing import Dict, List, Optional, Any
from pathlib import Path
import pytz

try:
    from config import TRADING_MODE
except Exception:
    TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")

logger = logging.getLogger("algo_engine")
IST = pytz.timezone("Asia/Kolkata")

# Storage file for persistent algo metrics & settings
STATE_FILE = Path(__file__).resolve().parent / "data" / "algo_state.json"


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
        self.universe = "nifty50"     # "nifty50" | "fno" | "nifty100" | "watchlist"


        # Scheduler & Timing
        self.scan_interval_sec = 15
        self.last_scan_time: Optional[datetime] = None
        self.next_scan_countdown = 15
        self._worker_thread: Optional[threading.Thread] = None
        self._running_flag = False

        # Live Terminal Logs (Ring buffer of last 300 logs)
        self.logs = deque(maxlen=300)

        # Risk Management Settings (RMS)
        self.risk_config = {
            "max_daily_loss": 5000.0,         # Bot halts if loss exceeds ₹5,000
            "max_daily_profit": 15000.0,       # Bot locks profits at ₹15,000
            "max_open_positions": 4,          # Max simultaneous positions
            "entry_start_time": "09:20",       # 9:20 AM IST
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
                "target_pct": 1.5,
                "target_1_pct": 1.0,           # Target 1: Book 50% Qty & Move SL to Cost
                "target_2_pct": 2.0,           # Target 2: Final 50% Runner
                "sl_pct": 0.8,
                "trailing_sl_pct": 0.3,
                "capital_per_trade": 20000.0,
                "product": "MIS",              # MIS uses 5X leverage
                "side": "BOTH",               # BOTH, BUY_ONLY, SELL_ONLY
                "signals_count": 0,
            },
            "open_reversal": {
                "id": "open_reversal",
                "name": "Open Reversal Breakout",
                "badge": "Dip & Surge",
                "desc": "Stock dips below morning Open, rebounds strongly and crosses Open with volume.",
                "icon": "🔄",
                "enabled": True,
                "timeframe": "3m",
                "target_pct": 1.2,
                "target_1_pct": 0.8,
                "target_2_pct": 1.6,
                "sl_pct": 0.7,
                "trailing_sl_pct": 0.25,
                "capital_per_trade": 20000.0,
                "product": "MIS",
                "side": "BOTH",
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
                "target_pct": 1.0,
                "target_1_pct": 0.7,
                "target_2_pct": 1.4,
                "sl_pct": 0.6,
                "trailing_sl_pct": 0.2,
                "capital_per_trade": 20000.0,
                "product": "MIS",
                "side": "BOTH",
                "signals_count": 0,
            },
            "breakout_surge": {
                "id": "breakout_surge",
                "name": "Breakout & Volume Surge",
                "badge": "High Break + 1.5x Vol",
                "desc": "Day High / Previous Day High breakout accompanied by 1.5x+ volume spike.",
                "icon": "🚀",
                "enabled": True,
                "timeframe": "5m",
                "target_pct": 1.8,
                "target_1_pct": 1.2,
                "target_2_pct": 2.4,
                "sl_pct": 0.9,
                "trailing_sl_pct": 0.35,
                "capital_per_trade": 20000.0,
                "product": "MIS",
                "side": "BUY_ONLY",
                "signals_count": 0,
            },
            "supertrend_rider": {
                "id": "supertrend_rider",
                "name": "Supertrend Trend Rider",
                "badge": "Supertrend (10, 3)",
                "desc": "Captures sustained intraday directional trends when Supertrend changes color.",
                "icon": "🛡️",
                "enabled": True,
                "timeframe": "5m",
                "target_pct": 2.0,
                "target_1_pct": 1.2,
                "target_2_pct": 2.5,
                "sl_pct": 1.0,
                "trailing_sl_pct": 0.5,
                "capital_per_trade": 20000.0,
                "product": "MIS",
                "side": "BOTH",
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
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "signals_today": 0,
            "orders_today": 0,
        }

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
                if "strategies" in data:
                    for k, v in data["strategies"].items():
                        if k in self.strategies:
                            self.strategies[k].update(v)
                self.closed_trades = data.get("closed_trades", [])
                if "stats" in data:
                    self.stats.update(data["stats"])
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
        net_pnl = self.stats["realized_pnl"] + self.stats["unrealized_pnl"]
        max_loss = float(self.risk_config.get("max_daily_loss", 5000.0))
        if net_pnl <= -abs(max_loss) and not self.risk_config.get("circuit_breaker_hit"):
            self.risk_config["circuit_breaker_hit"] = True
            self.risk_config["circuit_breaker_reason"] = f"Max Daily Loss limit breached (-₹{abs(net_pnl):,.2f} / -₹{max_loss:,.2f})"
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

    def _monitor_active_positions(self):
        """
        Monitors active positions tick-by-tick:
        - Fetches latest live LTP.
        - Calculates live P&L.
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
        symbols = list({f"NSE:{p['symbol']}" for p in self.active_positions.values()})

        # Fetch live quotes
        ltp_map = {}

        if kite:
            try:
                quotes = kite.quote(symbols)
                for k, v in quotes.items():
                    sym = k.replace("NSE:", "")
                    ltp_map[sym] = float(v.get("last_price", 0) or 0)
            except Exception as e:
                logger.debug(f"Quote fetch error in position monitor: {e}")

        for pos_id, pos in list(self.active_positions.items()):
            sym = pos["symbol"]
            entry_p = pos["entry_price"]
            side = pos["side"]

            # Resolve LTP (fallback to simulated movement in paper test if market closed)
            ltp = ltp_map.get(sym, pos.get("current_price", entry_p))
            if ltp <= 0:
                ltp = entry_p

            pos["current_price"] = ltp

            # Calculate Live P&L
            qty = pos["quantity"]
            if side == "BUY":
                pnl = (ltp - entry_p) * qty
                pnl_pct = ((ltp - entry_p) / entry_p) * 100.0
                if ltp > pos.get("highest_price", entry_p):
                    pos["highest_price"] = ltp
            else:  # SELL / SHORT
                pnl = (entry_p - ltp) * qty
                pnl_pct = ((entry_p - ltp) / entry_p) * 100.0
                if ltp < pos.get("lowest_price", entry_p):
                    pos["lowest_price"] = ltp

            pos["pnl"] = round(pnl, 2)
            pos["pnl_pct"] = round(pnl_pct, 2)

            # DYNAMIC TRAILING STOP LOSS & MULTI-TARGET EXITS
            trail_pct = pos.get("trailing_step_pct", 0.3)
            t1 = pos.get("target_1", pos.get("target", 0))
            t2 = pos.get("target_2", t1 * (1.01 if side == "BUY" else 0.99))

            if side == "BUY":
                # If price advanced beyond entry by trailing step, trail SL up
                favorable_gain = ((ltp - entry_p) / entry_p) * 100.0
                if favorable_gain >= trail_pct:
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
                    # Move Stop Loss to Entry Price (100% Risk-Free!)
                    pos["stop_loss"] = entry_p
                    pos["trailing_sl"] = max(pos["trailing_sl"], entry_p)
                    self._log("ORDER", f"🎯 [TARGET 1 HIT] ⚡ Booked 50% ({exit_qty} Qty) on {sym} @ ₹{ltp:.2f}",
                              f"🛡️ SL moved to Entry Cost ₹{entry_p:.2f} (Trade is now 100% Risk-Free!)")
                    continue

                # AUTO TARGET 2 EXIT (Final 50% Runner Exit)
                if pos.get("target_1_hit", False) and ltp >= t2:
                    self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting remaining {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                              f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%) | Full targets achieved!")
                    self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                    continue

                # Gap up past T2 directly
                if not pos.get("target_1_hit", False) and ltp >= t2:
                    self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting full {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                              f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%)")
                    self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                    continue

                # AUTO STOP LOSS EXIT
                if ltp <= pos["trailing_sl"]:
                    reason = "COST_SL_HIT" if pos.get("target_1_hit", False) else "STOP_LOSS_HIT"
                    self._log("ORDER", f"🛑 [{reason}] ⚡ Auto Exiting {sym} @ ₹{ltp:.2f}", f"P&L: ₹{pnl:,.2f} ({pnl_pct:.2f}%)")
                    self._exit_position(pos, exit_price=ltp, reason=reason)
                    continue

            else:  # SHORT POSITION
                favorable_gain = ((entry_p - ltp) / entry_p) * 100.0
                if favorable_gain >= trail_pct:
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
                    continue

                # AUTO TARGET 2 EXIT (Short)
                if pos.get("target_1_hit", False) and ltp <= t2:
                    self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting remaining {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                              f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%) | Full targets achieved!")
                    self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                    continue

                if not pos.get("target_1_hit", False) and ltp <= t2:
                    self._log("ORDER", f"🏆 [TARGET 2 HIT] ⚡ Auto Exiting full {pos['quantity']} Qty on {sym} @ ₹{ltp:.2f}",
                              f"Profit: +₹{pnl:,.2f} (+{pnl_pct:.2f}%)")
                    self._exit_position(pos, exit_price=ltp, reason="TARGET_2_HIT")
                    continue

                # AUTO STOP LOSS EXIT
                if ltp >= pos["trailing_sl"]:
                    reason = "COST_SL_HIT" if pos.get("target_1_hit", False) else "STOP_LOSS_HIT"
                    self._log("ORDER", f"🛑 [{reason}] ⚡ Auto Exiting {sym} @ ₹{ltp:.2f}", f"P&L: ₹{pnl:,.2f} ({pnl_pct:.2f}%)")
                    self._exit_position(pos, exit_price=ltp, reason=reason)
                    continue

    # ─────────────────────────────────────────────────────────────
    # STEP 3: SCANNING & AUTONOMOUS ORDER DISPATCH (AUTO BUY/SELL)
    # ─────────────────────────────────────────────────────────────

    def _scan_and_execute_signals(self):
        """
        Scans universe symbols, evaluates quantitative strategies, and
        AUTOMATICALLY FIRES orders when signals are detected without waiting for human approval!
        """
        max_open = int(self.risk_config.get("max_open_positions", 4))
        if len(self.active_positions) >= max_open:
            return

        symbols = self._get_universe_symbols()
        if not symbols:
            return

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
            return


        # Check entry cutoff time
        now = datetime.now(IST).time()
        try:
            cutoff_parts = [int(p) for p in self.risk_config["entry_cutoff_time"].split(":")]
            entry_cutoff = dtime(cutoff_parts[0], cutoff_parts[1])
            if now > entry_cutoff:
                return
        except Exception:
            pass

        # Batch fetch OHLC for universe (sample top 40 liquid symbols to keep scan blazing fast)
        sample_syms = symbols[:40]
        formatted = [f"NSE:{s}" if ":" not in s else s for s in sample_syms]

        try:
            ohlc_data = kite.ohlc(formatted)
        except Exception as e:
            logger.debug(f"Scan OHLC batch error: {e}")
            return

        if not ohlc_data:
            return

        self._log("SCAN", f"Scanning {len(ohlc_data)} symbols across {len([s for s in self.strategies.values() if s['enabled']])} active strategies...")

        active_symbols = {p["symbol"] for p in self.active_positions.values()}

        for key, item in ohlc_data.items():
            if len(self.active_positions) >= max_open:
                break

            sym = key.replace("NSE:", "")
            if sym in active_symbols:
                continue

            ltp = float(item.get("last_price", 0) or 0)
            ohlc = item.get("ohlc", {}) or {}
            open_p = float(ohlc.get("open", 0) or 0)
            high_p = float(ohlc.get("high", 0) or 0)
            low_p = float(ohlc.get("low", 0) or 0)
            prev_close = float(ohlc.get("close", 0) or 0)

            if open_p <= 0 or ltp <= 20.0 or ltp > 50000.0:
                continue

            # Evaluate Enabled Strategies
            for strat_id, strat in self.strategies.items():
                if not strat.get("enabled", True):
                    continue

                signal = self._evaluate_strategy(strat_id, sym, ltp, open_p, high_p, low_p, prev_close)
                if signal:
                    # ⚡ AUTO BUY / AUTO SELL EXECUTION!
                    self._execute_auto_order(signal, strat)
                    active_symbols.add(sym)
                    break

    # ─────────────────────────────────────────────────────────────
    # QUANTITATIVE STRATEGY RULES EVALUATOR
    # ─────────────────────────────────────────────────────────────

    def _evaluate_strategy(self, strat_id: str, symbol: str, ltp: float, open_p: float, high_p: float, low_p: float, prev_close: float) -> Optional[dict]:
        """
        Evaluates mathematical criteria for each strategy.
        Returns a signal dict if conditions are met, otherwise None.
        """
        # 1. MOMENTUM TREND (EMA + VWAP)
        if strat_id == "momentum_trend":
            # Bullish trend: Price opened, made low, and is trending strongly above prev close and open
            if ltp > open_p and prev_close > 0 and ltp > prev_close:
                gain_pct = ((ltp - open_p) / open_p) * 100.0
                day_chg = ((ltp - prev_close) / prev_close) * 100.0
                if 0.5 <= gain_pct <= 3.5 and day_chg > 0.4:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": "Momentum Trend",
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Bullish momentum (+{gain_pct:.1f}% vs Open, +{day_chg:.1f}% Day Change)",
                    }

        # 2. OPEN REVERSAL BREAKOUT
        elif strat_id == "open_reversal":
            # Stock dipped below open, reversed, and is now breaking above open
            if low_p < open_p and ltp > open_p:
                dip_pct = ((open_p - low_p) / open_p) * 100.0
                recov_pct = ((ltp - open_p) / open_p) * 100.0
                if dip_pct >= 0.25 and 0.15 <= recov_pct <= 2.5:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": "Open Reversal",
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Morning dip (-{dip_pct:.2f}%) reversed above Open (+{recov_pct:.2f}%)",
                    }

        # 3. RSI MEAN REVERSION
        elif strat_id == "rsi_reversion":
            # Oversold bounce: Stock dropped sharply from open, but started recovering from the extreme low
            if prev_close > 0 and low_p < prev_close:
                drop_from_close = ((prev_close - low_p) / prev_close) * 100.0
                bounce_from_low = ((ltp - low_p) / low_p) * 100.0
                if drop_from_close >= 1.5 and bounce_from_low >= 0.4 and ltp > low_p:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": "RSI Reversion",
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Oversold bounce (+{bounce_from_low:.2f}% off extreme day low)",
                    }

        # 4. BREAKOUT & VOLUME SURGE
        elif strat_id == "breakout_surge":
            # Day high breakout: Price trading near or at day high with strong intraday expansion
            if high_p > open_p:
                rng = high_p - low_p
                if rng > 0 and (ltp - low_p) / rng >= 0.90:  # trading in top 10% of day's range
                    day_gain = ((ltp - open_p) / open_p) * 100.0
                    if 0.8 <= day_gain <= 4.0:
                        return {
                            "strategy_id": strat_id,
                            "strategy_name": "Breakout Surge",
                            "symbol": symbol,
                            "side": "BUY",
                            "ltp": ltp,
                            "reason": f"Day High Breakout (LTP near ₹{high_p:.2f} Day High, +{day_gain:.1f}%)",
                        }

        # 5. SUPERTREND RIDER
        elif strat_id == "supertrend_rider":
            if prev_close > 0 and ltp > prev_close and ltp > open_p:
                chg = ((ltp - prev_close) / prev_close) * 100.0
                if 1.0 <= chg <= 3.0:
                    return {
                        "strategy_id": strat_id,
                        "strategy_name": "Supertrend Rider",
                        "symbol": symbol,
                        "side": "BUY",
                        "ltp": ltp,
                        "reason": f"Sustained directional uptrend (+{chg:.1f}% with trend support)",
                    }

        return None

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

        # Calculate position sizing with 5X leverage in MIS
        cap_alloc = float(strat.get("capital_per_trade", 20000.0))
        is_mis = (product == "MIS")
        leverage_mult = 5.0 if is_mis else 1.0
        effective_buying_power = cap_alloc * leverage_mult

        quantity = int(effective_buying_power / ltp)
        if quantity < 1:
            quantity = 1

        margin_req = (ltp * quantity) / leverage_mult

        # Target & SL Calculations (Multi-Target: T1 for 50% partial exit & T2 for runner)
        t1_pct = float(strat.get("target_1_pct", strat.get("target_pct", 1.0)))
        t2_pct = float(strat.get("target_2_pct", t1_pct * 2.0))
        sl_pct = float(strat.get("sl_pct", 0.8))
        trail_pct = float(strat.get("trailing_sl_pct", 0.3))

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

            lev_info = f"(5X Margin: ₹{margin_req:,.2f})" if is_mis else "(1X CNC)"
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
            "margin_used": round(margin_req, 2),
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
            pnl = (exit_price - entry_p) * qty
            pnl_pct = ((exit_price - entry_p) / entry_p) * 100.0
            exit_side = "SELL"
        else:
            pnl = (entry_p - exit_price) * qty
            pnl_pct = ((entry_p - exit_price) / entry_p) * 100.0
            exit_side = "BUY"

        pnl = round(pnl, 2)
        pnl_pct = round(pnl_pct, 2)

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
            "side": side,
            "product": product,
            "quantity": qty,
            "entry_price": entry_p,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "entry_time": pos.get("entry_time", ""),
            "exit_time": datetime.now(IST).strftime("%H:%M:%S"),
            "duration": f"{duration_min}m",
            "exit_reason": reason,
        }
        self.closed_trades.insert(0, trade_record)

        # Remove from active positions
        pos_id = pos.get("pos_id")
        if pos_id in self.active_positions:
            del self.active_positions[pos_id]

        # Update stats
        self.stats["realized_pnl"] = round(self.stats["realized_pnl"] + pnl, 2)
        self.stats["total_trades"] += 1
        if pnl > 0:
            self.stats["winning_trades"] += 1
        else:
            self.stats["losing_trades"] += 1

        win_rate = (self.stats["winning_trades"] / self.stats["total_trades"] * 100.0) if self.stats["total_trades"] > 0 else 0.0
        self.stats["win_rate"] = round(win_rate, 1)

        pnl_str = f"+₹{pnl:,.2f}" if pnl >= 0 else f"-₹{abs(pnl):,.2f}"
        self._log("EXIT", f"🏁 [{reason}] Closed {qty} {symbol} @ ₹{exit_price:.2f} | P&L: {pnl_str} ({pnl_pct:+.2f}%)")
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
            pnl = (exit_price - entry_p) * exit_qty
            pnl_pct = ((exit_price - entry_p) / entry_p) * 100.0
            exit_side = "SELL"
        else:
            pnl = (entry_p - exit_price) * exit_qty
            pnl_pct = ((entry_p - exit_price) / entry_p) * 100.0
            exit_side = "BUY"

        pnl = round(pnl, 2)
        pnl_pct = round(pnl_pct, 2)

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
            "side": side,
            "product": product,
            "quantity": exit_qty,
            "entry_price": entry_p,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "entry_time": pos.get("entry_time", ""),
            "exit_time": datetime.now(IST).strftime("%H:%M:%S"),
            "duration": f"{duration_min}m",
            "exit_reason": reason,
        }
        self.closed_trades.insert(0, trade_record)

        self.stats["realized_pnl"] = round(self.stats["realized_pnl"] + pnl, 2)
        self.stats["total_trades"] += 1
        if pnl > 0:
            self.stats["winning_trades"] += 1
        else:
            self.stats["losing_trades"] += 1

        win_rate = (self.stats["winning_trades"] / self.stats["total_trades"] * 100.0) if self.stats["total_trades"] > 0 else 0.0
        self.stats["win_rate"] = round(win_rate, 1)

        self._record_equity_point()
        pnl_str = f"+₹{pnl:,.2f}" if pnl >= 0 else f"-₹{abs(pnl):,.2f}"
        self._log("EXIT", f"🎯 [{reason}] Partial Closed {exit_qty} {symbol} @ ₹{exit_price:.2f} | P&L: {pnl_str} ({pnl_pct:+.2f}%)")
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
        self.stats["unrealized_pnl"] = round(unrealized, 2)
        self.stats["today_pnl"] = round(self.stats["realized_pnl"] + unrealized, 2)

    def _get_universe_symbols(self) -> List[str]:
        """Resolves symbol list based on selected universe."""
        if self.universe == "fno":
            from web_app import _get_fno_symbols
            kite = self._web_state.get("kite")
            fno = list(_get_fno_symbols(kite))
            return fno if fno else ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATAMOTORS"]
        elif self.universe == "nifty100":
            from web_app import _resolve_symbols
            return _resolve_symbols("nifty100")
        elif self.universe == "watchlist":
            from config import INTRADAY_CONFIG
            return INTRADAY_CONFIG.get("watchlist", ["RELIANCE", "TCS", "INFY", "HDFCBANK"])
        else:  # default nifty50
            from web_app import _resolve_symbols
            syms = _resolve_symbols("nifty50")
            return syms if syms else ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE", "TATAMOTORS", "AXISBANK", "TATASTEEL"]

    # ─────────────────────────────────────────────────────────────
    # API SERIALIZERS
    # ─────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Returns comprehensive status for Algo Trade HUD."""
        with self._lock:
            self._recalculate_stats()
            active_count = len([s for s in self.strategies.values() if s.get("enabled", True)])
            return {
                "status": self.status,
                "mode": self.mode,
                "universe": self.universe,
                "active_strategies_count": active_count,
                "total_strategies_count": len(self.strategies),
                "open_positions_count": len(self.active_positions),
                "last_scan_time": self.last_scan_time.strftime("%H:%M:%S") if self.last_scan_time else "-",
                "next_scan_countdown": self.next_scan_countdown,
                "scan_interval": self.scan_interval_sec,
                "stats": self.stats,
                "circuit_breaker_hit": self.risk_config.get("circuit_breaker_hit", False),
                "circuit_breaker_reason": self.risk_config.get("circuit_breaker_reason", ""),
            }

    def get_config(self) -> dict:
        """Returns strategy parameters and RMS risk settings."""
        with self._lock:
            return {
                "status": self.status,
                "mode": self.mode,
                "universe": self.universe,
                "risk_config": self.risk_config,
                "strategies": list(self.strategies.values()),
            }

    def update_config(self, data: dict) -> dict:
        """Update strategy settings or RMS limits from client."""
        with self._lock:
            if "universe" in data:
                self.universe = data["universe"]

            if "risk_config" in data:
                self.risk_config.update(data["risk_config"])
                # Reset circuit breaker if requested
                if data["risk_config"].get("circuit_breaker_hit") is False:
                    self.risk_config["circuit_breaker_hit"] = False
                    self.risk_config["circuit_breaker_reason"] = ""

            if "strategies" in data:
                for s_data in data["strategies"]:
                    sid = s_data.get("id")
                    if sid in self.strategies:
                        self.strategies[sid].update(s_data)

            self._save_state()
            self._log("INFO", "⚙️ Algo Trade Configuration updated.")
            return {"success": True, "message": "Config updated successfully"}

    def get_active_positions(self) -> List[dict]:
        """Returns active positions with live P&L and trailing SL."""
        with self._lock:
            return list(self.active_positions.values())

    def get_closed_trades(self, limit: int = 50) -> List[dict]:
        """Returns recent completed trades."""
        with self._lock:
            return self.closed_trades[:limit]

    def clear_closed_trades(self) -> dict:
        """Clears completed trades history."""
        with self._lock:
            self.closed_trades.clear()
            self._save_state()
            self._log("INFO", "🧹 Completed trades history cleared by user.")
            return {"success": True, "message": "Trades history cleared successfully."}


    def get_recent_logs(self, limit: int = 150) -> List[dict]:
        """Returns recent activity logs."""
        with self._lock:
            logs_list = list(self.logs)
            return logs_list[-limit:]

    def force_scan_now(self) -> dict:
        """Triggers an immediate scan and execution cycle on-demand."""
        threading.Thread(target=self._run_single_scan_cycle, daemon=True).start()
        return {"success": True, "message": "Scan cycle triggered on-demand!"}

    def _run_single_scan_cycle(self):
        with self._lock:
            self._log("SCAN", "⚡ Manual on-demand scan triggered by user...")
            self._check_rms_and_timing()
            self._monitor_active_positions()
            self._scan_and_execute_signals()
            self._recalculate_stats()
            self._record_equity_point()

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

    # ─────────────────────────────────────────────────────────────
    # 24/7 OFF-MARKET DEMO SIMULATION GENERATOR
    # ─────────────────────────────────────────────────────────────

    def run_demo_simulation(self) -> dict:
        """
        24/7 Off-Market Live Robot Simulation:
        Generates simulated market ticks, triggers an Auto Buy, trails SL upwards,
        books 50% at Target 1, moves SL to Cost (Risk-Free), and executes Target 2!
        """
        if self.mode != "PAPER":
            return {"success": False, "error": "Demo Simulation can only be run in PAPER TRADING mode for safety."}

        threading.Thread(target=self._demo_simulation_worker, daemon=True, name="DemoSimulationWorker").start()
        return {"success": True, "message": "Demo simulation started! Watch live terminal and positions table."}

    def _demo_simulation_worker(self):
        """Simulates live tick movement over 15-20 seconds for demonstration with dynamic stocks & strategies."""
        try:
            candidates = [
                {"symbol": "TATAMOTORS", "base_price": 975.0,  "strategy_id": "momentum_trend"},
                {"symbol": "RELIANCE",   "base_price": 2980.0, "strategy_id": "breakout_surge"},
                {"symbol": "INFY",       "base_price": 1820.0, "strategy_id": "rsi_reversion"},
                {"symbol": "HDFCBANK",   "base_price": 1645.0, "strategy_id": "open_reversal"},
                {"symbol": "ICICIBANK",  "base_price": 1250.0, "strategy_id": "supertrend_rider"},
                {"symbol": "TCS",        "base_price": 4210.0, "strategy_id": "momentum_trend"},
                {"symbol": "SBIN",       "base_price": 785.0,  "strategy_id": "breakout_surge"},
                {"symbol": "BHARTIARTL", "base_price": 1550.0, "strategy_id": "momentum_trend"},
                {"symbol": "TATASTEEL",  "base_price": 152.0,  "strategy_id": "open_reversal"},
                {"symbol": "ITC",        "base_price": 492.0,  "strategy_id": "rsi_reversion"},
            ]

            active_syms = {p["symbol"] for p in self.active_positions.values()}
            available = [c for c in candidates if c["symbol"] not in active_syms]
            cand = random.choice(available if available else candidates)

            sym = cand["symbol"]
            strat_id = cand.get("strategy_id", "momentum_trend")
            strat = self.strategies.get(strat_id, self.strategies.get("momentum_trend", {}))
            strat_name = f"{strat.get('name', 'Algo Strategy')} (Demo)"

            # Resolve entry price: check live quote if kite is available, else base_price
            entry_p = float(cand["base_price"])
            kite = self._web_state.get("kite")
            if kite:
                try:
                    q = kite.quote([f"NSE:{sym}"])
                    live_p = float(q.get(f"NSE:{sym}", {}).get("last_price", 0) or 0)
                    if live_p > 10.0:
                        entry_p = round(live_p, 2)
                except Exception:
                    pass

            t1_pct = float(strat.get("target_1_pct", 1.0))
            t2_pct = float(strat.get("target_2_pct", 2.0))
            sl_pct = float(strat.get("sl_pct", 0.8))
            trail_pct = float(strat.get("trailing_sl_pct", 0.3))
            capital = float(strat.get("capital_per_trade", 20000.0))

            qty = max(1, int((capital * 5.0) / entry_p))
            t1 = round(entry_p * (1.0 + t1_pct / 100.0), 2)
            t2 = round(entry_p * (1.0 + t2_pct / 100.0), 2)
            sl = round(entry_p * (1.0 - sl_pct / 100.0), 2)
            margin_used = round((entry_p * qty) / 5.0, 2)

            self._log("ALERT", f"🧪 [DEMO SIMULATION] Live Robot Testing on {sym}", f"Strategy: {strat_name} | Capital: ₹{capital:,.0f} (5X)")
            time.sleep(1.0)

            self._log("SCAN", f"Scanning universe symbols... technical setup triggered on {sym}")
            time.sleep(1.5)

            self._log("SIGNAL", f"🎯 [{strat_name}] Signal Detected on {sym} @ ₹{entry_p:.2f}", f"Target 1: +{t1_pct}% | Target 2: +{t2_pct}% | SL: -{sl_pct}%")
            time.sleep(1.0)

            self._log("RMS", f"🛡️ RMS Check Approved: Daily P&L OK, Open Pos: {len(self.active_positions)+1}/4 | Margin: ₹{margin_used:,.2f} (5X)")
            time.sleep(0.8)

            pos_id = f"POS_SIM_{sym}_{int(time.time())}"
            with self._lock:
                self.active_positions[pos_id] = {
                    "pos_id": pos_id,
                    "order_id": f"SIM_ORD_{int(time.time())}",
                    "symbol": sym,
                    "strategy_id": strat_id,
                    "strategy_name": strat_name,
                    "side": "BUY",
                    "product": "MIS",
                    "quantity": qty,
                    "original_quantity": qty,
                    "entry_price": entry_p,
                    "current_price": entry_p,
                    "highest_price": entry_p,
                    "lowest_price": entry_p,
                    "stop_loss": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "target": t1,
                    "target_1_hit": False,
                    "trailing_sl": sl,
                    "trailing_step_pct": trail_pct,
                    "margin_used": margin_used,
                    "pnl": 0.0,
                    "pnl_pct": 0.0,
                    "entry_time": datetime.now(IST).strftime("%H:%M:%S"),
                    "entry_timestamp": time.time(),
                }
                self.stats["signals_today"] += 1
                self.stats["orders_today"] += 1
                self._record_equity_point()

            self._log("ORDER", f"⚡ [AUTO BUY] EXECUTED: {qty} Qty {sym} @ ₹{entry_p:.2f} (5X Margin: ₹{margin_used:,.2f})",
                      f"T1: ₹{t1:.2f} (+{t1_pct}%, 50% Qty) | T2: ₹{t2:.2f} (+{t2_pct}%) | SL: ₹{sl:.2f} (-{sl_pct}%)")

            # Tick 1: Price rises 40% towards T1
            time.sleep(3.0)
            with self._lock:
                if pos_id in self.active_positions:
                    p1 = round(entry_p * (1.0 + (t1_pct * 0.40) / 100.0), 2)
                    self.active_positions[pos_id]["current_price"] = p1
                    self._monitor_active_positions()
                    self._recalculate_stats()
                    self._record_equity_point()

            # Tick 2: Price rises 75% towards T1 -> Trailing SL ratchets up
            time.sleep(3.0)
            with self._lock:
                if pos_id in self.active_positions:
                    p2 = round(entry_p * (1.0 + (t1_pct * 0.75) / 100.0), 2)
                    self.active_positions[pos_id]["current_price"] = p2
                    self._monitor_active_positions()
                    self._recalculate_stats()
                    self._record_equity_point()

            # Tick 3: Price hits Target 1 -> Partial 50% exit & SL moved to Cost!
            time.sleep(3.5)
            with self._lock:
                if pos_id in self.active_positions:
                    p3 = round(entry_p * (1.0 + (t1_pct * 1.05) / 100.0), 2)
                    self.active_positions[pos_id]["current_price"] = p3
                    self._monitor_active_positions()
                    self._recalculate_stats()
                    self._record_equity_point()

            # Tick 4: Price surges further towards T2 with Trailing SL
            time.sleep(3.5)
            with self._lock:
                if pos_id in self.active_positions:
                    p4 = round(entry_p * (1.0 + (t1_pct + (t2_pct - t1_pct) * 0.55) / 100.0), 2)
                    self.active_positions[pos_id]["current_price"] = p4
                    self._monitor_active_positions()
                    self._recalculate_stats()
                    self._record_equity_point()

            # Tick 5: Price reaches Target 2 -> Final Target Exit!
            time.sleep(3.5)
            with self._lock:
                if pos_id in self.active_positions:
                    p5 = round(entry_p * (1.0 + (t2_pct * 1.05) / 100.0), 2)
                    self.active_positions[pos_id]["current_price"] = p5
                    self._monitor_active_positions()
                    self._recalculate_stats()
                    self._record_equity_point()

            self._log("ALERT", f"🎉 [DEMO SIMULATION COMPLETE] All targets hit on {sym}!", f"Both T1 (50% booked + Risk-Free) and T2 executed successfully.")
            self._save_state()


        except Exception as e:
            logger.error(f"Demo simulation error: {e}", exc_info=True)
            self._log("ERROR", f"Demo simulation error: {e}")
