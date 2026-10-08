"""
main.py - Main Trading Bot
Zerodha Kite Algo Trading - Master Controller

Yeh file sabkuch orchestrate karta hai:
  - Authentication
  - Data fetching
  - Strategy signals
  - Risk checks
  - Order placement
  - Live ticker
  - Scheduled tasks
"""

import logging
import signal
import sys
import time
import threading
import os
from datetime import datetime, date

# ── SSL Fix - sabse pehle yeh run hona chahiye ───────────────
try:
    import certifi
    os.environ["SSL_CERT_FILE"]      = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
except ImportError:
    pass
# ─────────────────────────────────────────────────────────────

import pytz
import schedule

from utils.logger import setup_logger
from config import (
    INTRADAY_CONFIG, SWING_CONFIG, IS_PAPER_TRADING,
    TRADING_MODE, TOTAL_CAPITAL, TELEGRAM,
    INTRADAY_ENTRY_CUTOFF, INTRADAY_EXIT_TIME,
    PRE_MARKET_TIME, MARKET_OPEN, MARKET_CLOSE,
    validate_config,
)
from auth import KiteAuth
from data import DataFetcher
from order_manager import OrderManager
from risk_manager import RiskManager
from ticker import LiveTicker
from strategies.intraday import IntradayStrategy, Signal as ISignal
from strategies.swing import SwingStrategy, SwingSignal
from utils.notifier import notifier

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class AlgoTradingBot:
    """
    Main trading bot - sabkuch yahan se chalata hai.

    Flow:
      1. Login → Kite instance
      2. Instruments + data load karo
      3. Live ticker start karo
      4. Har 5 min pe intraday scan
      5. EOD pe swing scan
      6. Risk checks har jagah
      7. 3:15 PM pe force square-off
    """

    def __init__(self):
        self.kite         = None
        self.data         = None
        self.order_mgr    = None
        self.risk_mgr     = None
        self.ticker       = None
        self.intraday_strat = IntradayStrategy()
        self.swing_strat    = SwingStrategy()

        self._running     = False
        self._intraday_data: dict = {}   # {symbol: df with indicators}
        self._swing_data:    dict = {}

        # Graceful shutdown ke liye signal handler
        signal.signal(signal.SIGINT,  self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    # ─────────────────────────────────────────────────────────
    # STARTUP
    # ─────────────────────────────────────────────────────────

    def start(self):
        """Bot start karo"""
        print("\n" + "═"*60)
        print("  🤖 ZERODHA ALGO TRADING BOT")
        print(f"  Mode: {'📄 PAPER TRADING' if IS_PAPER_TRADING else '🔴 LIVE TRADING'}")
        print(f"  Capital: ₹{TOTAL_CAPITAL:,.0f}")
        print("═"*60 + "\n")

        # ── 1. Config validate karo ───────────────────────────
        errors, warnings = validate_config()
        for w in warnings:
            logger.warning(w)
        if errors:
            for e in errors:
                logger.error(e)
            logger.error("Config errors hain. .env file check karo.")
            sys.exit(1)

        # ── 2. Login ──────────────────────────────────────────
        logger.info("🔐 Authenticating with Zerodha...")
        try:
            auth = KiteAuth()
            self.kite = auth.get_kite_instance()
        except Exception as e:
            logger.error(f"Login failed: {e}")
            sys.exit(1)

        # ── 3. Core modules initialize karo ───────────────────
        self.data      = DataFetcher(self.kite)
        self.order_mgr = OrderManager(self.kite)
        self.risk_mgr  = RiskManager(TOTAL_CAPITAL)

        # ── 4. Initial data load karo ─────────────────────────
        logger.info("📥 Loading initial market data...")
        self._load_intraday_data()
        self._load_swing_data()

        # ── 5. Live ticker start karo ─────────────────────────
        self._start_ticker()

        # ── 6. Scheduler setup karo ───────────────────────────
        self._setup_schedule()

        # ── 7. Main loop ──────────────────────────────────────
        self._running = True
        logger.info("✅ Bot is LIVE! Press Ctrl+C to stop.\n")
        notifier.send("🤖 Algo Bot started!\nMode: " +
                      ("PAPER" if IS_PAPER_TRADING else "LIVE") +
                      f"\nCapital: ₹{TOTAL_CAPITAL:,.0f}")

        try:
            while self._running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Bot gracefully band karo"""
        logger.info("🛑 Shutting down bot...")
        self._running = False

        # Ticker band karo
        if self.ticker:
            self.ticker.stop()

        # Schedule clear karo
        schedule.clear()

        # Final stats print karo
        if self.risk_mgr:
            stats = self.risk_mgr.get_daily_stats()
            logger.info(f"\n{'─'*50}")
            logger.info(f"📊 FINAL STATS - {date.today()}")
            logger.info(f"   Total Trades : {stats['total_trades']}")
            logger.info(f"   Winners      : {stats['winners']}")
            logger.info(f"   Losers       : {stats['losers']}")
            logger.info(f"   Win Rate     : {stats['win_rate']}%")
            logger.info(f"   Daily P&L    : ₹{stats['daily_pnl']:+.2f}")
            logger.info(f"{'─'*50}\n")

            notifier.daily_summary(
                stats["total_trades"], stats["winners"],
                stats["losers"], stats["daily_pnl"], stats["current_capital"]
            )

        logger.info("👋 Bot stopped.")

    def _shutdown_handler(self, signum, frame):
        logger.info("Shutdown signal received...")
        self._running = False

    # ─────────────────────────────────────────────────────────
    # SCHEDULER
    # ─────────────────────────────────────────────────────────

    def _setup_schedule(self):
        """Scheduled tasks setup karo"""
        schedule.clear()

        # ── Intraday scan: Har 5 minute ───────────────────────
        schedule.every(5).minutes.do(self._intraday_scan_job)

        # ── Data refresh: Har 5 minute ────────────────────────
        schedule.every(5).minutes.do(self._load_intraday_data)

        # ── Pre-market: 9:00 AM ───────────────────────────────
        schedule.every().day.at("09:00").do(self._pre_market_job)

        # ── Market open: 9:15 AM ──────────────────────────────
        schedule.every().day.at("09:15").do(self._market_open_job)

        # ── Force square-off: 3:15 PM ─────────────────────────
        schedule.every().day.at("15:15").do(self._force_squareoff_job)

        # ── Swing scan: EOD 3:30 PM ───────────────────────────
        schedule.every().day.at("15:30").do(self._swing_eod_scan_job)

        # ── Daily report: 4:00 PM ─────────────────────────────
        schedule.every().day.at("16:00").do(self._daily_report_job)

        # ── Risk status print: Har 15 minute ──────────────────
        schedule.every(15).minutes.do(self._print_risk_status)

        logger.info("✅ Scheduler configured")

    # ─────────────────────────────────────────────────────────
    # SCHEDULED JOBS
    # ─────────────────────────────────────────────────────────

    def _pre_market_job(self):
        """9:00 AM - Pre-market preparation"""
        logger.info("⏰ Pre-market job running...")
        self._load_intraday_data()
        self._load_swing_data()
        logger.info("✅ Data loaded for the day")

    def _market_open_job(self):
        """9:15 AM - Market open"""
        logger.info("🔔 Market is OPEN!")
        notifier.send("🔔 Market Open - Bot is scanning...")

    def _intraday_scan_job(self):
        """Har 5 min - Intraday signals check karo"""
        if not self._is_market_time():
            return
        if not INTRADAY_CONFIG["enabled"]:
            return

        now = datetime.now(IST_tz).time()
        if now >= INTRADAY_EXIT_TIME:
            return  # Already in exit zone
        from datetime import time as dtime
        if now < dtime(9, 20):
            return  # No orders before 9:20 AM

        try:
            # Latest data fetch karo
            self._refresh_intraday_data()

            # Risk check
            can_trade, reason = self.risk_mgr.can_trade()
            if not can_trade:
                logger.warning(f"⛔ Cannot trade: {reason}")
                return

            # Signals generate karo
            signals = self.intraday_strat.scan_all(self._intraday_data)

            for sig in signals:
                self._process_intraday_signal(sig)

        except Exception as e:
            logger.error(f"Intraday scan error: {e}")
            notifier.error_alert(f"Intraday scan error: {e}")

    def _force_squareoff_job(self):
        """3:15 PM - Saari intraday positions close karo"""
        logger.info("⏰ 3:15 PM - Force square-off starting...")
        signals = self.intraday_strat.force_exit_all(self._intraday_data)

        for sig in signals:
            logger.info(f"🔴 Force exit: {sig.symbol}")
            self._execute_exit_order(
                symbol=sig.symbol,
                price=sig.price,
                direction="LONG" if sig.signal.value == "EXIT_LONG" else "SHORT",
                reason=sig.reason,
                product="MIS",
            )

        if signals:
            logger.info(f"✅ {len(signals)} positions square-off initiated")
            notifier.send(f"⏰ 3:15 PM Square-off: {len(signals)} positions closed")

    def _swing_eod_scan_job(self):
        """3:30 PM - Swing trading EOD scan"""
        if not SWING_CONFIG["enabled"]:
            return
        logger.info("📊 EOD Swing scan running...")

        try:
            self._load_swing_data()
            signals = self.swing_strat.scan_all(self._swing_data)

            buy_signals = [s for s in signals if s.signal == SwingSignal.BUY]
            exit_signals = [s for s in signals
                            if s.signal in (SwingSignal.EXIT_LONG, SwingSignal.EXIT_SHORT)]

            # Process exits pehle
            for sig in exit_signals:
                self._process_swing_exit(sig)

            # Then entries
            for sig in buy_signals[:3]:   # Max 3 new swing positions per day
                self._process_swing_entry(sig)

            if buy_signals:
                logger.info(f"📈 Swing: {len(buy_signals)} BUY signals")

        except Exception as e:
            logger.error(f"Swing EOD scan error: {e}")

    def _daily_report_job(self):
        """4:00 PM - Daily report generate karo"""
        logger.info("📋 Generating daily report...")
        stats = self.risk_mgr.get_daily_stats()
        self._save_daily_report(stats)
        logger.info(f"📊 Daily P&L: ₹{stats['daily_pnl']:+.2f} | "
                    f"Trades: {stats['total_trades']} | "
                    f"Win Rate: {stats['win_rate']}%")

    def _print_risk_status(self):
        """Har 15 min - Risk status print karo"""
        if self.risk_mgr and self._is_market_time():
            logger.info(self.risk_mgr.get_status_bar())

    # ─────────────────────────────────────────────────────────
    # SIGNAL PROCESSING
    # ─────────────────────────────────────────────────────────

    def _process_intraday_signal(self, sig):
        """Intraday signal process karo aur order place karo"""
        from strategies.intraday import Signal as IS

        symbol    = sig.symbol
        direction = "LONG" if sig.signal == IS.BUY else "SHORT"
        price     = sig.price

        # Exit signals
        if sig.signal in (IS.EXIT_LONG, IS.EXIT_SHORT):
            self._execute_exit_order(
                symbol=symbol,
                price=price,
                direction="LONG" if sig.signal == IS.EXIT_LONG else "SHORT",
                reason=sig.reason,
                product="MIS",
            )
            return

        # Entry signals - risk check
        can_trade, reason = self.risk_mgr.can_trade(symbol)
        if not can_trade:
            logger.debug(f"⛔ {symbol}: {reason}")
            return

        # Position size calculate karo
        qty = self.risk_mgr.calculate_position_size(price, sig.stop_loss)
        if qty <= 0:
            logger.warning(f"⛔ {symbol}: Zero quantity calculated")
            return
        sig.quantity = qty

        # Final validation
        valid, msg = self.risk_mgr.validate_trade(
            symbol=symbol, price=price,
            stop_loss=sig.stop_loss, target=sig.target,
            quantity=qty, direction=direction
        )
        if not valid:
            logger.warning(f"⛔ {symbol} trade rejected: {msg}")
            return

        # Order place karo
        order = self.order_mgr.place_market_order(
            symbol=symbol,
            transaction="BUY" if direction == "LONG" else "SELL",
            quantity=qty,
            exchange=INTRADAY_CONFIG["exchange"],
            product=INTRADAY_CONFIG["product"],
            tag=f"INTRADAY_{direction[:1]}",
        )

        if order:
            # Register karo
            self.risk_mgr.register_entry(
                symbol=symbol, direction=direction,
                price=price, quantity=qty,
                stop_loss=sig.stop_loss, target=sig.target,
                strategy="INTRADAY",
            )
            self.intraday_strat.register_trade(symbol, sig)

            # SL order bhi place karo
            sl_txn = "SELL" if direction == "LONG" else "BUY"
            self.order_mgr.place_sl_market_order(
                symbol=symbol,
                transaction=sl_txn,
                quantity=qty,
                trigger_price=sig.stop_loss,
                exchange=INTRADAY_CONFIG["exchange"],
                product=INTRADAY_CONFIG["product"],
                tag=f"INTRADAY_SL",
            )

            logger.info(
                f"✅ INTRADAY {direction}: {symbol} {qty}@₹{price:.2f} | "
                f"SL:₹{sig.stop_loss:.2f} Target:₹{sig.target:.2f}"
            )
            notifier.trade_entry(
                symbol, direction, price, qty,
                sig.stop_loss, sig.target, "INTRADAY"
            )

    def _process_swing_entry(self, sig):
        """Swing entry signal process karo"""
        symbol    = sig.symbol
        price     = sig.price

        can_trade, reason = self.risk_mgr.can_trade(symbol)
        if not can_trade:
            return

        qty = self.risk_mgr.calculate_position_size(price, sig.stop_loss)
        if qty <= 0:
            return
        sig.quantity = qty

        valid, msg = self.risk_mgr.validate_trade(
            symbol=symbol, price=price,
            stop_loss=sig.stop_loss, target=sig.target,
            quantity=qty, direction="LONG"
        )
        if not valid:
            logger.warning(f"⛔ Swing {symbol}: {msg}")
            return

        order = self.order_mgr.place_limit_order(
            symbol=symbol,
            transaction="BUY",
            quantity=qty,
            price=round(price * 1.002, 1),  # Slight premium for fill
            exchange=SWING_CONFIG["exchange"],
            product=SWING_CONFIG["product"],
            tag=f"SWING_BUY",
        )

        if order:
            self.risk_mgr.register_entry(
                symbol=symbol, direction="LONG",
                price=price, quantity=qty,
                stop_loss=sig.stop_loss, target=sig.target,
                strategy="SWING",
            )
            self.swing_strat.register_trade(symbol, sig)

            logger.info(
                f"✅ SWING BUY: {symbol} {qty}@₹{price:.2f} | "
                f"Score:{sig.score}/{sig.max_score} | {sig.conviction}"
            )
            notifier.trade_entry(
                symbol, "LONG", price, qty,
                sig.stop_loss, sig.target, f"SWING (score:{sig.score})"
            )

    def _process_swing_exit(self, sig):
        """Swing exit signal process karo"""
        self._execute_exit_order(
            symbol=sig.symbol,
            price=sig.price,
            direction="LONG",
            reason=sig.reason,
            product="CNC",
        )

    def _execute_exit_order(
        self,
        symbol: str,
        price: float,
        direction: str,
        reason: str,
        product: str = "MIS",
    ):
        """Exit order place karo aur position close karo"""
        # Active position check
        pos = (
            self.intraday_strat.get_active_positions().get(symbol)
            or self.swing_strat.get_active_positions().get(symbol)
        )
        if not pos:
            return

        qty = pos.get("quantity", 1)
        txn = "SELL" if direction == "LONG" else "BUY"

        order = self.order_mgr.place_market_order(
            symbol=symbol,
            transaction=txn,
            quantity=qty,
            product=product,
            tag="EXIT",
        )

        if order:
            record = self.risk_mgr.register_exit(symbol, price, reason)
            self.intraday_strat.close_position(symbol)
            self.swing_strat.close_position(symbol)

            if record:
                notifier.trade_exit(
                    symbol, record.entry_price, price,
                    qty, record.pnl, reason
                )
                logger.info(
                    f"{'✅' if record.pnl >= 0 else '❌'} EXIT {symbol} "
                    f"₹{record.entry_price:.2f}→₹{price:.2f} | "
                    f"P&L: ₹{record.pnl:+.2f} | {reason}"
                )

    # ─────────────────────────────────────────────────────────
    # DATA LOADING
    # ─────────────────────────────────────────────────────────

    def _load_intraday_data(self):
        """Intraday watchlist ka data load karo"""
        try:
            symbols  = INTRADAY_CONFIG["watchlist"]
            exchange = INTRADAY_CONFIG["exchange"]
            tf       = INTRADAY_CONFIG["timeframe"]

            raw_data = self.data.get_multiple_symbols_data(
                symbols, exchange, tf, days=5
            )
            for symbol, df in raw_data.items():
                if not df.empty:
                    df = self.data.add_all_intraday_indicators(df)
                    self._intraday_data[symbol] = df

            logger.debug(f"Intraday data loaded: {len(self._intraday_data)} symbols")
        except Exception as e:
            logger.error(f"Intraday data load error: {e}")

    def _load_swing_data(self):
        """Swing watchlist ka daily data load karo"""
        try:
            symbols  = SWING_CONFIG["watchlist"]
            exchange = SWING_CONFIG["exchange"]

            raw_data = self.data.get_multiple_symbols_data(
                symbols, exchange, "day", days=200
            )
            for symbol, df in raw_data.items():
                if not df.empty:
                    df = self.data.add_all_swing_indicators(df)
                    self._swing_data[symbol] = df

            logger.debug(f"Swing data loaded: {len(self._swing_data)} symbols")
        except Exception as e:
            logger.error(f"Swing data load error: {e}")

    def _refresh_intraday_data(self):
        """Latest candle ke saath intraday data update karo"""
        try:
            symbols  = INTRADAY_CONFIG["watchlist"]
            exchange = INTRADAY_CONFIG["exchange"]
            tf       = INTRADAY_CONFIG["timeframe"]

            # Sirf last 2 din ka data chahiye for refresh
            raw_data = self.data.get_multiple_symbols_data(
                symbols, exchange, tf, days=2
            )
            for symbol, df_new in raw_data.items():
                if df_new.empty:
                    continue
                existing = self._intraday_data.get(symbol)
                if existing is not None and not existing.empty:
                    # Merge + deduplicate
                    combined = (
                        existing.copy()
                        ._append(df_new, ignore_index=True)
                        .drop_duplicates(subset=["date"])
                        .sort_values("date")
                        .tail(500)   # Last 500 candles rakhte hain
                        .reset_index(drop=True)
                    )
                else:
                    combined = df_new

                self._intraday_data[symbol] = self.data.add_all_intraday_indicators(combined)

        except Exception as e:
            logger.error(f"Data refresh error: {e}")

    # ─────────────────────────────────────────────────────────
    # LIVE TICKER
    # ─────────────────────────────────────────────────────────

    def _start_ticker(self):
        """Live ticker start karo"""
        try:
            from config import KITE_API_KEY
            access_token = self.kite.access_token

            self.ticker = LiveTicker(
                kite=self.kite,
                api_key=KITE_API_KEY,
                access_token=access_token,
                mode="quote",
            )

            # Subscribe karo
            all_symbols = list(set(
                INTRADAY_CONFIG["watchlist"] + SWING_CONFIG["watchlist"]
            ))
            self.ticker.subscribe(all_symbols, exchange="NSE")

            # Tick callback
            self.ticker.start(
                on_tick=self._on_tick,
                on_connect=lambda: logger.info("📡 Live feed connected"),
                threaded=True,
            )
            logger.info(f"📡 Live ticker started for {len(all_symbols)} symbols")

        except Exception as e:
            logger.warning(f"Ticker start failed: {e}. Running without live feed.")

    def _on_tick(self, symbol: str, tick: dict):
        """
        Har tick pe yeh callback call hota hai.
        Yahan real-time SL breach check kar sakte ho.
        """
        ltp = tick.get("ltp", 0)
        if ltp <= 0:
            return

        # Intraday SL real-time check
        intraday_pos = self.intraday_strat.get_active_positions()
        if symbol in intraday_pos:
            pos = intraday_pos[symbol]
            sl  = pos["stop_loss"]

            if pos["direction"] == "LONG" and ltp <= sl:
                logger.warning(f"⚠️  Real-time SL breach: {symbol} LTP={ltp:.2f} SL={sl:.2f}")
                self._execute_exit_order(
                    symbol=symbol, price=ltp,
                    direction="LONG",
                    reason=f"Real-time SL breach @ ₹{ltp:.2f}",
                )

    # ─────────────────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────────────────

    def _is_market_time(self) -> bool:
        """Market hours mein hain?"""
        now = datetime.now(IST_tz).time()
        return MARKET_OPEN <= now <= MARKET_CLOSE

    def _save_daily_report(self, stats: dict):
        """Daily report CSV mein save karo"""
        import csv
        import os
        from config import REPORTS
        os.makedirs(REPORTS["dir"], exist_ok=True)
        filename = f"{REPORTS['dir']}/report_{date.today().isoformat()}.csv"

        trades = self.risk_mgr.get_trade_history()
        if not trades:
            return

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                if trades:
                    writer = csv.DictWriter(f, fieldnames=trades[0].keys())
                    writer.writeheader()
                    writer.writerows(trades)
            logger.info(f"📄 Report saved: {filename}")
        except Exception as e:
            logger.error(f"Report save error: {e}")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def main():
    setup_logger(log_level="INFO", log_file="logs/trading.log")

    bot = AlgoTradingBot()
    bot.start()


if __name__ == "__main__":
    main()
