"""
dashboard.py - Trading Dashboard
Terminal mein live P&L, positions aur market data dikhata hai
Rich library ka use karke beautiful console UI

Run karo: python dashboard.py
"""

import logging
import os
import sys
import time
import threading
from datetime import datetime, date

import pytz
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn
from rich import box
from rich.columns import Columns
from rich.align import Align

from utils.logger import setup_logger
from config import (
    TOTAL_CAPITAL, IS_PAPER_TRADING, TRADING_MODE,
    INTRADAY_CONFIG, SWING_CONFIG, MAX_DAILY_LOSS_AMOUNT,
    validate_config,
)

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")
console = Console()


class TradingDashboard:
    """
    Live terminal dashboard - saari trading info ek jagah.

    Sections:
      - Header (status, mode, time)
      - P&L Summary
      - Active Positions
      - Today's Trades
      - Market Watchlist (live prices)
      - Risk Meter
    """

    REFRESH_INTERVAL = 3   # Seconds

    def __init__(self, kite=None, order_mgr=None, risk_mgr=None,
                 intraday_strat=None, swing_strat=None, ticker=None, data=None):
        self.kite           = kite
        self.order_mgr      = order_mgr
        self.risk_mgr       = risk_mgr
        self.intraday_strat = intraday_strat
        self.swing_strat    = swing_strat
        self.ticker         = ticker
        self.data           = data

        self._running = False

    # ─────────────────────────────────────────────────────────
    # STANDALONE MODE (sirf dashboard run karo, bot ke bina)
    # ─────────────────────────────────────────────────────────

    def run_standalone(self):
        """
        Dashboard standalone run karo (bot ke saath connect karke).
        Main bot alag chal raha hota hai; dashboard uska status dikhata hai.
        """
        setup_logger("WARNING")   # Dashboard mein sirf warnings
        errors, warnings = validate_config()
        if errors:
            for e in errors:
                console.print(f"[red]❌ {e}[/red]")
            sys.exit(1)

        # Login
        try:
            from auth import KiteAuth
            from data import DataFetcher
            from order_manager import OrderManager
            from risk_manager import RiskManager
            from strategies.intraday import IntradayStrategy
            from strategies.swing import SwingStrategy

            console.print("[yellow]🔐 Connecting to Zerodha...[/yellow]")
            auth = KiteAuth()
            self.kite = auth.get_kite_instance()

            self.data         = DataFetcher(self.kite)
            self.order_mgr    = OrderManager(self.kite)
            self.risk_mgr     = RiskManager(TOTAL_CAPITAL)
            self.intraday_strat = IntradayStrategy()
            self.swing_strat    = SwingStrategy()

            console.print("[green]✅ Connected! Starting dashboard...[/green]")
            time.sleep(1)

        except Exception as e:
            console.print(f"[red]❌ Connection failed: {e}[/red]")
            console.print("[yellow]Running in DEMO mode...[/yellow]")

        self._running = True
        self._run_live()

    def _run_live(self):
        """Rich Live display loop"""
        with Live(
            self._build_layout(),
            refresh_per_second=1 / self.REFRESH_INTERVAL,
            screen=True,
            console=console,
        ) as live:
            try:
                while self._running:
                    live.update(self._build_layout())
                    time.sleep(self.REFRESH_INTERVAL)
            except KeyboardInterrupt:
                self._running = False
                console.print("\n[yellow]Dashboard stopped.[/yellow]")

    # ─────────────────────────────────────────────────────────
    # LAYOUT BUILDER
    # ─────────────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        """Poora dashboard layout banao"""
        layout = Layout()

        layout.split_column(
            Layout(name="header",   size=7),
            Layout(name="middle",   size=18),
            Layout(name="bottom",   size=14),
            Layout(name="footer",   size=3),
        )

        layout["middle"].split_row(
            Layout(name="pnl",       ratio=1),
            Layout(name="positions", ratio=2),
        )

        layout["bottom"].split_row(
            Layout(name="trades",    ratio=2),
            Layout(name="watchlist", ratio=1),
        )

        # Fill sections
        layout["header"].update(self._build_header())
        layout["pnl"].update(self._build_pnl_panel())
        layout["positions"].update(self._build_positions_panel())
        layout["trades"].update(self._build_trades_panel())
        layout["watchlist"].update(self._build_watchlist_panel())
        layout["footer"].update(self._build_footer())

        return layout

    # ─────────────────────────────────────────────────────────
    # PANELS
    # ─────────────────────────────────────────────────────────

    def _build_header(self) -> Panel:
        """Top header - status aur time"""
        now = datetime.now(IST_tz)
        mode_str = "📄 PAPER TRADING" if IS_PAPER_TRADING else "🔴 LIVE TRADING"
        mode_color = "yellow" if IS_PAPER_TRADING else "red"

        # Market status
        market_open  = now.time() >= datetime.strptime("09:15", "%H:%M").time()
        market_close = now.time() >= datetime.strptime("15:30", "%H:%M").time()
        if market_open and not market_close:
            market_status = "[green]🟢 MARKET OPEN[/green]"
        elif not market_open:
            market_status = "[yellow]🟡 PRE-MARKET[/yellow]"
        else:
            market_status = "[red]🔴 MARKET CLOSED[/red]"

        # Ticker status
        if self.ticker:
            ticker_status = "[green]📡 LIVE[/green]" if self.ticker.is_connected else "[red]📡 OFFLINE[/red]"
        else:
            ticker_status = "[dim]📡 N/A[/dim]"

        header_text = Text()
        header_text.append("  🤖 ZERODHA ALGO TRADING DASHBOARD  ", style="bold white on dark_blue")
        header_text.append(f"\n  [{mode_color}]{mode_str}[/{mode_color}]")
        header_text.append(f"  |  {market_status}")
        header_text.append(f"  |  {ticker_status}")
        header_text.append(f"  |  Capital: [cyan]₹{TOTAL_CAPITAL:,.0f}[/cyan]")
        header_text.append(f"\n  🕐 {now.strftime('%A, %d %B %Y  %H:%M:%S IST')}")

        return Panel(
            Align.center(header_text),
            border_style="blue",
            padding=(0, 1),
        )

    def _build_pnl_panel(self) -> Panel:
        """P&L summary panel"""
        stats = self._get_stats()

        pnl       = stats.get("daily_pnl", 0)
        pnl_pct   = stats.get("daily_pnl_pct", 0)
        trades    = stats.get("total_trades", 0)
        win_rate  = stats.get("win_rate", 0)
        winners   = stats.get("winners", 0)
        losers    = stats.get("losers", 0)
        capital   = stats.get("current_capital", TOTAL_CAPITAL)
        loss_used = stats.get("loss_used_pct", 0)
        halted    = stats.get("trading_halted", False)

        pnl_color = "green" if pnl >= 0 else "red"
        pnl_sign  = "+" if pnl >= 0 else ""

        status_text = "[bold red]🛑 HALTED[/bold red]" if halted else "[bold green]✅ ACTIVE[/bold green]"

        content = (
            f"[bold]Status:[/bold] {status_text}\n\n"
            f"[bold]Today's P&L:[/bold]\n"
            f"  [{pnl_color}]{pnl_sign}₹{pnl:,.2f}  ({pnl_sign}{pnl_pct:.2f}%)[/{pnl_color}]\n\n"
            f"[bold]Capital:[/bold] [cyan]₹{capital:,.0f}[/cyan]\n\n"
            f"[bold]Trades:[/bold] {trades}  "
            f"([green]W:{winners}[/green]/[red]L:{losers}[/red])\n"
            f"[bold]Win Rate:[/bold] [{'green' if win_rate >= 50 else 'red'}]{win_rate:.1f}%[/]\n\n"
            f"[bold]Daily Loss Used:[/bold]\n"
            f"  [{'red' if loss_used > 70 else 'yellow' if loss_used > 40 else 'green'}]{loss_used:.1f}%[/] "
            f"of ₹{MAX_DAILY_LOSS_AMOUNT:,.0f} limit"
        )

        return Panel(content, title="[bold yellow]📊 P&L Summary[/bold yellow]",
                     border_style="yellow", padding=(0, 1))

    def _build_positions_panel(self) -> Panel:
        """Active positions table"""
        table = Table(
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        table.add_column("Symbol",    style="bold white", width=12)
        table.add_column("Type",      width=8)
        table.add_column("Dir",       width=6)
        table.add_column("Qty",       justify="right", width=6)
        table.add_column("Entry ₹",   justify="right", width=10)
        table.add_column("LTP ₹",     justify="right", width=10)
        table.add_column("P&L ₹",     justify="right", width=10)
        table.add_column("SL ₹",      justify="right", width=10)
        table.add_column("Target ₹",  justify="right", width=10)

        rows = self._get_positions_data()

        if not rows:
            table.add_row("[dim]No active positions[/dim]", *["─"]*8)
        else:
            for row in rows:
                pnl_val   = row.get("pnl", 0)
                pnl_color = "green" if pnl_val >= 0 else "red"
                pnl_str   = f"{'+'if pnl_val>=0 else ''}₹{pnl_val:,.0f}"
                dir_color = "green" if row["direction"] == "LONG" else "red"
                dir_arrow = "▲" if row["direction"] == "LONG" else "▼"

                table.add_row(
                    row["symbol"],
                    f"[dim]{row['strategy']}[/dim]",
                    f"[{dir_color}]{dir_arrow} {row['direction']}[/{dir_color}]",
                    str(row["qty"]),
                    f"₹{row['entry']:.2f}",
                    f"₹{row.get('ltp', row['entry']):.2f}",
                    f"[{pnl_color}]{pnl_str}[/{pnl_color}]",
                    f"[red]₹{row['sl']:.2f}[/red]",
                    f"[green]₹{row['target']:.2f}[/green]",
                )

        return Panel(table, title="[bold cyan]📈 Active Positions[/bold cyan]",
                     border_style="cyan", padding=(0, 0))

    def _build_trades_panel(self) -> Panel:
        """Today's trades history"""
        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold white",
            expand=True,
        )
        table.add_column("Time",    width=8)
        table.add_column("Symbol",  width=12)
        table.add_column("Dir",     width=6)
        table.add_column("Entry ₹", justify="right", width=9)
        table.add_column("Exit ₹",  justify="right", width=9)
        table.add_column("Qty",     justify="right", width=5)
        table.add_column("P&L ₹",   justify="right", width=10)
        table.add_column("Result",  width=6)
        table.add_column("Reason",  width=20)

        trades = self._get_trades()

        if not trades:
            table.add_row("[dim]No trades yet today[/dim]", *["─"]*8)
        else:
            # Last 10 trades dikhao
            for t in trades[-10:]:
                pnl_color  = "green" if t["pnl"] >= 0 else "red"
                result_str = "[green]WIN ✓[/green]" if t["pnl"] >= 0 else "[red]LOSS ✗[/red]"
                dir_color  = "green" if t["direction"] == "LONG" else "red"

                table.add_row(
                    t.get("exit_time", "─"),
                    t["symbol"],
                    f"[{dir_color}]{t['direction']}[/{dir_color}]",
                    f"₹{t['entry']:.2f}",
                    f"₹{t['exit']:.2f}",
                    str(t["qty"]),
                    f"[{pnl_color}]{'+'if t['pnl']>=0 else ''}₹{t['pnl']:,.0f}[/{pnl_color}]",
                    result_str,
                    f"[dim]{t.get('exit_reason','')[:20]}[/dim]",
                )

        return Panel(table, title="[bold white]📋 Today's Trades[/bold white]",
                     border_style="white", padding=(0, 0))

    def _build_watchlist_panel(self) -> Panel:
        """Live watchlist prices"""
        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold magenta",
            expand=True,
        )
        table.add_column("Symbol",  width=12)
        table.add_column("LTP ₹",   justify="right", width=10)
        table.add_column("Chg%",    justify="right", width=8)

        prices = self._get_watchlist_prices()

        if not prices:
            table.add_row("[dim]No live data[/dim]", "─", "─")
        else:
            for sym, data in list(prices.items())[:12]:
                chg_pct  = data.get("change_pct", 0)
                chg_col  = "green" if chg_pct >= 0 else "red"
                chg_sign = "+" if chg_pct >= 0 else ""

                table.add_row(
                    sym,
                    f"₹{data['ltp']:,.2f}",
                    f"[{chg_col}]{chg_sign}{chg_pct:.2f}%[/{chg_col}]",
                )

        return Panel(table, title="[bold magenta]📡 Watchlist[/bold magenta]",
                     border_style="magenta", padding=(0, 0))

    def _build_footer(self) -> Panel:
        """Footer - keyboard shortcuts"""
        return Panel(
            "[dim]  [Q] Quit  |  [R] Refresh  |  "
            "Ctrl+C to stop bot  |  "
            f"Last update: {datetime.now(IST_tz).strftime('%H:%M:%S')}[/dim]",
            border_style="dim",
            padding=(0, 1),
        )

    # ─────────────────────────────────────────────────────────
    # DATA HELPERS
    # ─────────────────────────────────────────────────────────

    def _get_stats(self) -> dict:
        if self.risk_mgr:
            return self.risk_mgr.get_daily_stats()
        return {
            "daily_pnl": 0, "daily_pnl_pct": 0, "total_trades": 0,
            "win_rate": 0, "winners": 0, "losers": 0,
            "current_capital": TOTAL_CAPITAL, "loss_used_pct": 0,
            "trading_halted": False,
        }

    def _get_positions_data(self) -> list[dict]:
        rows = []
        ltp_map = {}
        if self.ticker:
            ltp_map = self.ticker.get_ltp_map()

        # Intraday positions
        if self.intraday_strat:
            for symbol, pos in self.intraday_strat.get_active_positions().items():
                ltp = ltp_map.get(symbol, pos["entry_price"])
                pnl = (ltp - pos["entry_price"]) * pos.get("quantity", 1)
                if pos["direction"] == "SHORT":
                    pnl = -pnl
                rows.append({
                    "symbol":    symbol,
                    "strategy":  "INTRA",
                    "direction": pos["direction"],
                    "qty":       pos.get("quantity", 1),
                    "entry":     pos["entry_price"],
                    "ltp":       ltp,
                    "pnl":       round(pnl, 2),
                    "sl":        pos["stop_loss"],
                    "target":    pos["target"],
                })

        # Swing positions
        if self.swing_strat:
            for symbol, pos in self.swing_strat.get_active_positions().items():
                ltp = ltp_map.get(symbol, pos["entry_price"])
                pnl = (ltp - pos["entry_price"]) * pos.get("quantity", 1)
                rows.append({
                    "symbol":    symbol,
                    "strategy":  "SWING",
                    "direction": pos["direction"],
                    "qty":       pos.get("quantity", 1),
                    "entry":     pos["entry_price"],
                    "ltp":       ltp,
                    "pnl":       round(pnl, 2),
                    "sl":        pos["stop_loss"],
                    "target":    pos["target"],
                })

        return rows

    def _get_trades(self) -> list[dict]:
        if self.risk_mgr:
            return self.risk_mgr.get_trade_history()
        return []

    def _get_watchlist_prices(self) -> dict:
        """Live prices from ticker ya Kite API"""
        prices = {}

        # Ticker se try karo pehle (faster)
        if self.ticker:
            ticks = self.ticker.get_all_ticks()
            for symbol, tick in ticks.items():
                prices[symbol] = {
                    "ltp":        tick.get("ltp", 0),
                    "change_pct": tick.get("change_pct", 0),
                }
            if prices:
                return prices

        # Fallback: Kite API
        if self.kite and self.data:
            symbols = INTRADAY_CONFIG["watchlist"][:10]
            try:
                ltp_data = self.data.get_ltp(symbols)
                for sym, ltp in ltp_data.items():
                    prices[sym] = {"ltp": ltp, "change_pct": 0}
            except Exception:
                pass

        return prices


