"""
strategies/swing.py - Swing Trading Strategy
EMA Crossover (20/50) + MACD + RSI + ADX Trend Filter

Logic:
  BUY  Signal: EMA20 > EMA50 crossover + MACD bullish crossover + RSI 40-60 + ADX > 25
  SELL Signal: EMA20 < EMA50 crossdown + MACD bearish crossover + RSI 40-60 + ADX > 25

Timeframe : Daily candles
Holding   : 3 to 15 days
Exit       : 5% SL / 10% Target / 3% Trailing SL
Product    : CNC (delivery - not intraday)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional

import pandas as pd
import numpy as np
import pytz

from config import SWING_CONFIG

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class SwingSignal(Enum):
    BUY         = "BUY"
    SELL_SHORT  = "SELL_SHORT"   # Short swing (advanced)
    HOLD        = "HOLD"
    EXIT_LONG   = "EXIT_LONG"
    EXIT_SHORT  = "EXIT_SHORT"
    WATCH       = "WATCH"        # Potential setup forming


@dataclass
class SwingTradeSignal:
    """Swing trade signal ki poori details"""
    symbol:       str
    signal:       SwingSignal
    price:        float
    stop_loss:    float
    target:       float
    quantity:     int    = 0
    # Indicator values
    ema_fast:     float  = 0.0
    ema_slow:     float  = 0.0
    macd:         float  = 0.0
    macd_signal:  float  = 0.0
    rsi:          float  = 0.0
    adx:          float  = 0.0
    volume_ratio: float  = 0.0
    # Score (kitni conditions meet hui)
    score:        int    = 0
    max_score:    int    = 5
    reason:       str    = ""
    timestamp:    datetime = field(default_factory=lambda: datetime.now(IST_tz))
    strategy:     str    = "SWING"
    # Position tracking
    entry_date:   Optional[date] = None
    days_held:    int    = 0

    @property
    def risk_pct(self) -> float:
        return abs(self.price - self.stop_loss) / self.price * 100

    @property
    def target_pct(self) -> float:
        return abs(self.target - self.price) / self.price * 100

    @property
    def rr_ratio(self) -> float:
        risk = abs(self.price - self.stop_loss)
        reward = abs(self.target - self.price)
        return reward / risk if risk > 0 else 0

    @property
    def conviction(self) -> str:
        """Signal kitna strong hai"""
        pct = self.score / self.max_score * 100
        if pct >= 80:
            return "HIGH 🔥"
        elif pct >= 60:
            return "MEDIUM ✅"
        else:
            return "LOW ⚠️"

    def __str__(self):
        return (
            f"[{self.signal.value}] {self.symbol} @ ₹{self.price:.2f} | "
            f"SL: ₹{self.stop_loss:.2f} ({self.risk_pct:.1f}%) | "
            f"Target: ₹{self.target:.2f} ({self.target_pct:.1f}%) | "
            f"R:R={self.rr_ratio:.1f} | Score={self.score}/{self.max_score} | "
            f"{self.reason}"
        )


class SwingStrategy:
    """
    Swing Trading Strategy: EMA + MACD + RSI + ADX + Volume
    
    Daily timeframe pe work karta hai.
    Signals end-of-day generate hote hain.
    """

    def __init__(self):
        self.cfg = SWING_CONFIG
        self.ind = self.cfg["indicators"]
        self.entry = self.cfg["entry_conditions"]
        self.exit_cfg = self.cfg["exit_conditions"]

        self.ema_fast_col = f"ema_{self.ind['ema_fast']}"
        self.ema_slow_col = f"ema_{self.ind['ema_slow']}"

        self._active_positions: dict[str, dict] = {}

    # ─────────────────────────────────────────────────────────
    # MAIN SIGNAL GENERATOR
    # ─────────────────────────────────────────────────────────

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SwingTradeSignal]:
        """
        Daily data se swing signal generate karo.
        """
        min_candles = max(self.ind["ema_slow"], self.ind["macd_slow"] + self.ind["macd_signal"]) + 10
        if df is None or len(df) < min_candles:
            logger.debug(f"{symbol}: Not enough data ({len(df) if df is not None else 0})")
            return None

        required = [
            self.ema_fast_col, self.ema_slow_col,
            "macd", "macd_signal", "macd_histogram",
            "rsi", "adx", "atr", "volume_ratio"
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning(f"{symbol}: Missing: {missing}")
            return None

        # Active position mein hai? Exit check karo
        if symbol in self._active_positions:
            return self._check_exit_signal(symbol, df)

        # Entry signal check karo
        return self._check_entry_signal(symbol, df)

    def _check_entry_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SwingTradeSignal]:
        """Swing entry signal check karo"""
        curr  = df.iloc[-1]
        prev1 = df.iloc[-2]
        prev2 = df.iloc[-3]

        price         = curr["close"]
        ema_fast      = curr[self.ema_fast_col]
        ema_slow      = curr[self.ema_slow_col]
        ema_fast_prev = prev1[self.ema_fast_col]
        ema_slow_prev = prev1[self.ema_slow_col]

        macd          = curr["macd"]
        macd_sig      = curr["macd_signal"]
        macd_prev     = prev1["macd"]
        macd_sig_prev = prev1["macd_signal"]

        rsi           = curr["rsi"]
        adx           = curr["adx"]
        atr           = curr["atr"]
        vol_ratio     = curr.get("volume_ratio", 1.0)

        # ── LONG SIGNAL ────────────────────────────────────
        long_score, long_reasons = self._score_long_entry(
            price, ema_fast, ema_slow, ema_fast_prev, ema_slow_prev,
            macd, macd_sig, macd_prev, macd_sig_prev,
            rsi, adx, vol_ratio
        )

        if long_score >= 3:  # Minimum 3/5 conditions chahiye
            sl     = price * (1 - self.exit_cfg["stop_loss_pct"] / 100)
            target = price * (1 + self.exit_cfg["target_pct"] / 100)
            # ATR-based SL bhi check karo (jo bhi zyada protective ho)
            atr_sl = price - (2 * atr) if not pd.isna(atr) else sl
            sl = max(sl, atr_sl)  # Closer stop loss

            signal = SwingTradeSignal(
                symbol=symbol,
                signal=SwingSignal.BUY,
                price=price,
                stop_loss=round(sl, 2),
                target=round(target, 2),
                ema_fast=round(ema_fast, 2),
                ema_slow=round(ema_slow, 2),
                macd=round(macd, 4),
                macd_signal=round(macd_sig, 4),
                rsi=round(rsi, 2),
                adx=round(adx, 2),
                volume_ratio=round(vol_ratio, 2),
                score=long_score,
                max_score=5,
                reason=" | ".join(long_reasons),
                entry_date=date.today(),
            )
            logger.info(f"📈 SWING BUY: {signal}")
            return signal

        # ── WATCH SIGNAL (almost ready) ────────────────────
        if long_score == 2:
            return SwingTradeSignal(
                symbol=symbol,
                signal=SwingSignal.WATCH,
                price=price,
                stop_loss=price * 0.95,
                target=price * 1.10,
                score=long_score,
                reason="Setup forming: " + " | ".join(long_reasons),
            )

        return None

    def _score_long_entry(
        self,
        price, ema_fast, ema_slow, ema_fast_prev, ema_slow_prev,
        macd, macd_sig, macd_prev, macd_sig_prev,
        rsi, adx, vol_ratio
    ) -> tuple[int, list]:
        """Long entry score calculate karo (0-5)"""
        score = 0
        reasons = []

        # ── Condition 1: EMA Crossover / Bullish Alignment ──
        if self.entry["ema_crossover"]:
            crossed_up = (ema_fast > ema_slow) and (ema_fast_prev <= ema_slow_prev)
            bullish    = ema_fast > ema_slow

            if crossed_up:
                score += 1
                reasons.append(f"EMA{self.ind['ema_fast']}/EMA{self.ind['ema_slow']} Crossover ↑")
            elif bullish:
                score += 0.5  # Partial score
                reasons.append(f"EMA Bullish ({ema_fast:.1f} > {ema_slow:.1f})")

        # ── Condition 2: MACD Crossover ──────────────────────
        if self.entry["macd_crossover"]:
            macd_crossed = (macd > macd_sig) and (macd_prev <= macd_sig_prev)
            macd_bullish = macd > macd_sig

            if macd_crossed:
                score += 1
                reasons.append("MACD Bullish Crossover ↑")
            elif macd_bullish and macd > 0:
                score += 0.5
                reasons.append(f"MACD Bullish ({macd:.3f})")

        # ── Condition 3: RSI Filter ───────────────────────────
        if self.entry["rsi_filter"]:
            rsi_ok = self.ind["rsi_oversold"] <= rsi <= self.ind["rsi_overbought"]
            rsi_rising = rsi > 50

            if rsi_ok and rsi_rising:
                score += 1
                reasons.append(f"RSI={rsi:.0f} (Healthy)")
            elif rsi_ok:
                score += 0.5
                reasons.append(f"RSI={rsi:.0f}")

        # ── Condition 4: ADX Trend Strength ───────────────────
        if self.entry["adx_filter"]:
            if adx >= self.ind["adx_threshold"]:
                score += 1
                reasons.append(f"ADX={adx:.0f} (Strong trend)")
            elif adx >= 20:
                score += 0.5
                reasons.append(f"ADX={adx:.0f} (Moderate)")

        # ── Condition 5: Volume Confirmation ──────────────────
        if self.entry["volume_confirm"]:
            if vol_ratio >= self.entry["volume_multiplier"]:
                score += 1
                reasons.append(f"Volume={vol_ratio:.1f}x ↑")
            elif vol_ratio >= 1.0:
                score += 0.5
                reasons.append(f"Volume={vol_ratio:.1f}x")

        return int(score), reasons

    def _check_exit_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SwingTradeSignal]:
        """Active swing position ke liye exit check karo"""
        pos = self._active_positions.get(symbol)
        if not pos:
            return None

        curr  = df.iloc[-1]
        prev1 = df.iloc[-2]
        price = curr["close"]

        ema_fast      = curr[self.ema_fast_col]
        ema_slow      = curr[self.ema_slow_col]
        ema_fast_prev = prev1[self.ema_fast_col]
        ema_slow_prev = prev1[self.ema_slow_col]
        rsi           = curr["rsi"]

        entry_price = pos["entry_price"]
        sl          = pos["stop_loss"]
        target      = pos["target"]
        days_held   = (date.today() - pos.get("entry_date", date.today())).days

        exit_signal = None
        reason = ""

        if pos["direction"] == "LONG":
            pnl_pct = (price - entry_price) / entry_price * 100

            # 1. Stop loss hit
            if price <= sl:
                exit_signal = SwingSignal.EXIT_LONG
                reason = f"Stop Loss hit (₹{price:.2f}) Loss: {pnl_pct:.1f}%"

            # 2. Target hit
            elif price >= target:
                exit_signal = SwingSignal.EXIT_LONG
                reason = f"Target achieved (₹{price:.2f}) Profit: {pnl_pct:.1f}% 🎯"

            # 3. EMA crossdown (trend reversal)
            elif self.exit_cfg["ema_crossdown"]:
                crossed_down = (ema_fast < ema_slow) and (ema_fast_prev >= ema_slow_prev)
                if crossed_down:
                    exit_signal = SwingSignal.EXIT_LONG
                    reason = f"EMA crossdown - trend reversal"

            # 4. Max holding days
            elif days_held >= self.cfg["holding_days"][1]:
                exit_signal = SwingSignal.EXIT_LONG
                reason = f"Max holding days ({days_held}) reached"

            # 5. Trailing stop loss update
            elif pnl_pct >= 5.0:  # 5% profit pe trailing start
                trail_sl = price * (1 - self.exit_cfg["trailing_stop_pct"] / 100)
                if trail_sl > sl:
                    pos["stop_loss"] = round(trail_sl, 2)
                    logger.info(f"📌 {symbol} Trailing SL: ₹{pos['stop_loss']:.2f} (+{pnl_pct:.1f}%)")

        if exit_signal:
            return SwingTradeSignal(
                symbol=symbol,
                signal=exit_signal,
                price=price,
                stop_loss=sl,
                target=target,
                days_held=days_held,
                reason=reason,
            )

        return None

    # ─────────────────────────────────────────────────────────
    # SWING SCANNER - Multiple symbols
    # ─────────────────────────────────────────────────────────

    def scan_all(self, symbols_data: dict[str, pd.DataFrame]) -> list[SwingTradeSignal]:
        """
        Saare symbols ko scan karo.
        Returns buy signals sorted by score (highest first).
        """
        buy_signals = []
        watch_list = []
        exit_signals = []

        for symbol, df in symbols_data.items():
            signal = self.generate_signal(symbol, df)
            if signal is None:
                continue

            if signal.signal == SwingSignal.BUY:
                buy_signals.append(signal)
            elif signal.signal == SwingSignal.WATCH:
                watch_list.append(signal)
            elif signal.signal in (SwingSignal.EXIT_LONG, SwingSignal.EXIT_SHORT):
                exit_signals.append(signal)

        # Score se sort karo (best signal pehle)
        buy_signals.sort(key=lambda x: x.score, reverse=True)

        all_signals = exit_signals + buy_signals + watch_list

        if buy_signals:
            logger.info(f"📊 Swing scan: {len(buy_signals)} BUY | {len(watch_list)} WATCH | {len(exit_signals)} EXIT")

        return all_signals

    def get_watchlist_analysis(self, symbols_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Saare symbols ka analysis table banao.
        Dashboard pe display ke liye.
        """
        rows = []
        for symbol, df in symbols_data.items():
            if df is None or df.empty or len(df) < 5:
                continue

            curr = df.iloc[-1]
            prev = df.iloc[-2]

            ema_fast = curr.get(self.ema_fast_col, 0)
            ema_slow = curr.get(self.ema_slow_col, 0)
            trend = "BULLISH ↑" if ema_fast > ema_slow else "BEARISH ↓"
            chg_pct = ((curr["close"] - prev["close"]) / prev["close"] * 100)

            rows.append({
                "Symbol":    symbol,
                "Price":     round(curr["close"], 2),
                "Chg%":      round(chg_pct, 2),
                "Trend":     trend,
                f"EMA{self.ind['ema_fast']}": round(ema_fast, 2),
                f"EMA{self.ind['ema_slow']}": round(ema_slow, 2),
                "RSI":       round(curr.get("rsi", 0), 1),
                "MACD":      round(curr.get("macd", 0), 3),
                "ADX":       round(curr.get("adx", 0), 1),
                "Vol Ratio": round(curr.get("volume_ratio", 0), 2),
                "Signal":    "ACTIVE" if symbol in self._active_positions else "-",
            })

        return pd.DataFrame(rows)

    # ─────────────────────────────────────────────────────────
    # POSITION MANAGEMENT
    # ─────────────────────────────────────────────────────────

    def register_trade(self, symbol: str, signal: SwingTradeSignal):
        """Trade register karo"""
        self._active_positions[symbol] = {
            "direction":   "LONG" if signal.signal == SwingSignal.BUY else "SHORT",
            "entry_price": signal.price,
            "stop_loss":   signal.stop_loss,
            "target":      signal.target,
            "entry_date":  date.today(),
            "quantity":    signal.quantity,
            "score":       signal.score,
        }
        logger.info(
            f"📝 Swing position registered: {symbol} @ ₹{signal.price:.2f} | "
            f"SL: ₹{signal.stop_loss:.2f} | Target: ₹{signal.target:.2f}"
        )

    def close_position(self, symbol: str):
        """Position close karo"""
        if symbol in self._active_positions:
            del self._active_positions[symbol]
            logger.info(f"✅ Swing position closed: {symbol}")

    def get_active_positions(self) -> dict:
        return self._active_positions.copy()

    def update_positions_pnl(self, ltp_data: dict) -> list[dict]:
        """Saari positions ki current P&L calculate karo"""
        result = []
        for symbol, pos in self._active_positions.items():
            ltp = ltp_data.get(symbol, pos["entry_price"])
            pnl = (ltp - pos["entry_price"]) * pos.get("quantity", 1)
            pnl_pct = (ltp - pos["entry_price"]) / pos["entry_price"] * 100
            days = (date.today() - pos.get("entry_date", date.today())).days

            result.append({
                "symbol":      symbol,
                "entry_price": pos["entry_price"],
                "ltp":         ltp,
                "quantity":    pos.get("quantity", 1),
                "pnl":         round(pnl, 2),
                "pnl_pct":     round(pnl_pct, 2),
                "days_held":   days,
                "stop_loss":   pos["stop_loss"],
                "target":      pos["target"],
            })
        return result

    def get_summary(self) -> str:
        active = len(self._active_positions)
        pos_str = "\n".join([
            f"  {s}: {p['direction']} @ ₹{p['entry_price']:.2f} | "
            f"SL: ₹{p['stop_loss']:.2f} | Days: {(date.today()-p.get('entry_date',date.today())).days}"
            for s, p in self._active_positions.items()
        ])
        return f"Swing Active Positions: {active}\n{pos_str}"
