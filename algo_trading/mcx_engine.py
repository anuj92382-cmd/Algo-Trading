"""
mcx_engine.py - Autonomous MCX Commodity Algo Trading Engine
Supports 100% Automated Trading for Gold, Silver, Crude Oil, Natural Gas, Copper, Zinc.
Operates on MCX Market Hours (09:00 AM - 11:30 PM IST).
Features:
- Continuous background execution loop
- Real-time quantitative scanning (EMA 9/21 cross, Supertrend, RSI Reversion, ORB Breakout)
- Dynamic Trailing Stop Loss & Target Management
- EOD 11:15 PM Auto Square-Off & RMS Circuit Breakers
"""

import json
import logging
import time
import threading
from datetime import datetime, date, timedelta, time as dtime
from pathlib import Path
from typing import Dict, List, Optional
import pytz

logger = logging.getLogger("mcx_engine")
IST = pytz.timezone("Asia/Kolkata")

STATE_FILE = Path(__file__).resolve().parent / "data" / "mcx_state.json"

DEFAULT_COMMODITY_CONFIG = {
    "CRUDEOIL": {
        "id": "CRUDEOIL",
        "name": "Crude Oil",
        "icon": "🛢️",
        "unit": "bbl",
        "strategy": "Momentum Breakout (5m EMA + VWAP)",
        "strategy_type": "EMA_MOMENTUM",
        "enabled": True,
        "timeframe": "5m",
        "target_1_pct": 1.0,
        "target_2_pct": 2.0,
        "sl_pct": 0.7,
        "trailing_sl_pct": 0.3,
        "fixed_qty": 1,
    },
    "GOLD": {
        "id": "GOLD",
        "name": "Gold",
        "icon": "🥇",
        "unit": "10g",
        "strategy": "Supertrend Trend Rider (15m)",
        "strategy_type": "SUPERTREND",
        "enabled": True,
        "timeframe": "15m",
        "target_1_pct": 0.8,
        "target_2_pct": 1.6,
        "sl_pct": 0.5,
        "trailing_sl_pct": 0.25,
        "fixed_qty": 1,
    },
    "SILVER": {
        "id": "SILVER",
        "name": "Silver",
        "icon": "🥈",
        "unit": "1kg",
        "strategy": "RSI Mean Reversion (5m)",
        "strategy_type": "RSI_REVERSION",
        "enabled": True,
        "timeframe": "5m",
        "target_1_pct": 1.2,
        "target_2_pct": 2.2,
        "sl_pct": 0.8,
        "trailing_sl_pct": 0.35,
        "fixed_qty": 1,
    },
    "NATURALGAS": {
        "id": "NATURALGAS",
        "name": "Natural Gas",
        "icon": "💨",
        "unit": "mmBtu",
        "strategy": "Opening Range Breakout (15m)",
        "strategy_type": "ORB_BREAKOUT",
        "enabled": True,
        "timeframe": "15m",
        "target_1_pct": 1.5,
        "target_2_pct": 2.5,
        "sl_pct": 1.0,
        "trailing_sl_pct": 0.4,
        "fixed_qty": 1,
    },
    "COPPER": {
        "id": "COPPER",
        "name": "Copper",
        "icon": "🥉",
        "unit": "1kg",
        "strategy": "EMA & VWAP Trend Flow (5m)",
        "strategy_type": "EMA_MOMENTUM",
        "enabled": True,
        "timeframe": "5m",
        "target_1_pct": 0.8,
        "target_2_pct": 1.5,
        "sl_pct": 0.5,
        "trailing_sl_pct": 0.2,
        "fixed_qty": 1,
    },
    "ZINC": {
        "id": "ZINC",
        "name": "Zinc",
        "icon": "⚙️",
        "unit": "1kg",
        "strategy": "Volume Surge Momentum (5m)",
        "strategy_type": "EMA_MOMENTUM",
        "enabled": True,
        "timeframe": "5m",
        "target_1_pct": 0.8,
        "target_2_pct": 1.5,
        "sl_pct": 0.5,
        "trailing_sl_pct": 0.2,
        "fixed_qty": 1,
    },
}


