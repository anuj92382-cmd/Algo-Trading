"""
data.py - Market Data Fetcher Module
Zerodha Kite se historical aur live market data fetch karo
Technical indicators bhi yahi calculate hote hain
"""

import logging
import time
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
import numpy as np
import pytz
from kiteconnect import KiteConnect

from config import IST, INTRADAY_CONFIG, SWING_CONFIG, KITE_API

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class DataFetcher:
    """
    Kite se market data fetch karta hai.
    
    Features:
    - Historical OHLCV data
    - Live quotes (LTP, depth)
    - Technical indicators (EMA, RSI, MACD, VWAP, BB, ATR, ADX)
    - Instruments list aur symbol search
    """

    # Kite timeframe mapping
    TIMEFRAMES = {
        "1minute":  "minute",
        "3minute":  "3minute",
        "5minute":  "5minute",
        "10minute": "10minute",
        "15minute": "15minute",
        "30minute": "30minute",
        "60minute": "60minute",
        "day":      "day",
        "week":     "week",
        "month":    "month",
    }

    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self._instruments_cache: dict = {}
        self._last_instruments_fetch: Optional[datetime] = None

    # ─────────────────────────────────────────────────────────
    # HISTORICAL DATA
    # ─────────────────────────────────────────────────────────

    def get_historical_data(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        days: int = 100,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Historical OHLCV data fetch karo.
        
        Args:
            symbol:    NSE symbol e.g. "RELIANCE"
            exchange:  "NSE" ya "BSE"
            timeframe: "5minute", "day", etc.
            days:      Kitne din ka data chahiye
            from_date: Custom start date (optional)
            to_date:   Custom end date (optional)
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        try:
            instrument_token = self._get_instrument_token(symbol, exchange)
            if not instrument_token:
                logger.error(f"Instrument token nahi mila: {symbol}:{exchange}")
                return pd.DataFrame()

            # Date range set karo
            if to_date is None:
                to_date = datetime.now(IST_tz)
            if from_date is None:
                from_date = to_date - timedelta(days=days)

            kite_interval = self.TIMEFRAMES.get(timeframe, "day")

            logger.debug(f"Fetching {symbol} {timeframe} data: {from_date.date()} to {to_date.date()}")

            # Rate limit respect karo
            time.sleep(0.1)

            records = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=kite_interval,
                continuous=False,
                oi=False,
            )

            if not records:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            logger.info(f"✅ {symbol} | {len(df)} candles | {timeframe}")
            return df

        except Exception as e:
            logger.error(f"Historical data error for {symbol}: {e}")
            return pd.DataFrame()

    def get_multiple_symbols_data(
        self,
        symbols: list,
        exchange: str,
        timeframe: str,
        days: int = 100,
    ) -> dict[str, pd.DataFrame]:
        """Ek saath kai symbols ka data fetch karo"""
        result = {}
        for symbol in symbols:
            df = self.get_historical_data(symbol, exchange, timeframe, days)
            if not df.empty:
                result[symbol] = df
            time.sleep(0.1)  # Rate limiting
        logger.info(f"✅ {len(result)}/{len(symbols)} symbols ka data mila")
        return result

    # ─────────────────────────────────────────────────────────
    # LIVE QUOTES
    # ─────────────────────────────────────────────────────────

    def get_ltp(self, symbols: list, exchange: str = "NSE") -> dict:
        """
        Last Traded Price fetch karo.
        
        Returns:
            {"RELIANCE": 2500.50, "TCS": 3400.00, ...}
        """
        try:
            instrument_list = [f"{exchange}:{s}" for s in symbols]
            quotes = self.kite.ltp(instrument_list)
            result = {}
            for key, data in quotes.items():
                symbol = key.split(":")[1]
                result[symbol] = data["last_price"]
            return result
        except Exception as e:
            logger.error(f"LTP fetch error: {e}")
            return {}

    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        """Full quote data fetch karo (OHLC, volume, depth)"""
        try:
            instrument = f"{exchange}:{symbol}"
            quotes = self.kite.quote([instrument])
            return quotes.get(instrument, {})
        except Exception as e:
            logger.error(f"Quote fetch error for {symbol}: {e}")
            return {}

    def get_ohlc(self, symbols: list, exchange: str = "NSE") -> dict:
        """OHLC + LTP fetch karo"""
        try:
            instrument_list = [f"{exchange}:{s}" for s in symbols]
            return self.kite.ohlc(instrument_list)
        except Exception as e:
            logger.error(f"OHLC fetch error: {e}")
            return {}

    # ─────────────────────────────────────────────────────────
    # TECHNICAL INDICATORS
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def add_ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
        """Exponential Moving Average add karo"""
        df[f"ema_{period}"] = df[column].ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.DataFrame:
        """Relative Strength Index add karo"""
        delta = df[column].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        df["rsi"] = df["rsi"].fillna(50)
        return df

    @staticmethod
    def add_macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        column: str = "close",
    ) -> pd.DataFrame:
        """MACD + Signal + Histogram add karo"""
        ema_fast = df[column].ewm(span=fast, adjust=False).mean()
        ema_slow = df[column].ewm(span=slow, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        return df

    @staticmethod
    def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """
        Volume Weighted Average Price add karo.
        Intraday ke liye - har din reset hota hai.
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df["trading_day"] = df["date"].dt.date

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        df["tp_vol"] = typical_price * df["volume"]

        # Har din ke liye cumulative calculate karo
        df["cum_tp_vol"] = df.groupby("trading_day")["tp_vol"].cumsum()
        df["cum_vol"] = df.groupby("trading_day")["volume"].cumsum()
        df["vwap"] = df["cum_tp_vol"] / df["cum_vol"].replace(0, np.nan)
        df["vwap"] = df["vwap"].fillna(df["close"])

        # Cleanup columns
        df.drop(columns=["tp_vol", "cum_tp_vol", "cum_vol", "trading_day"],
                inplace=True, errors="ignore")
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Average True Range add karo (stop loss ke liye)"""
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        df["atr"] = tr.ewm(com=period - 1, min_periods=period).mean()
        return df

    @staticmethod
    def add_bollinger_bands(
        df: pd.DataFrame, period: int = 20, std_dev: float = 2.0, column: str = "close"
    ) -> pd.DataFrame:
        """Bollinger Bands add karo"""
        sma = df[column].rolling(window=period).mean()
        std = df[column].rolling(window=period).std()
        df["bb_upper"] = sma + (std * std_dev)
        df["bb_middle"] = sma
        df["bb_lower"] = sma - (std * std_dev)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Average Directional Index add karo (trend strength)"""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = low.diff().abs()

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(com=period - 1, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(com=period - 1).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.ewm(com=period - 1).mean() / atr.replace(0, np.nan))

        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df["adx"] = dx.ewm(com=period - 1, min_periods=period).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        return df

    @staticmethod
    def add_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Volume Moving Average add karo"""
        df[f"volume_ma_{period}"] = df["volume"].rolling(window=period).mean()
        df["volume_ratio"] = df["volume"] / df[f"volume_ma_{period}"].replace(0, np.nan)
        return df

    @staticmethod
    def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        """SuperTrend indicator add karo"""
        df = df.copy()
        DataFetcher.add_atr(df, period)

        hl2 = (df["high"] + df["low"]) / 2
        upper_band = hl2 + (multiplier * df["atr"])
        lower_band = hl2 - (multiplier * df["atr"])

        supertrend = [True] * len(df)
        for i in range(1, len(df)):
            if df["close"].iloc[i] > upper_band.iloc[i - 1]:
                supertrend[i] = True
            elif df["close"].iloc[i] < lower_band.iloc[i - 1]:
                supertrend[i] = False
            else:
                supertrend[i] = supertrend[i - 1]

        df["supertrend_bull"] = supertrend
        df["supertrend"] = np.where(
            df["supertrend_bull"],
            lower_band,
            upper_band
        )
        return df

    def add_all_intraday_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Intraday ke liye saare indicators ek saath add karo"""
        cfg = INTRADAY_CONFIG["indicators"]
        df = self.add_ema(df, cfg["ema_fast"])
        df = self.add_ema(df, cfg["ema_slow"])
        df = self.add_rsi(df, cfg["rsi_period"])
        df = self.add_vwap(df)
        df = self.add_atr(df, cfg["atr_period"])
        df = self.add_volume_ma(df)
        return df

    def add_all_swing_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Swing trading ke liye saare indicators add karo"""
        cfg = SWING_CONFIG["indicators"]
        df = self.add_ema(df, cfg["ema_fast"])
        df = self.add_ema(df, cfg["ema_slow"])
        df = self.add_macd(df, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"])
        df = self.add_rsi(df, cfg["rsi_period"])
        df = self.add_bollinger_bands(df, cfg["bb_period"], cfg["bb_std"])
        df = self.add_adx(df, cfg["adx_period"])
        df = self.add_atr(df)
        df = self.add_volume_ma(df)
        return df

    # ─────────────────────────────────────────────────────────
    # INSTRUMENTS
    # ─────────────────────────────────────────────────────────

    def get_instruments(self, exchange: str = "NSE") -> pd.DataFrame:
        """
        Sab instruments ki list fetch karo.
        Cache karta hai - baar baar API call nahi hoti.
        """
        cache_key = exchange
        now = datetime.now(IST_tz)

        # Cache valid check (1 ghante ke liye valid)
        if (
            cache_key in self._instruments_cache
            and self._last_instruments_fetch
            and (now - self._last_instruments_fetch).seconds < 3600
        ):
            return self._instruments_cache[cache_key]

        try:
            instruments = self.kite.instruments(exchange)
            df = pd.DataFrame(instruments)
            self._instruments_cache[cache_key] = df
            self._last_instruments_fetch = now
            logger.info(f"✅ {exchange} instruments loaded: {len(df)} symbols")
            return df
        except Exception as e:
            logger.error(f"Instruments fetch error: {e}")
            return pd.DataFrame()

    def _get_instrument_token(self, symbol: str, exchange: str) -> Optional[int]:
        """Symbol ka instrument token dhoondo"""
        instruments = self.get_instruments(exchange)
        if instruments.empty:
            return None

        match = instruments[
            (instruments["tradingsymbol"] == symbol) &
            (instruments["exchange"] == exchange)
        ]

        if match.empty:
            logger.warning(f"Symbol nahi mila: {symbol} on {exchange}")
            return None

        return int(match.iloc[0]["instrument_token"])

    def search_symbol(self, query: str, exchange: str = "NSE") -> pd.DataFrame:
        """Symbol search karo"""
        instruments = self.get_instruments(exchange)
        if instruments.empty:
            return pd.DataFrame()

        mask = (
            instruments["tradingsymbol"].str.contains(query.upper(), na=False) |
            instruments["name"].str.contains(query.upper(), na=False, case=False)
        )
        return instruments[mask][["tradingsymbol", "name", "instrument_token",
                                   "exchange", "segment", "lot_size"]].head(20)

    # ─────────────────────────────────────────────────────────
    # MARKET STATUS
    # ─────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Market khula hai ya band?"""
        now = datetime.now(IST_tz).time()
        return (
            now >= IST.MARKET_OPEN
            and now <= IST.MARKET_CLOSE
        ) if hasattr(IST, "MARKET_OPEN") else (
            now >= datetime.strptime("09:15", "%H:%M").time()
            and now <= datetime.strptime("15:30", "%H:%M").time()
        )

    def get_market_depth(self, symbol: str, exchange: str = "NSE") -> dict:
        """Market depth (bid/ask) fetch karo"""
        try:
            quote = self.get_quote(symbol, exchange)
            return quote.get("depth", {})
        except Exception as e:
            logger.error(f"Market depth error: {e}")
            return {}
