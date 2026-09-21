"""
scanner.py - Stock Scanner Engine
Multi-indicator analysis: RSI + SuperTrend + VWAP + MACD + EMA + Bollinger + ADX + Volume
Sirf strong trade setups recommend karta hai with Entry, SL, Target
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math

import pandas as pd
import numpy as np
import pytz

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


# ─────────────────────────────────────────────────────────────
# SIGNAL DATACLASS
# ─────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    """Ek stock ka complete analysis result"""
    symbol:        str
    name:          str
    direction:     str        # "LONG" or "SHORT"
    signal_type:   str        # "STRONG BUY", "BUY", "STRONG SELL", "SELL"

    # Price levels
    ltp:           float
    entry:         float
    stop_loss:     float
    target1:       float      # 1:1.5 R:R
    target2:       float      # 1:2   R:R
    target3:       float      # 1:3   R:R

    # Risk metrics
    risk_pct:      float      # SL distance %
    rr_ratio:      float      # Best achievable R:R
    score:         int        # Total score (max 10)
    confidence:    str        # HIGH / MEDIUM

    # Indicator values
    rsi:           float = 0.0
    macd:          float = 0.0
    macd_signal:   float = 0.0
    macd_hist:     float = 0.0
    ema_fast:      float = 0.0
    ema_slow:      float = 0.0
    vwap:          float = 0.0
    supertrend:    float = 0.0
    supertrend_bull: bool = True
    adx:           float = 0.0
    bb_upper:      float = 0.0
    bb_lower:      float = 0.0
    atr:           float = 0.0
    volume_ratio:  float = 0.0

    # Reasons
    reasons:       list  = field(default_factory=list)
    warnings:      list  = field(default_factory=list)

    # Timeframe
    timeframe:     str   = "day"
    timestamp:     datetime = field(default_factory=lambda: datetime.now(IST_tz))

    @property
    def risk_amount(self) -> float:
        return abs(self.entry - self.stop_loss)

    @property
    def reward1(self) -> float:
        return abs(self.target1 - self.entry)

    @property
    def best_rr(self) -> str:
        """Best R:R ratio string"""
        r = self.rr_ratio
        if r >= 3:   return "1:3+"
        elif r >= 2: return "1:2"
        elif r >= 1.5: return "1:1.5"
        else:        return f"1:{r:.1f}"

    def to_dict(self) -> dict:
        return {
            "symbol":         self.symbol,
            "name":           self.name,
            "direction":      self.direction,
            "signal_type":    self.signal_type,
            "ltp":            round(self.ltp, 2),
            "entry":          round(self.entry, 2),
            "stop_loss":      round(self.stop_loss, 2),
            "target1":        round(self.target1, 2),
            "target2":        round(self.target2, 2),
            "target3":        round(self.target3, 2),
            "risk_pct":       round(self.risk_pct, 2),
            "rr_ratio":       round(self.rr_ratio, 2),
            "best_rr":        self.best_rr,
            "score":          self.score,
            "confidence":     self.confidence,
            "rsi":            round(self.rsi, 1),
            "macd":           round(self.macd, 4),
            "macd_signal":    round(self.macd_signal, 4),
            "macd_hist":      round(self.macd_hist, 4),
            "ema_fast":       round(self.ema_fast, 2),
            "ema_slow":       round(self.ema_slow, 2),
            "vwap":           round(self.vwap, 2),
            "supertrend":     round(self.supertrend, 2),
            "supertrend_bull": self.supertrend_bull,
            "adx":            round(self.adx, 1),
            "atr":            round(self.atr, 2),
            "volume_ratio":   round(self.volume_ratio, 2),
            "reasons":        self.reasons,
            "warnings":       self.warnings,
            "timeframe":      self.timeframe,
            "timestamp":      self.timestamp.strftime("%H:%M:%S"),
        }


# ─────────────────────────────────────────────────────────────
# INDICATOR CALCULATIONS
# ─────────────────────────────────────────────────────────────

class Indicators:
    """Pure indicator calculations - no Kite dependency"""

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta    = series.diff()
        gain     = delta.clip(lower=0)
        loss     = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
        rs       = avg_gain / avg_loss.replace(0, np.nan)
        rsi      = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def macd(series: pd.Series, fast=12, slow=26, signal=9):
        ema_f  = series.ewm(span=fast,   adjust=False).mean()
        ema_s  = series.ewm(span=slow,   adjust=False).mean()
        macd_  = ema_f - ema_s
        sig_   = macd_.ewm(span=signal,  adjust=False).mean()
        hist   = macd_ - sig_
        return macd_, sig_, hist

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l, pc = df["high"], df["low"], df["close"].shift(1)
        tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
        return tr.ewm(com=period-1, min_periods=period).mean()

    @staticmethod
    def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
        atr_   = Indicators.atr(df, period)
        hl2    = (df["high"] + df["low"]) / 2
        upper  = hl2 + multiplier * atr_
        lower  = hl2 - multiplier * atr_

        st      = [0.0] * len(df)
        is_bull = [True] * len(df)
        close   = df["close"].values

        for i in range(1, len(df)):
            # Upper band
            u = upper.iloc[i]
            if u < upper.iloc[i-1] or close[i-1] > upper.iloc[i-1]:
                pass
            else:
                u = upper.iloc[i-1]

            # Lower band
            l = lower.iloc[i]
            if l > lower.iloc[i-1] or close[i-1] < lower.iloc[i-1]:
                pass
            else:
                l = lower.iloc[i-1]

            # Direction
            if st[i-1] == upper.iloc[i-1]:
                st[i]      = l if close[i] > u else u
                is_bull[i] = close[i] > u
            else:
                st[i]      = u if close[i] < l else l
                is_bull[i] = close[i] > l

        return pd.Series(st, index=df.index), pd.Series(is_bull, index=df.index)

    @staticmethod
    def bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
        sma    = series.rolling(period).mean()
        stddev = series.rolling(period).std()
        return sma + std*stddev, sma, sma - std*stddev

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        plus_dm  = h.diff().clip(lower=0)
        minus_dm = l.diff().abs().clip(lower=0)

        # Zero out when other is larger
        plus_dm  = plus_dm.where(plus_dm > minus_dm, 0)
        minus_dm = minus_dm.where(minus_dm > plus_dm, 0)

        tr_  = Indicators.atr(df, period)
        plus_di  = 100 * plus_dm.ewm(com=period-1).mean()  / tr_.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(com=period-1).mean() / tr_.replace(0, np.nan)
        dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        return dx.ewm(com=period-1, min_periods=period).mean().fillna(0)

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        tp      = (df["high"] + df["low"] + df["close"]) / 3
        cum_tv  = (tp * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        return (cum_tv / cum_vol.replace(0, np.nan)).fillna(df["close"])

    @staticmethod
    def volume_ma(series: pd.Series, period: int = 20) -> pd.Series:
        return series.rolling(period).mean()


# ─────────────────────────────────────────────────────────────
# SCANNER ENGINE
# ─────────────────────────────────────────────────────────────

class StockScanner:
    """
    Multi-indicator stock scanner.
    Sirf high-confidence trade setups return karta hai.

    Scoring system (max 10 points):
      EMA alignment        : 2 pts
      RSI zone             : 2 pts
      MACD crossover       : 2 pts
      SuperTrend direction : 1 pt
      ADX strength         : 1 pt
      Volume confirmation  : 1 pt
      VWAP position        : 1 pt

    MIN_SCORE = 6 → trade recommendation
    """

    # ── Config ──────────────────────────────────────────────
    EMA_FAST     = 9
    EMA_SLOW     = 21
    EMA_TREND    = 50
    RSI_PERIOD   = 14
    RSI_OS       = 35    # Oversold
    RSI_OB       = 65    # Overbought
    RSI_BULL_LO  = 40    # RSI in bullish zone lower
    RSI_BULL_HI  = 70
    RSI_BEAR_LO  = 30
    RSI_BEAR_HI  = 60
    MACD_FAST    = 12
    MACD_SLOW    = 26
    MACD_SIG     = 9
    ST_PERIOD    = 10
    ST_MULT      = 3.0
    ADX_PERIOD   = 14
    ADX_THRESH   = 25    # Strong trend threshold
    ATR_PERIOD   = 14
    VOL_MA       = 20
    VOL_MULT     = 1.3   # Volume spike threshold
    BB_PERIOD    = 20
    BB_STD       = 2.0
    MIN_SCORE    = 6     # Minimum score for recommendation
    MIN_CANDLES  = 60    # Minimum candles needed
    MIN_RR       = 1.5   # Minimum risk:reward ratio

    def analyse(self, symbol: str, name: str, df: pd.DataFrame,
                timeframe: str = "day") -> Optional[ScanResult]:
        """
        Ek stock ka complete analysis karo.
        Returns ScanResult agar strong signal mila, else None.
        """
        if df is None or len(df) < self.MIN_CANDLES:
            return None

        df = df.copy().reset_index(drop=True)

        # ── Calculate all indicators ──────────────────────
        try:
            close  = df["close"]
            high   = df["high"]
            low    = df["low"]
            volume = df["volume"]

            ema9   = Indicators.ema(close, self.EMA_FAST)
            ema21  = Indicators.ema(close, self.EMA_SLOW)
            ema50  = Indicators.ema(close, self.EMA_TREND)
            rsi    = Indicators.rsi(close, self.RSI_PERIOD)
            macd_, macd_sig_, macd_hist_ = Indicators.macd(close,
                                            self.MACD_FAST, self.MACD_SLOW, self.MACD_SIG)
            atr_   = Indicators.atr(df, self.ATR_PERIOD)
            st_, st_bull_ = Indicators.supertrend(df, self.ST_PERIOD, self.ST_MULT)
            adx_   = Indicators.adx(df, self.ADX_PERIOD)
            bb_up, bb_mid, bb_lo = Indicators.bollinger(close, self.BB_PERIOD, self.BB_STD)
            vwap_  = Indicators.vwap(df)
            vol_ma = Indicators.volume_ma(volume, self.VOL_MA)

        except Exception as e:
            logger.debug(f"{symbol} indicator error: {e}")
            return None

        # ── Latest values ─────────────────────────────────
        c  = close.iloc[-1]
        c1 = close.iloc[-2]   # Previous candle

        v  = {
            "ema9":        ema9.iloc[-1],
            "ema9_p":      ema9.iloc[-2],
            "ema21":       ema21.iloc[-1],
            "ema21_p":     ema21.iloc[-2],
            "ema50":       ema50.iloc[-1],
            "rsi":         rsi.iloc[-1],
            "rsi_p":       rsi.iloc[-2],
            "macd":        macd_.iloc[-1],
            "macd_p":      macd_.iloc[-2],
            "macd_sig":    macd_sig_.iloc[-1],
            "macd_sig_p":  macd_sig_.iloc[-2],
            "macd_hist":   macd_hist_.iloc[-1],
            "macd_hist_p": macd_hist_.iloc[-2],
            "atr":         atr_.iloc[-1],
            "st":          st_.iloc[-1],
            "st_bull":     st_bull_.iloc[-1],
            "st_bull_p":   st_bull_.iloc[-2],
            "adx":         adx_.iloc[-1],
            "bb_up":       bb_up.iloc[-1],
            "bb_lo":       bb_lo.iloc[-1],
            "bb_mid":      bb_mid.iloc[-1],
            "vwap":        vwap_.iloc[-1],
            "vol":         volume.iloc[-1],
            "vol_ma":      vol_ma.iloc[-1] if not pd.isna(vol_ma.iloc[-1]) else volume.mean(),
        }

        # Safety check
        if any(pd.isna(val) or (isinstance(val, float) and math.isinf(val))
               for val in [v["atr"], v["ema9"], v["ema21"], v["rsi"]]):
            return None
        if v["atr"] <= 0 or c <= 0:
            return None

        # ── LONG analysis ─────────────────────────────────
        long_score, long_reasons, long_warns = self._score_long(c, c1, v)

        # ── SHORT analysis ────────────────────────────────
        short_score, short_reasons, short_warns = self._score_short(c, c1, v)

        # ── Decide direction ──────────────────────────────
        direction = None
        score     = 0
        reasons   = []
        warnings  = []

        if long_score >= self.MIN_SCORE and long_score >= short_score:
            direction = "LONG"
            score     = long_score
            reasons   = long_reasons
            warnings  = long_warns
        elif short_score >= self.MIN_SCORE:
            direction = "SHORT"
            score     = short_score
            reasons   = short_reasons
            warnings  = short_warns

        if not direction:
            return None   # No strong signal

        # ── Calculate trade levels ────────────────────────
        atr = v["atr"]

        if direction == "LONG":
            entry     = round(c, 2)
            stop_loss = round(c - 1.5 * atr, 2)

            # Extra protection: SL below recent low
            recent_low = low.iloc[-5:].min()
            stop_loss  = round(min(stop_loss, recent_low - 0.5 * atr), 2)

            risk       = entry - stop_loss
            if risk <= 0:
                return None

            signal_type = "STRONG BUY" if score >= 8 else "BUY"

        else:  # SHORT
            entry     = round(c, 2)
            stop_loss = round(c + 1.5 * atr, 2)

            recent_high = high.iloc[-5:].max()
            stop_loss   = round(max(stop_loss, recent_high + 0.5 * atr), 2)

            risk        = stop_loss - entry
            if risk <= 0:
                return None

            signal_type = "STRONG SELL" if score >= 8 else "SELL"

        # ── Targets (1:1.5, 1:2, 1:3) ────────────────────
        if direction == "LONG":
            t1 = round(entry + 1.5 * risk, 2)
            t2 = round(entry + 2.0 * risk, 2)
            t3 = round(entry + 3.0 * risk, 2)
        else:
            t1 = round(entry - 1.5 * risk, 2)
            t2 = round(entry - 2.0 * risk, 2)
            t3 = round(entry - 3.0 * risk, 2)

        # ── R:R check ─────────────────────────────────────
        best_rr = 3.0  # We always offer 1:3 target
        if best_rr < self.MIN_RR:
            return None

        risk_pct = round(risk / entry * 100, 2)

        # ── Confidence level ──────────────────────────────
        confidence = "HIGH 🔥" if score >= 8 else "MEDIUM ✅"

        return ScanResult(
            symbol=symbol, name=name,
            direction=direction, signal_type=signal_type,
            ltp=c, entry=entry, stop_loss=stop_loss,
            target1=t1, target2=t2, target3=t3,
            risk_pct=risk_pct, rr_ratio=best_rr,
            score=score, confidence=confidence,
            rsi=v["rsi"], macd=v["macd"],
            macd_signal=v["macd_sig"], macd_hist=v["macd_hist"],
            ema_fast=v["ema9"], ema_slow=v["ema21"],
            vwap=v["vwap"], supertrend=v["st"],
            supertrend_bull=bool(v["st_bull"]),
            adx=v["adx"], atr=atr,
            bb_upper=v["bb_up"], bb_lower=v["bb_lo"],
            volume_ratio=round(v["vol"] / max(v["vol_ma"], 1), 2),
            reasons=reasons, warnings=warnings,
            timeframe=timeframe,
        )

    # ─────────────────────────────────────────────────────────
    # SCORING - LONG
    # ─────────────────────────────────────────────────────────

    def _score_long(self, c, c1, v) -> tuple:
        score   = 0
        reasons = []
        warns   = []

        # ── 1. EMA Alignment (max 2 pts) ──────────────────
        # Crossover: 2 pts | Just above: 1 pt
        ema_cross = v["ema9"] > v["ema21"] and v["ema9_p"] <= v["ema21_p"]
        ema_above = v["ema9"] > v["ema21"]
        trend_ok  = c > v["ema50"]

        if ema_cross and trend_ok:
            score += 2
            reasons.append("✅ EMA 9/21 Bullish Crossover + Price > EMA50")
        elif ema_above and trend_ok:
            score += 1.5
            reasons.append("✅ EMA Bullish (9>21) + Price > EMA50")
        elif ema_above:
            score += 1
            reasons.append("⚡ EMA 9 > EMA 21 (bullish)")
        else:
            warns.append("⚠️ EMA bearish alignment")

        # ── 2. RSI Zone (max 2 pts) ────────────────────────
        rsi = v["rsi"]
        rsi_rising = v["rsi"] > v["rsi_p"]
        if 45 <= rsi <= 65 and rsi_rising:
            score += 2
            reasons.append(f"✅ RSI={rsi:.0f} (Bullish zone, rising)")
        elif 35 <= rsi < 45 and rsi_rising:
            score += 1.5
            reasons.append(f"✅ RSI={rsi:.0f} (Oversold recovery)")
        elif 40 <= rsi <= 70:
            score += 1
            reasons.append(f"⚡ RSI={rsi:.0f} (acceptable)")
        elif rsi > 70:
            warns.append(f"⚠️ RSI={rsi:.0f} Overbought - risky entry")
        else:
            warns.append(f"⚠️ RSI={rsi:.0f} too low/weak")

        # ── 3. MACD (max 2 pts) ───────────────────────────
        macd_cross = (v["macd"] > v["macd_sig"] and
                      v["macd_p"] <= v["macd_sig_p"])
        macd_bull  = v["macd"] > v["macd_sig"]
        hist_up    = v["macd_hist"] > v["macd_hist_p"]  # histogram growing

        if macd_cross and v["macd"] > 0:
            score += 2
            reasons.append("✅ MACD Bullish Crossover (above zero)")
        elif macd_cross:
            score += 1.5
            reasons.append("✅ MACD Bullish Crossover")
        elif macd_bull and hist_up:
            score += 1
            reasons.append(f"⚡ MACD Bullish momentum (hist growing)")
        elif macd_bull:
            score += 0.5
            reasons.append(f"⚡ MACD above signal line")
        else:
            warns.append("⚠️ MACD bearish")

        # ── 4. SuperTrend (max 1 pt) ──────────────────────
        st_flip = v["st_bull"] and not v["st_bull_p"]  # Just flipped bullish
        if st_flip:
            score += 1
            reasons.append(f"✅ SuperTrend just turned BULLISH 🔄")
        elif v["st_bull"]:
            score += 0.5
            reasons.append(f"⚡ SuperTrend Bullish (price > ₹{v['st']:.2f})")
        else:
            warns.append(f"⚠️ SuperTrend Bearish")

        # ── 5. ADX Trend Strength (max 1 pt) ──────────────
        adx = v["adx"]
        if adx >= 30:
            score += 1
            reasons.append(f"✅ ADX={adx:.0f} Strong trend")
        elif adx >= self.ADX_THRESH:
            score += 0.5
            reasons.append(f"⚡ ADX={adx:.0f} Moderate trend")
        else:
            warns.append(f"⚠️ ADX={adx:.0f} Weak trend")

        # ── 6. Volume Confirmation (max 1 pt) ─────────────
        vol_ratio = v["vol"] / max(v["vol_ma"], 1)
        if vol_ratio >= 2.0:
            score += 1
            reasons.append(f"✅ Volume spike {vol_ratio:.1f}x (strong)")
        elif vol_ratio >= self.VOL_MULT:
            score += 0.5
            reasons.append(f"⚡ Volume {vol_ratio:.1f}x above avg")
        else:
            warns.append(f"⚠️ Low volume ({vol_ratio:.1f}x)")

        # ── 7. VWAP Position (max 1 pt) ───────────────────
        if c > v["vwap"] * 1.001:
            score += 1
            reasons.append(f"✅ Price above VWAP (₹{v['vwap']:.2f})")
        elif c > v["vwap"]:
            score += 0.5
            reasons.append(f"⚡ Price near VWAP (₹{v['vwap']:.2f})")
        else:
            warns.append(f"⚠️ Price below VWAP")

        return int(score), reasons, warns

    # ─────────────────────────────────────────────────────────
    # SCORING - SHORT
    # ─────────────────────────────────────────────────────────

    def _score_short(self, c, c1, v) -> tuple:
        score   = 0
        reasons = []
        warns   = []

        # ── 1. EMA Alignment (max 2 pts) ──────────────────
        ema_cross_down = v["ema9"] < v["ema21"] and v["ema9_p"] >= v["ema21_p"]
        ema_below      = v["ema9"] < v["ema21"]
        trend_down     = c < v["ema50"]

        if ema_cross_down and trend_down:
            score += 2
            reasons.append("✅ EMA 9/21 Bearish Crossover + Price < EMA50")
        elif ema_below and trend_down:
            score += 1.5
            reasons.append("✅ EMA Bearish (9<21) + Price < EMA50")
        elif ema_below:
            score += 1
            reasons.append("⚡ EMA 9 < EMA 21 (bearish)")
        else:
            warns.append("⚠️ EMA bullish - weak short setup")

        # ── 2. RSI Zone (max 2 pts) ────────────────────────
        rsi = v["rsi"]
        rsi_falling = v["rsi"] < v["rsi_p"]
        if 35 <= rsi <= 55 and rsi_falling:
            score += 2
            reasons.append(f"✅ RSI={rsi:.0f} (Bearish zone, falling)")
        elif 55 < rsi <= 70 and rsi_falling:
            score += 1.5
            reasons.append(f"✅ RSI={rsi:.0f} (Overbought pullback)")
        elif 30 <= rsi <= 60:
            score += 1
            reasons.append(f"⚡ RSI={rsi:.0f} (acceptable)")
        elif rsi < 30:
            warns.append(f"⚠️ RSI={rsi:.0f} Oversold - risky short")
        else:
            warns.append(f"⚠️ RSI={rsi:.0f} weak for short")

        # ── 3. MACD (max 2 pts) ───────────────────────────
        macd_cross_dn = (v["macd"] < v["macd_sig"] and
                         v["macd_p"] >= v["macd_sig_p"])
        macd_bear = v["macd"] < v["macd_sig"]
        hist_dn   = v["macd_hist"] < v["macd_hist_p"]

        if macd_cross_dn and v["macd"] < 0:
            score += 2
            reasons.append("✅ MACD Bearish Crossover (below zero)")
        elif macd_cross_dn:
            score += 1.5
            reasons.append("✅ MACD Bearish Crossover")
        elif macd_bear and hist_dn:
            score += 1
            reasons.append("⚡ MACD Bearish momentum")
        elif macd_bear:
            score += 0.5
            reasons.append("⚡ MACD below signal")
        else:
            warns.append("⚠️ MACD bullish")

        # ── 4. SuperTrend (max 1 pt) ──────────────────────
        st_flip_bear = not v["st_bull"] and v["st_bull_p"]
        if st_flip_bear:
            score += 1
            reasons.append("✅ SuperTrend just turned BEARISH 🔄")
        elif not v["st_bull"]:
            score += 0.5
            reasons.append(f"⚡ SuperTrend Bearish (price < ₹{v['st']:.2f})")
        else:
            warns.append("⚠️ SuperTrend Bullish - weak short")

        # ── 5. ADX (max 1 pt) ─────────────────────────────
        adx = v["adx"]
        if adx >= 30:
            score += 1
            reasons.append(f"✅ ADX={adx:.0f} Strong trend")
        elif adx >= self.ADX_THRESH:
            score += 0.5
            reasons.append(f"⚡ ADX={adx:.0f} Moderate trend")
        else:
            warns.append(f"⚠️ ADX={adx:.0f} Weak trend")

        # ── 6. Volume (max 1 pt) ──────────────────────────
        vol_ratio = v["vol"] / max(v["vol_ma"], 1)
        if vol_ratio >= 2.0:
            score += 1
            reasons.append(f"✅ Volume spike {vol_ratio:.1f}x")
        elif vol_ratio >= self.VOL_MULT:
            score += 0.5
            reasons.append(f"⚡ Volume {vol_ratio:.1f}x above avg")
        else:
            warns.append(f"⚠️ Low volume")

        # ── 7. VWAP (max 1 pt) ────────────────────────────
        if c < v["vwap"] * 0.999:
            score += 1
            reasons.append(f"✅ Price below VWAP (₹{v['vwap']:.2f})")
        elif c < v["vwap"]:
            score += 0.5
        else:
            warns.append(f"⚠️ Price above VWAP - weak short")

        return int(score), reasons, warns


# ─────────────────────────────────────────────────────────────
# BULK SCANNER
# ─────────────────────────────────────────────────────────────

class BulkScanner:
    """
    Multiple stocks ko scan karo aur results return karo.
    Kite API se data fetch karta hai.
    """

    def __init__(self, kite):
        self.kite         = kite
        self.scanner      = StockScanner()
        self._token_cache = {}   # {tradingsymbol: instrument_token}

    def _get_instrument_token(self, symbol: str, exchange: str = "NSE") -> Optional[int]:
        """Instrument token lookup with 1-time in-memory caching"""
        if not self._token_cache and self.kite:
            try:
                instruments = self.kite.instruments(exchange)
                for inst in instruments:
                    sym = inst.get("tradingsymbol")
                    tok = inst.get("instrument_token")
                    if sym and tok:
                        self._token_cache[sym] = tok
                logger.info(f"Cached {len(self._token_cache)} instruments for {exchange}")
            except Exception as e:
                logger.warning(f"Instruments fetch error: {e}")
        return self._token_cache.get(symbol)

    def scan_symbols(
        self,
        symbols:   list,
        timeframe: str = "day",
        days:      int = 200,
        min_score: int = 6,
        progress_cb = None,   # Callback(done, total, current_symbol, current_results)
        stop_check  = None,   # Callable returning True if scan should abort
    ) -> list[ScanResult]:
        """
        Symbols list scan karo.
        Returns list of ScanResult sorted by score (highest first).
        Supports progressive updates and early cancellation.
        """
        import time

        results = []
        total   = len(symbols)

        # Pre-cache instruments once before loop
        self._get_instrument_token("RELIANCE")

        for i, item in enumerate(symbols):
            if stop_check and stop_check():
                logger.info("BulkScanner: scan stopped early by request")
                break

            symbol = item if isinstance(item, str) else item.get("symbol", "")
            name   = item.get("name", "") if isinstance(item, dict) else ""

            if not symbol:
                continue

            # Progress callback before analyzing
            if progress_cb:
                try:
                    progress_cb(i + 1, total, symbol, results)
                except Exception:
                    pass

            try:
                df = self._fetch_data(symbol, timeframe, days)
                if df is None or df.empty:
                    continue

                result = self.scanner.analyse(symbol, name, df, timeframe)
                if result and result.score >= min_score:
                    results.append(result)
                    # Notify with updated results
                    if progress_cb:
                        try:
                            progress_cb(i + 1, total, symbol, results)
                        except Exception:
                            pass

                time.sleep(0.08)   # Safe rate limiting for Kite historical API

            except Exception as e:
                logger.debug(f"Scan error {symbol}: {e}")
                continue

        # Sort by score descending
        results.sort(key=lambda x: (-x.score, x.symbol))
        logger.info(f"Scanner: {len(results)}/{total} signals found")
        return results

    def _fetch_data(self, symbol: str, timeframe: str, days: int) -> Optional[pd.DataFrame]:
        """Kite se historical data fetch karo using cached token"""
        from datetime import datetime, timedelta
        import pytz

        IST = pytz.timezone("Asia/Kolkata")
        to_date   = datetime.now(IST)
        from_date = to_date - timedelta(days=days)

        interval_map = {
            "day":      "day",
            "60minute": "60minute",
            "30minute": "30minute",
            "15minute": "15minute",
            "5minute":  "5minute",
        }
        interval = interval_map.get(timeframe, "day")

        try:
            token = self._get_instrument_token(symbol)
            if not token:
                return None

            records = self.kite.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                continuous=False,
                oi=False,
            )

            if not records:
                return None

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)

        except Exception as e:
            logger.debug(f"Data fetch error {symbol}: {e}")
            return None