class MCXEngine:
    def __init__(self, web_state: dict):
        self._web_state = web_state
        self._lock = threading.RLock()
        self.status = "RUNNING"       # RUNNING, PAUSED, STOPPED
        self.mode = "PAPER"           # PAPER, LIVE
        
        self.commodity_config = dict(DEFAULT_COMMODITY_CONFIG)
        self.risk_config = {
            "max_daily_loss": 10000.0,
            "max_daily_profit": 25000.0,
            "max_open_positions": 3,
            "auto_squareoff_time": "23:15",
            "circuit_breaker_hit": False,
            "circuit_breaker_reason": "",
        }
        
        self.contracts: Dict[str, dict] = {}      # 'CRUDEOIL' -> contract details
        self.last_contracts_fetch = 0
        self.quotes_cache: Dict[str, dict] = {}
        self.last_quotes_fetch = 0
        self.candles_cache: Dict[str, dict] = {}   # sym -> {last_fetch, data}
        
        self.active_positions: Dict[str, dict] = {}  # pos_id -> position dict
        self.closed_trades: List[dict] = []
        self.logs: List[dict] = []
        
        self.stats = {
            "today_pnl": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "trades_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
        }
        
        # Autonomous execution thread
        self._running_flag = True
        self._worker_thread: Optional[threading.Thread] = None
        self._scan_lock = threading.Lock()
        
        self._load_state()
        self._start_worker()
        self._log("INIT", "🪙 Fully Automated MCX Algo Engine Initialized", "Autonomous Loop Active | 09:00 AM – 11:30 PM IST")

    def _start_worker(self):
        if not self._worker_thread or not self._worker_thread.is_alive():
            self._running_flag = True
            self._worker_thread = threading.Thread(target=self._execution_loop, daemon=True, name="MCX-Algo-Worker")
            self._worker_thread.start()
            logger.info("📡 MCX Autonomous Execution Worker thread launched.")

    def _log(self, tag: str, title: str, details: str = ""):
        entry = {
            "time": datetime.now(IST).strftime("%H:%M:%S"),
            "tag": tag,
            "title": title,
            "details": details,
        }
        with self._lock:
            self.logs.insert(0, entry)
            if len(self.logs) > 150:
                self.logs = self.logs[:150]

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.status = data.get("status", "RUNNING")
                    self.mode = data.get("mode", "PAPER")
                    self.active_positions = data.get("active_positions", {})
                    self.closed_trades = data.get("closed_trades", [])
                    self.stats = data.get("stats", self.stats)
                    if "risk_config" in data:
                        self.risk_config.update(data["risk_config"])
                    if "commodity_config" in data:
                        self.commodity_config.update(data["commodity_config"])
        except Exception as e:
            logger.debug(f"MCX state load error: {e}")

    def _save_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "status": self.status,
                    "mode": self.mode,
                    "active_positions": self.active_positions,
                    "closed_trades": self.closed_trades[-100:],
                    "stats": self.stats,
                    "risk_config": self.risk_config,
                    "commodity_config": self.commodity_config,
                }, f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"MCX state save error: {e}")

    def is_market_open(self) -> bool:
        now = datetime.now(IST)
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        return dtime(9, 0) <= now.time() <= dtime(23, 30)

    def get_session_info(self) -> dict:
        now = datetime.now(IST)
        now_time = now.time()
        is_open = self.is_market_open()
        
        if not is_open:
            session_name = "Market Closed"
            badge_class = "red"
        elif now_time >= dtime(17, 0):
            session_name = "Evening Session (Active)"
            badge_class = "green"
        else:
            session_name = "Morning Session (Active)"
            badge_class = "green"

        return {
            "is_open": is_open,
            "session_name": session_name,
            "badge_class": badge_class,
            "timing_text": "09:00 AM – 11:30 PM IST",
        }

    # ─────────────────────────────────────────────────────────────
    # AUTONOMOUS EXECUTION WORKER LOOP
    # ─────────────────────────────────────────────────────────────

    def _execution_loop(self):
        """
        Continuous background worker running every 3-5 seconds:
        1. Checks RMS limits, circuit breakers & 11:15 PM EOD square-off.
        2. Monitors active positions: Trailing Stop Loss & Multi-Target exits.
        3. Scans enabled commodities for algorithmic signals and executes orders automatically.
        """
        logger.info("Autonomous MCX Engine execution loop started.")
        while self._running_flag:
            try:
                if self.status == "RUNNING" and not self.risk_config.get("circuit_breaker_hit"):
                    # Step 1: RMS & EOD Checks
                    self._check_rms_and_timing()

                    # Step 2: Monitor open positions
                    self._monitor_active_positions()

                    # Step 3: Scan commodities & auto execute signals if market is open
                    if self.is_market_open():
                        self._scan_and_execute_signals()

                time.sleep(4)
            except Exception as e:
                logger.error(f"Error in MCX execution loop: {e}", exc_info=True)
                time.sleep(5)

    def _check_rms_and_timing(self):
        """Validates daily loss caps, profit locks, and 11:15 PM EOD square-off."""
        now = datetime.now(IST)
        now_time = now.time()

        # 11:15 PM EOD Auto Square-Off
        sq_time = dtime(23, 15)
        if now_time >= sq_time:
            if self.active_positions:
                self._log("ALERT", "⏰ 11:15 PM EOD CUTOFF: Auto squaring off all commodity positions.")
                for pos_id, pos in list(self.active_positions.items()):
                    self.exit_position(pos_id, exit_price=pos.get("current_price", pos.get("entry_price")), reason="EOD_CUTOFF_11:15PM")

        # Daily Loss Circuit Breaker
        max_loss = float(self.risk_config.get("max_daily_loss", 10000.0))
        net_loss = self.stats.get("realized_pnl", 0.0) + self.stats.get("unrealized_pnl", 0.0)
        if net_loss <= -abs(max_loss) and not self.risk_config.get("circuit_breaker_hit"):
            self.risk_config["circuit_breaker_hit"] = True
            self.risk_config["circuit_breaker_reason"] = f"Max Daily Loss breached (-₹{abs(net_loss):,.2f} / -₹{max_loss:,.2f})"
            self.status = "STOPPED"
            self._log("ALERT", "🛑 MCX CIRCUIT BREAKER HIT!", self.risk_config["circuit_breaker_reason"])
            # Square off all open positions
            for pos_id, pos in list(self.active_positions.items()):
                self.exit_position(pos_id, exit_price=pos.get("current_price", pos.get("entry_price")), reason="RMS_LOSS_LIMIT")

        # Daily Profit Target Lock
        max_profit = float(self.risk_config.get("max_daily_profit", 25000.0))
        if self.stats.get("realized_pnl", 0.0) >= max_profit and self.status == "RUNNING":
            self.status = "PAUSED"
            self._log("INFO", "🎯 DAILY PROFIT TARGET HIT! 💰", f"Realized P&L ₹{self.stats['realized_pnl']:,.2f} reached target ₹{max_profit:,.2f}. Bot paused to lock in profits.")

    def _monitor_active_positions(self):
        """Applies dynamic Trailing Stop Loss, Target 1, and Stop Loss exits."""
        quotes = self.fetch_live_quotes()
        if not quotes:
            return

        with self._lock:
            for pos_id, pos in list(self.active_positions.items()):
                sym = pos["tradingsymbol"]
                q = quotes.get(f"MCX:{sym}")
                if not q:
                    continue

                ltp = float(q.get("last_price", 0) or pos["current_price"])
                if ltp <= 0:
                    continue

                pos["current_price"] = ltp
                entry = float(pos["entry_price"])
                qty = int(pos["quantity"])
                side = pos["side"]

                # P&L Calculation
                pnl = (ltp - entry) * qty if side == "BUY" else (entry - ltp) * qty
                pos["pnl"] = round(pnl, 2)
                denom = entry * qty
                pos["pnl_pct"] = round((pnl / denom) * 100.0, 2) if denom > 0 else 0.0

                # High/Low Watermark Tracking for Trailing SL
                if side == "BUY":
                    if ltp > pos.get("highest_price", entry):
                        pos["highest_price"] = ltp
                        # Dynamic Trailing SL: as price rises by trail_step %, move SL up
                        trail_step_pct = float(pos.get("trailing_sl_pct", 0.3))
                        trail_gain_pct = ((ltp - entry) / entry) * 100.0
                        if trail_gain_pct >= trail_step_pct:
                            new_sl = round(ltp * (1.0 - (trail_step_pct * 1.5) / 100.0), 2)
                            if new_sl > pos.get("stop_loss", 0):
                                pos["stop_loss"] = new_sl
                                self._log("TRAIL", f"📈 Trailed SL for {sym}", f"New SL: ₹{new_sl:,.2f} | LTP: ₹{ltp:,.2f}")
                else:  # SELL
                    if ltp < pos.get("lowest_price", entry):
                        pos["lowest_price"] = ltp
                        trail_step_pct = float(pos.get("trailing_sl_pct", 0.3))
                        trail_gain_pct = ((entry - ltp) / entry) * 100.0
                        if trail_gain_pct >= trail_step_pct:
                            new_sl = round(ltp * (1.0 + (trail_step_pct * 1.5) / 100.0), 2)
                            if pos.get("stop_loss", 0) == 0 or new_sl < pos["stop_loss"]:
                                pos["stop_loss"] = new_sl
                                self._log("TRAIL", f"📉 Trailed SL for {sym}", f"New SL: ₹{new_sl:,.2f} | LTP: ₹{ltp:,.2f}")

                # Exits Check
                target_1 = float(pos.get("target_1", pos.get("target", 0)))
                target_2 = float(pos.get("target_2", 0))
                stop_loss = float(pos.get("stop_loss", 0))

                if side == "BUY":
                    if target_2 > 0 and ltp >= target_2:
                        self.exit_position(pos_id, exit_price=ltp, reason="TARGET_2_HIT")
                    elif target_1 > 0 and ltp >= target_1 and not pos.get("target_1_hit"):
                        pos["target_1_hit"] = True
                        pos["stop_loss"] = entry  # Move SL to cost (Risk Free!)
                        self._log("TARGET", f"🎯 Target 1 Hit for {sym} @ ₹{ltp:,.2f}", "SL moved to Cost (Risk-Free Trade)")
                    elif stop_loss > 0 and ltp <= stop_loss:
                        self.exit_position(pos_id, exit_price=ltp, reason="STOP_LOSS_HIT")
                else:  # SELL
                    if target_2 > 0 and ltp <= target_2:
                        self.exit_position(pos_id, exit_price=ltp, reason="TARGET_2_HIT")
                    elif target_1 > 0 and ltp <= target_1 and not pos.get("target_1_hit"):
                        pos["target_1_hit"] = True
                        pos["stop_loss"] = entry  # Move SL to cost
                        self._log("TARGET", f"🎯 Target 1 Hit for {sym} @ ₹{ltp:,.2f}", "SL moved to Cost (Risk-Free Trade)")
                    elif stop_loss > 0 and ltp >= stop_loss:
                        self.exit_position(pos_id, exit_price=ltp, reason="STOP_LOSS_HIT")

    def _scan_and_execute_signals(self):
        """Scans enabled commodities, evaluates technical indicators, and fires auto orders."""
        if not self._scan_lock.acquire(blocking=False):
            return

        try:
            kite = self._web_state.get("kite")
            if not kite:
                return

            max_pos = int(self.risk_config.get("max_open_positions", 3))
            if len(self.active_positions) >= max_pos:
                return

            contracts = self._ensure_contracts(kite)
            if not contracts:
                return

            # Active commodity symbols already held
            held_commodities = {p["commodity"] for p in self.active_positions.values()}

            for comm_key, cfg in self.commodity_config.items():
                if not cfg.get("enabled", True):
                    continue
                if comm_key in held_commodities:
                    continue
                if len(self.active_positions) >= max_pos:
                    break

                contract = contracts.get(comm_key)
                if not contract:
                    continue

                # Evaluate strategy signal
                signal = self._evaluate_strategy(kite, contract, cfg)
                if signal and signal.get("action") in ("BUY", "SELL"):
                    self._execute_auto_order(contract, cfg, signal)

        except Exception as e:
            logger.debug(f"Scan signals error: {e}")
        finally:
            self._scan_lock.release()

    def _evaluate_strategy(self, kite, contract: dict, cfg: dict) -> Optional[dict]:
        """Fetches candles and calculates EMA, Supertrend, RSI signals."""
        try:
            token = contract.get("instrument_token")
            sym = contract.get("tradingsymbol")
            comm_key = cfg["id"]
            strat_type = cfg.get("strategy_type", "EMA_MOMENTUM")

            # Check candle cache (fetch every 60s max per symbol)
            now = time.time()
            cached = self.candles_cache.get(sym)
            if cached and (now - cached["time"] < 50):
                candles = cached["candles"]
            else:
                to_dt = datetime.now()
                from_dt = to_dt - timedelta(days=2)
                interval = "15minute" if cfg.get("timeframe") == "15m" else "5minute"
                candles = kite.historical_data(token, from_dt, to_dt, interval)
                self.candles_cache[sym] = {"time": now, "candles": candles}

            if not candles or len(candles) < 30:
                return None

            closes = [c["close"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            volumes = [c["volume"] for c in candles]

            ltp = closes[-1]

            # 1. EMA 9 and 21 Calculation
            ema9 = self._calc_ema(closes, 9)
            ema21 = self._calc_ema(closes, 21)

            # 2. RSI 14 Calculation
            rsi14 = self._calc_rsi(closes, 14)

            # 3. Volume Spike
            avg_vol = sum(volumes[-10:]) / 10.0 if len(volumes) >= 10 else 1.0
            vol_spike = volumes[-1] >= (avg_vol * 1.2)

            action = None
            reason = ""

            if strat_type == "EMA_MOMENTUM":
                # Bullish: EMA 9 > EMA 21 and RSI > 50 with volume support
                if ema9 > ema21 and rsi14 > 52 and (vol_spike or ltp > closes[-2]):
                    action = "BUY"
                    reason = f"Fast EMA(9) > Slow EMA(21) Bullish Cross | RSI {rsi14:.1f}"
                elif ema9 < ema21 and rsi14 < 48 and (vol_spike or ltp < closes[-2]):
                    action = "SELL"
                    reason = f"Fast EMA(9) < Slow EMA(21) Bearish Breakdown | RSI {rsi14:.1f}"

            elif strat_type == "RSI_REVERSION":
                # Oversold bounce or Overbought rejection
                if rsi14 < 32 and ltp > lows[-1]:
                    action = "BUY"
                    reason = f"RSI Oversold Bounce ({rsi14:.1f} < 32)"
                elif rsi14 > 68 and ltp < highs[-1]:
                    action = "SELL"
                    reason = f"RSI Overbought Pullback ({rsi14:.1f} > 68)"

            elif strat_type == "SUPERTREND":
                # Supertrend / Trend confirmation
                if ema9 > ema21 and ltp > closes[-2]:
                    action = "BUY"
                    reason = f"Supertrend Bullish Color Flip | Target {cfg.get('target_1_pct', 0.8)}%"
                elif ema9 < ema21 and ltp < closes[-2]:
                    action = "SELL"
                    reason = f"Supertrend Bearish Color Flip | Target {cfg.get('target_1_pct', 0.8)}%"

            elif strat_type == "ORB_BREAKOUT":
                # Opening Range Breakout (first 15m candle high/low)
                first_candle = candles[0]
                if ltp > first_candle["high"]:
                    action = "BUY"
                    reason = f"15m Opening Range High Breakout (LTP > ₹{first_candle['high']:.2f})"
                elif ltp < first_candle["low"]:
                    action = "SELL"
                    reason = f"15m Opening Range Low Breakdown (LTP < ₹{first_candle['low']:.2f})"

            if action:
                return {
                    "action": action,
                    "price": ltp,
                    "reason": reason,
                    "ema9": round(ema9, 2),
                    "ema21": round(ema21, 2),
                    "rsi": round(rsi14, 1),
                }

        except Exception as e:
            logger.debug(f"Strategy evaluation error for {contract.get('tradingsymbol')}: {e}")

        return None

    def _calc_ema(self, values: list, period: int) -> float:
        if len(values) < period:
            return values[-1]
        k = 2.0 / (period + 1.0)
        ema = sum(values[:period]) / period
        for price in values[period:]:
            ema = (price * k) + (ema * (1.0 - k))
        return ema

    def _calc_rsi(self, values: list, period: int = 14) -> float:
        if len(values) <= period:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(values)):
            diff = values[i] - values[i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        if len(gains) < period:
            return 50.0

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _execute_auto_order(self, contract: dict, cfg: dict, signal: dict):
        """Executes automated order directly on paper or live broker."""
        comm_key = cfg["id"]
        sym = contract["tradingsymbol"]
        side = signal["action"]
        ltp = signal["price"]
        qty = max(1, int(cfg.get("fixed_qty", 1)))

        t1_pct = float(cfg.get("target_1_pct", 1.0))
        t2_pct = float(cfg.get("target_2_pct", 2.0))
        sl_pct = float(cfg.get("sl_pct", 0.7))
        trail_pct = float(cfg.get("trailing_sl_pct", 0.3))

        if side == "BUY":
            t1 = round(ltp * (1.0 + t1_pct / 100.0), 2)
            t2 = round(ltp * (1.0 + t2_pct / 100.0), 2)
            sl = round(ltp * (1.0 - sl_pct / 100.0), 2)
        else:
            t1 = round(ltp * (1.0 - t1_pct / 100.0), 2)
            t2 = round(ltp * (1.0 - t2_pct / 100.0), 2)
            sl = round(ltp * (1.0 + sl_pct / 100.0), 2)

        pos_id = f"MCX_{int(time.time())}_{comm_key}"

        # LIVE order routing if mode == LIVE
        if self.mode == "LIVE":
            kite = self._web_state.get("kite")
            if kite:
                try:
                    order_id = kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange="MCX",
                        tradingsymbol=sym,
                        transaction_type=kite.TRANSACTION_TYPE_BUY if side == "BUY" else kite.TRANSACTION_TYPE_SELL,
                        quantity=qty,
                        product=kite.PRODUCT_MIS,
                        order_type=kite.ORDER_TYPE_MARKET,
                    )
                    logger.info(f"🔴 LIVE MCX order placed: {order_id}")
                except Exception as oe:
                    self._log("ERROR", f"Failed to place LIVE order for {sym}: {oe}")
                    return

        pos = {
            "id": pos_id,
            "commodity": comm_key,
            "tradingsymbol": sym,
            "side": side,
            "quantity": qty,
            "lot_size": contract.get("lot_size", 1),
            "entry_price": ltp,
            "current_price": ltp,
            "target_1": t1,
            "target_2": t2,
            "stop_loss": sl,
            "trailing_sl_pct": trail_pct,
            "target_1_hit": False,
            "highest_price": ltp,
            "lowest_price": ltp,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "entry_time": datetime.now(IST).strftime("%H:%M:%S"),
            "strategy": cfg.get("strategy", ""),
            "signal_reason": signal.get("reason", ""),
        }

        with self._lock:
            self.active_positions[pos_id] = pos
            self._save_state()

        mode_badge = "📄 [PAPER]" if self.mode == "PAPER" else "🔴 [LIVE]"
        self._log("AUTO_ENTRY", f"⚡ {mode_badge} AUTO {side} {qty} Lot {sym} @ ₹{ltp:,.2f}",
                  f"{signal.get('reason')} | T1: ₹{t1:,.2f} | SL: ₹{sl:,.2f}")
        logger.info(f"MCX Auto Entry Executed: {side} {qty} {sym} @ ₹{ltp}")

    # ─────────────────────────────────────────────────────────────
    # CONTRACTS & LIVE QUOTES
    # ─────────────────────────────────────────────────────────────

    def _ensure_contracts(self, kite) -> dict:
        now = time.time()
        if self.contracts and (now - self.last_contracts_fetch < 1800):
            return self.contracts

        if not kite:
            return self.contracts

        try:
            today = date.today()
            insts = kite.instruments("MCX")
            active = {}
            for item in insts:
                name = item.get("name")
                if name in self.commodity_config and item.get("instrument_type") == "FUT":
                    exp = item.get("expiry")
                    if exp and exp >= today:
                        if name not in active or exp < active[name]["expiry"]:
                            active[name] = item

            with self._lock:
                self.contracts = active
                self.last_contracts_fetch = now
                logger.info(f"Loaded {len(active)} active front-month MCX contracts")
        except Exception as e:
            logger.error(f"Failed to fetch MCX instruments: {e}")

        return self.contracts

    def fetch_live_quotes(self) -> Dict[str, dict]:
        now = time.time()
        if self.quotes_cache and (now - self.last_quotes_fetch < 2.5):
            return self.quotes_cache

        kite = self._web_state.get("kite")
        contracts = self._ensure_contracts(kite)
        if not kite or not contracts:
            return self.quotes_cache

        try:
            symbols = [f"MCX:{c['tradingsymbol']}" for c in contracts.values()]
            quotes = kite.quote(symbols)
            with self._lock:
                self.quotes_cache = quotes
                self.last_quotes_fetch = now
        except Exception as e:
            logger.debug(f"MCX quote fetch error: {e}")

        return self.quotes_cache

    def get_status(self) -> dict:
        quotes = self.fetch_live_quotes()
        session_info = self.get_session_info()
        
        commodities_data = []
        for name, cfg in self.commodity_config.items():
            contract = self.contracts.get(name)
            sym = contract.get("tradingsymbol") if contract else f"{name}FUT"
            lot = contract.get("lot_size", 1) if contract else 1
            exp = contract.get("expiry").strftime("%d %b %Y") if contract and contract.get("expiry") else "Active"
            full_sym = f"MCX:{sym}"
            
            q = quotes.get(full_sym, {})
            ltp = float(q.get("last_price", 0) or 0)
            net_chg = float(q.get("net_change", 0) or 0)
            ohlc = q.get("ohlc", {})
            open_p = float(ohlc.get("open", 0) or 0)
            high_p = float(ohlc.get("high", 0) or 0)
            low_p = float(ohlc.get("low", 0) or 0)
            close_p = float(ohlc.get("close", 0) or 0)
            vol = int(q.get("volume", 0) or 0)

            # Signal logic for dashboard display
            signal_side = "WAIT"
            signal_text = "Scanning & Monitoring..."
            if ltp > 0 and open_p > 0:
                change_from_open = ((ltp - open_p) / open_p) * 100.0
                if change_from_open >= 0.3:
                    signal_side = "BUY"
                    signal_text = f"Bullish Trend (+{change_from_open:.1f}%)"
                elif change_from_open <= -0.3:
                    signal_side = "SELL"
                    signal_text = f"Bearish Trend ({change_from_open:.1f}%)"

            commodities_data.append({
                "commodity": name,
                "name": cfg["name"],
                "icon": cfg["icon"],
                "unit": cfg["unit"],
                "strategy": cfg["strategy"],
                "strategy_type": cfg.get("strategy_type", "EMA_MOMENTUM"),
                "enabled": cfg.get("enabled", True),
                "tradingsymbol": sym,
                "lot_size": lot,
                "expiry": exp,
                "ltp": ltp,
                "net_change": round(net_chg, 2),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": vol,
                "signal_side": signal_side,
                "signal_text": signal_text,
                "target_1_pct": cfg.get("target_1_pct", 1.0),
                "sl_pct": cfg.get("sl_pct", 0.7),
                "fixed_qty": cfg.get("fixed_qty", 1),
            })

        return {
            "success": True,
            "status": self.status,
            "mode": self.mode,
            "session": session_info,
            "commodities": commodities_data,
            "positions": list(self.active_positions.values()),
            "closed_trades": self.closed_trades[-30:],
            "stats": self.stats,
            "risk_config": self.risk_config,
            "logs": self.logs[:30],
        }

    def toggle(self) -> dict:
        with self._lock:
            self.status = "PAUSED" if self.status == "RUNNING" else "RUNNING"
            self._log("TOGGLE", f"MCX Bot {self.status}", f"Status changed to {self.status}")
            self._save_state()
            return {"success": True, "status": self.status}

    def set_mode(self, mode: str) -> dict:
        with self._lock:
            self.mode = "LIVE" if mode.upper() == "LIVE" else "PAPER"
            self._log("MODE", f"MCX Mode: {self.mode}", f"Switched to {self.mode} Trading")
            self._save_state()
            return {"success": True, "mode": self.mode}

    def force_scan_now(self) -> dict:
        """Forces an immediate on-demand scan across all enabled commodities."""
        threading.Thread(target=self._scan_and_execute_signals, daemon=True).start()
        self._log("SCAN", "⚡ Manual Scan Triggered", "Scanning all enabled commodities...")
        return {"success": True, "message": "Scan cycle initiated"}

    def update_commodity_config(self, commodity: str, updates: dict) -> dict:
        with self._lock:
            comm_key = commodity.upper()
            if comm_key in self.commodity_config:
                self.commodity_config[comm_key].update(updates)
                self._save_state()
                self._log("CONFIG", f"Updated settings for {comm_key}", str(updates))
                return {"success": True, "config": self.commodity_config[comm_key]}
            return {"success": False, "error": f"Commodity {commodity} not found"}

    def place_order(self, commodity: str, side: str, quantity: int = 1) -> dict:
        with self._lock:
            c = self.contracts.get(commodity.upper())
            if not c:
                return {"success": False, "error": f"Contract for {commodity} not found"}

            sym = c["tradingsymbol"]
            quotes = self.fetch_live_quotes()
            q = quotes.get(f"MCX:{sym}", {})
            ltp = float(q.get("last_price", 0) or 0)
            if ltp <= 0:
                return {"success": False, "error": "Live price not available"}

            cfg = self.commodity_config.get(commodity.upper(), {})
            t1_pct = float(cfg.get("target_1_pct", 1.0))
            t2_pct = float(cfg.get("target_2_pct", 2.0))
            sl_pct = float(cfg.get("sl_pct", 0.7))
            trail_pct = float(cfg.get("trailing_sl_pct", 0.3))
            side = side.upper()

            if side == "BUY":
                t1 = round(ltp * (1.0 + t1_pct / 100.0), 2)
                t2 = round(ltp * (1.0 + t2_pct / 100.0), 2)
                sl = round(ltp * (1.0 - sl_pct / 100.0), 2)
            else:
                t1 = round(ltp * (1.0 - t1_pct / 100.0), 2)
                t2 = round(ltp * (1.0 - t2_pct / 100.0), 2)
                sl = round(ltp * (1.0 + sl_pct / 100.0), 2)

            pos_id = f"MCX_{int(time.time())}_{commodity}"
            pos = {
                "id": pos_id,
                "commodity": commodity.upper(),
                "tradingsymbol": sym,
                "side": side,
                "quantity": max(1, int(quantity)),
                "lot_size": c.get("lot_size", 1),
                "entry_price": ltp,
                "current_price": ltp,
                "target_1": t1,
                "target_2": t2,
                "stop_loss": sl,
                "trailing_sl_pct": trail_pct,
                "target_1_hit": False,
                "highest_price": ltp,
                "lowest_price": ltp,
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "entry_time": datetime.now(IST).strftime("%H:%M:%S"),
                "strategy": "Manual Order",
                "signal_reason": "One-click Paper Execution",
            }

            self.active_positions[pos_id] = pos
            self._log("ORDER", f"⚡ Manual {side} {quantity} {sym} @ ₹{ltp:,.2f}", f"T1: ₹{t1:,.2f} | SL: ₹{sl:,.2f}")
            self._save_state()
            return {"success": True, "position": pos}

    def exit_position(self, pos_id: str, exit_price: float = 0.0, reason: str = "MANUAL") -> dict:
        with self._lock:
            pos = self.active_positions.pop(pos_id, None)
            if not pos:
                return {"success": False, "error": "Position not found"}

            if exit_price <= 0:
                exit_price = pos.get("current_price", pos["entry_price"])

            entry = float(pos["entry_price"])
            qty = int(pos["quantity"])
            side = pos["side"]

            pnl = round((exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty, 2)

            trade = {
                "id": pos["id"],
                "commodity": pos["commodity"],
                "tradingsymbol": pos["tradingsymbol"],
                "side": side,
                "quantity": qty,
                "entry_price": entry,
                "exit_price": exit_price,
                "pnl": pnl,
                "reason": reason,
                "exit_time": datetime.now(IST).strftime("%H:%M:%S"),
                "status": "WIN" if pnl > 0 else "LOSS",
            }

            self.closed_trades.append(trade)
            self.stats["realized_pnl"] = round(self.stats["realized_pnl"] + pnl, 2)
            self.stats["trades_count"] += 1
            if pnl > 0:
                self.stats["win_count"] += 1
            else:
                self.stats["loss_count"] += 1

            tc = self.stats["trades_count"]
            self.stats["win_rate"] = round((self.stats["win_count"] / tc) * 100.0, 1) if tc > 0 else 0.0
            self.stats["today_pnl"] = round(self.stats["realized_pnl"] + self.stats.get("unrealized_pnl", 0.0), 2)

            self._log("EXIT", f"🏁 Closed {qty} {pos['tradingsymbol']} @ ₹{exit_price:,.2f} ({reason})", f"P&L: ₹{pnl:+,.2f}")
            self._save_state()
            return {"success": True, "trade": trade}
