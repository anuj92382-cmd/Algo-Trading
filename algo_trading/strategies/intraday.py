"""
strategies/intraday.py - Intraday Trading Strategy
EMA Crossover + RSI Filter + VWAP Confirmation

Logic:
  BUY  Signal: Fast EMA > Slow EMA (crossover) + RSI 40-65 + Price > VWAP + Volume spike
  SELL Signal: Fast EMA < Slow EMA (crossdown) + RSI 35-60 + Price < VWAP + Volume spike

Timeframe : 5-minute candles
Exit       : ATR-based Stop Loss + 2:1 Risk-Reward Target + Trailing SL
Cutoff     : No new entry after 2:30 PM, all positions close at 3:15 PM
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd
import numpy as np

from config import INTRADAY_CONFIG, IST
import pytz

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"   # Short sell
    HOLD = "HOLD"
    EXIT_LONG  = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"


@dataclass
class TradeSignal:
    """Ek trade signal ki poori information"""
    symbol:       str
    signal:       Signal
    price:        float
    stop_loss:    float
    target:       float
    quantity:     int    = 0
    atr:          float  = 0.0
    rsi:          float  = 0.0
    vwap:         float  = 0.0
    ema_fast:     float  = 0.0
    ema_slow:     float  = 0.0
    volume_ratio: float  = 0.0
    reason:       str    = ""
    timestamp:    datetime = field(default_factory=lambda: datetime.now(IST_tz))
    strategy:     str    = "INTRADAY"

    @property
    def risk(self) -> float:
        return abs(self.price - self.stop_loss)

    @property
    def reward(self) -> float:
        return abs(self.target - self.price)

    @property
    def rr_ratio(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0

    def __str__(self):
        return (
            f"[{self.signal.value}] {self.symbol} @ ₹{self.price:.2f} | "
            f"SL: ₹{self.stop_loss:.2f} | Target: ₹{self.target:.2f} | "
            f"R:R = 1:{self.rr_ratio:.1f} | {self.reason}"
        )


class IntradayStrategy:
    """
    Intraday Strategy: EMA + RSI + VWAP

    Har 5-minute candle close pe signals generate karta hai.
    """

    def __init__(self):
        self.cfg = INTRADAY_CONFIG
        self.ind = self.cfg["indicators"]
        self.entry = self.cfg["entry_conditions"]
        self.exit_cfg = self.cfg["exit_conditions"]

        self.ema_fast_col = f"ema_{self.ind['ema_fast']}"
        self.ema_slow_col = f"ema_{self.ind['ema_slow']}"

        # Active trades track karo
        self._active_positions: dict[str, dict] = {}

    # ─────────────────────────────────────────────────────────
    # MAIN SIGNAL GENERATOR
    # ─────────────────────────────────────────────────────────

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """
        DataFrame se signal generate karo.
        
        Args:
            symbol: Trading symbol e.g. "RELIANCE"
            df:     OHLCV + indicators DataFrame (already calculated)
            
        Returns:
            TradeSignal ya None
        """
        if df is None or len(df) < max(self.ind["ema_slow"], 30):
            logger.debug(f"{symbol}: Insufficient data ({len(df) if df is not None else 0} candles)")
            return None

        # Zaruri columns check karo
        required = [self.ema_fast_col, self.ema_slow_col, "rsi", "vwap", "atr", "volume_ratio"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning(f"{symbol}: Missing columns: {missing}")
            return None

        # Time check - entry allowed?
        if not self._is_entry_allowed():
            logger.debug(f"{symbol}: Entry cutoff reached")
            return None

        # Active position mein exit check karo
        if symbol in self._active_positions:
            return self._check_exit_signal(symbol, df)

        # Entry signal check karo
        return self._check_entry_signal(symbol, df)

    def _check_entry_signal(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """Entry conditions check karo"""
        # Last 3 candles lo
        curr  = df.iloc[-1]
        prev1 = df.iloc[-2]
        prev2 = df.iloc[-3]

        curr_price   = curr["close"]
        ema_fast_now = curr[self.ema_fast_col]
        ema_slow_now = curr[self.ema_slow_col]
        ema_fast_prev = prev1[self.ema_fast_col]
        ema_slow_prev = prev1[self.ema_slow_col]
        rsi          = curr["rsi"]
        vwap         = curr["vwap"]
        atr          = curr["atr"]
        vol_ratio    = curr.get("volume_ratio", 1.0)

        if pd.isna(atr) or atr <= 0:
            return None

        # ── LONG (BUY) SIGNAL ──────────────────────────────
        long_conditions = self._check_long_conditions(
            curr_price, ema_fast_now, ema_slow_now,
            ema_fast_prev, ema_slow_prev,
            rsi, vwap, vol_ratio
        )

        if long_conditions["all_met"]:
            sl     = curr_price - (self.exit_cfg["stop_loss_atr_multiplier"] * atr)
            target = curr_price + (self.exit_cfg["target_rr_ratio"] * abs(curr_price - sl))
            reason = " + ".join(long_conditions["reasons"])

            signal = TradeSignal(
                symbol=symbol,
                signal=Signal.BUY,
                price=curr_price,
                stop_loss=round(sl, 2),
                target=round(target, 2),
                atr=round(atr, 2),
                rsi=round(rsi, 2),
                vwap=round(vwap, 2),
                ema_fast=round(ema_fast_now, 2),
                ema_slow=round(ema_slow_now, 2),
                volume_ratio=round(vol_ratio, 2),
                reason=reason,
            )
            logger.info(f"📈 LONG signal: {signal}")
            return signal

        # ── SHORT (SELL) SIGNAL ────────────────────────────
        short_conditions = self._check_short_conditions(
            curr_price, ema_fast_now, ema_slow_now,
            ema_fast_prev, ema_slow_prev,
            rsi, vwap, vol_ratio
        )

        if short_conditions["all_met"]:
            sl     = curr_price + (self.exit_cfg["stop_loss_atr_multiplier"] * atr)
            target = curr_price - (self.exit_cfg["target_rr_ratio"] * abs(sl - curr_price))
            reason = " + ".join(short_conditions["reasons"])

            signal = TradeSignal(
                symbol=symbol,
                signal=Signal.SELL,
                price=curr_price,
                stop_loss=round(sl, 2),
                target=round(target, 2),
                atr=round(atr, 2),
                rsi=round(rsi, 2),
                vwap=round(vwap, 2),
                ema_fast=round(ema_fast_now, 2),
                ema_slow=round(ema_slow_now, 2),
                volume_ratio=round(vol_ratio, 2),
                reason=reason,
            )
            logger.info(f"📉 SHORT signal: {signal}")
            return signal

        return None

    def _check_long_conditions(
        self,
        price, ema_fast, ema_slow, ema_fast_prev, ema_slow_prev,
        rsi, vwap, vol_ratio
    ) -> dict:
        """Long entry ke liye saari conditions check karo"""
        reasons = []
        conditions = []

        # 1. EMA Crossover: Fast EMA ne Slow EMA ko upar cross kiya
        ema_crossed_up = (ema_fast > ema_slow) and (ema_fast_prev <= ema_slow_prev)
        ema_above = ema_fast > ema_slow  # Ya already above hai
        if self.entry["ema_crossover"]:
            # Crossover ya recent crossover (last 3 candles)
            if ema_crossed_up:
                conditions.append(True)
                reasons.append("EMA Crossover ↑")
            elif ema_above and (ema_fast - ema_slow) > 0:
                conditions.append(True)
                reasons.append("EMA Bullish")
            else:
                conditions.append(False)

        # 2. RSI Filter: 40-65 range (overbought avoid karo)
        if self.entry["rsi_confirm"]:
            rsi_ok = 40 <= rsi <= self.ind["rsi_overbought"]
            conditions.append(rsi_ok)
            if rsi_ok:
                reasons.append(f"RSI={rsi:.0f} ✓")

        # 3. VWAP: Price VWAP se upar ho
        if self.entry["vwap_filter"]:
            above_vwap = price > vwap
            conditions.append(above_vwap)
            if above_vwap:
                reasons.append("Price > VWAP")

        # 4. Volume: Average se zyada volume
        vol_ok = vol_ratio >= self.entry["volume_multiplier"]
        conditions.append(vol_ok)
        if vol_ok:
            reasons.append(f"Vol={vol_ratio:.1f}x ↑")

        return {
            "all_met": all(conditions) and len(conditions) >= 3,
            "reasons": reasons,
            "count": sum(conditions),
        }

    def _check_short_conditions(
        self,
        price, ema_fast, ema_slow, ema_fast_prev, ema_slow_prev,
        rsi, vwap, vol_ratio
    ) -> dict:
        """Short entry ke liye saari conditions check karo"""
        reasons = []
        conditions = []

        # 1. EMA Crossdown: Fast EMA ne Slow EMA ko niche cross kiya
        ema_crossed_down = (ema_fast < ema_slow) and (ema_fast_prev >= ema_slow_prev)
        ema_below = ema_fast < ema_slow
        if self.entry["ema_crossover"]:
            if ema_crossed_down:
                conditions.append(True)
                reasons.append("EMA Crossdown ↓")
            elif ema_below:
                conditions.append(True)
                reasons.append("EMA Bearish")
            else:
                conditions.append(False)

        # 2. RSI: 35-60 range
        if self.entry["rsi_confirm"]:
            rsi_ok = self.ind["rsi_oversold"] <= rsi <= 60
            conditions.append(rsi_ok)
            if rsi_ok:
                reasons.append(f"RSI={rsi:.0f} ✓")

        # 3. VWAP: Price VWAP se niche ho
        if self.entry["vwap_filter"]:
            below_vwap = price < vwap
            conditions.append(below_vwap)
            if below_vwap:
                reasons.append("Price < VWAP")

        # 4. Volume spike
        vol_ok = vol_ratio >= self.entry["volume_multiplier"]
        conditions.append(vol_ok)
        if vol_ok:
            reasons.append(f"Vol={vol_ratio:.1f}x ↑")

        return {
            "all_met": all(conditions) and len(conditions) >= 3,
            "reasons": reasons,
            "count": sum(conditions),
        }

    def _check_exit_signal(self, symbol: str, df: pd.DataFrame) -> Optional[TradeSignal]:
        """Active position ke liye exit check karo"""
        pos = self._active_positions.get(symbol)
        if not pos:
            return None

        curr = df.iloc[-1]
        curr_price = curr["close"]
        atr = curr.get("atr", 0)
        ema_fast = curr[self.ema_fast_col]
        ema_slow = curr[self.ema_slow_col]

        exit_signal = None
        reason = ""

        if pos["direction"] == "LONG":
            # Stop loss hit?
            if curr_price <= pos["stop_loss"]:
                exit_signal = Signal.EXIT_LONG
                reason = f"Stop Loss hit @ ₹{curr_price:.2f}"

            # Target hit?
            elif curr_price >= pos["target"]:
                exit_signal = Signal.EXIT_LONG
                reason = f"Target hit @ ₹{curr_price:.2f} 🎯"

            # EMA reversal?
            elif ema_fast < ema_slow:
                exit_signal = Signal.EXIT_LONG
                reason = "EMA bearish reversal"

            # Trailing SL update
            elif self.exit_cfg["trailing_stop"] and atr > 0:
                new_sl = curr_price - (self.exit_cfg["trailing_atr_multiplier"] * atr)
                if new_sl > pos["stop_loss"]:
                    pos["stop_loss"] = round(new_sl, 2)
                    logger.info(f"📌 {symbol} Trailing SL updated: ₹{pos['stop_loss']:.2f}")

        elif pos["direction"] == "SHORT":
            if curr_price >= pos["stop_loss"]:
                exit_signal = Signal.EXIT_SHORT
                reason = f"Stop Loss hit @ ₹{curr_price:.2f}"
            elif curr_price <= pos["target"]:
                exit_signal = Signal.EXIT_SHORT
                reason = f"Target hit @ ₹{curr_price:.2f} 🎯"
            elif ema_fast > ema_slow:
                exit_signal = Signal.EXIT_SHORT
                reason = "EMA bullish reversal"

        if exit_signal:
            return TradeSignal(
                symbol=symbol,
                signal=exit_signal,
                price=curr_price,
                stop_loss=pos["stop_loss"],
                target=pos["target"],
                reason=reason,
            )

        return None

    def force_exit_all(self, df_map: dict[str, pd.DataFrame]) -> list[TradeSignal]:
        """
        3:15 PM pe saari positions force close karo.
        """
        signals = []
        for symbol, pos in list(self._active_positions.items()):
            df = df_map.get(symbol)
            price = df.iloc[-1]["close"] if df is not None and not df.empty else pos["entry_price"]

            sig = Signal.EXIT_LONG if pos["direction"] == "LONG" else Signal.EXIT_SHORT
            signals.append(TradeSignal(
                symbol=symbol,
                signal=sig,
                price=price,
                stop_loss=pos["stop_loss"],
                target=pos["target"],
                reason="Market closing - force exit 3:15 PM",
            ))
            logger.info(f"⏰ Force exit: {symbol}")
        return signals

    # ─────────────────────────────────────────────────────────
    # POSITION TRACKING
    # ─────────────────────────────────────────────────────────

    def register_trade(self, symbol: str, signal: TradeSignal):
        """Trade place hone ke baad register karo"""
        direction = "LONG" if signal.signal == Signal.BUY else "SHORT"
        self._active_positions[symbol] = {
            "direction":   direction,
            "entry_price": signal.price,
            "stop_loss":   signal.stop_loss,
            "target":      signal.target,
            "entry_time":  signal.timestamp,
            "quantity":    signal.quantity,
        }
        logger.info(f"📝 Position registered: {symbol} {direction} @ ₹{signal.price:.2f}")

    def close_position(self, symbol: str):
        """Position band karo"""
        if symbol in self._active_positions:
            del self._active_positions[symbol]
            logger.info(f"✅ Position closed: {symbol}")

    def get_active_positions(self) -> dict:
        return self._active_positions.copy()

    # ─────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────

    def _is_entry_allowed(self) -> bool:
        """Entry allowed hai? (2:30 PM ke baad nahi)"""
        from config import INTRADAY_ENTRY_CUTOFF
        now = datetime.now(IST_tz).time()
        return now < INTRADAY_ENTRY_CUTOFF

    def scan_all(
        self, symbols_data: dict[str, pd.DataFrame]
    ) -> list[TradeSignal]:
        """
        Saare symbols scan karo aur valid signals return karo.
        
        Args:
            symbols_data: {symbol: DataFrame with indicators}
        Returns:
            List of TradeSignals
        """
        signals = []
        for symbol, df in symbols_data.items():
            signal = self.generate_signal(symbol, df)
            if signal and signal.signal != Signal.HOLD:
                signals.append(signal)

        if signals:
            logger.info(f"🔍 Intraday scan: {len(signals)} signals from {len(symbols_data)} symbols")
        return signals

    def get_summary(self) -> str:
        """Current status summary"""
        active = len(self._active_positions)
        pos_str = "\n".join([
            f"  {s}: {p['direction']} @ ₹{p['entry_price']:.2f} | SL: ₹{p['stop_loss']:.2f}"
            for s, p in self._active_positions.items()
        ])
        return f"Intraday Active Positions: {active}\n{pos_str}"