# ─────────────────────────────────────────────────────────────
# QUICK REPORT: Sirf stats print karo (no live loop)
# ─────────────────────────────────────────────────────────────

def print_quick_report():
    """Aaj ki quick P&L report terminal mein print karo"""
    console.print("\n[bold cyan]📊 ALGO TRADING - QUICK REPORT[/bold cyan]")
    console.print(f"[dim]{datetime.now(IST_tz).strftime('%d %b %Y  %H:%M:%S IST')}[/dim]\n")

    console.print(Panel(
        f"[yellow]Mode:[/yellow] {'PAPER' if IS_PAPER_TRADING else 'LIVE'}\n"
        f"[yellow]Capital:[/yellow] ₹{TOTAL_CAPITAL:,.0f}\n"
        f"[yellow]Max Daily Loss:[/yellow] ₹{MAX_DAILY_LOSS_AMOUNT:,.0f}\n"
        f"[yellow]Intraday Symbols:[/yellow] {len(INTRADAY_CONFIG['watchlist'])}\n"
        f"[yellow]Swing Symbols:[/yellow] {len(SWING_CONFIG['watchlist'])}",
        title="[bold]Config[/bold]",
        border_style="yellow",
    ))


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        print_quick_report()
    else:
        dashboard = TradingDashboard()
        dashboard.run_standalone()
