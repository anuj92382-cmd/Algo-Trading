"""
risk_manager.py - Risk Management Module
Capital protection, position sizing, daily loss limits

Rules:
  - Max risk per trade: 1% of capital
  - Max daily loss: 3% of capital
  - Max open positions: 5
  - Max position size: 20% of capital
  - No trading after daily loss limit hit
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

import pytz

from config import (
    TOTAL_CAPITAL, MAX_RISK_PER_TRADE, MAX_DAILY_LOSS_AMOUNT,
    MAX_OPEN_POSITIONS, MAX_POSITION_SIZE_PCT
)

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


@dataclass
class TradeRecord:
    """Ek completed trade ka record"""
    symbol:       str
    direction:    str       # "LONG" or "SHORT"
    entry_price:  float
    exit_price:   float
    quantity:     int
    entry_time:   datetime
    exit_time:    datetime = field(default_factory=lambda: datetime.now(IST_tz))
    stop_loss:    float    = 0.0
    target:       float    = 0.0
    strategy:     str      = ""
    exit_reason:  str      = ""

    @property
    def pnl(self) -> float:
        if self.direction == "LONG":
            return (self.exit_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.exit_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        return self.pnl / (self.entry_price * self.quantity) * 100

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def holding_time(self) -> float:
        """Hours mein holding time"""
        return (self.exit_time - self.entry_time).total_seconds() / 3600


class RiskManager:
    """
    Trading risk manage karta hai.
    
    Har trade se pehle check karta hai:
    1. Daily loss limit hit toh nahi hua?
    2. Max positions se zyada toh nahi?
    3. Position size sahi hai?
    4. Stop loss valid hai?
    """

    def __init__(self, capital: float = TOTAL_CAPITAL):
        self.initial_capital = capital
        self.current_capital = capital
        self.max_risk_per_trade = MAX_RISK_PER_TRADE
        self.max_daily_loss = MAX_DAILY_LOSS_AMOUNT
        self.max_positions = MAX_OPEN_POSITIONS
        self.max_position_pct = MAX_POSITION_SIZE_PCT

        # Daily tracking
        self._daily_pnl: float = 0.0
        self._today: date = date.today()
        self._trades_today: list[TradeRecord] = []
        self._active_positions: dict[str, dict] = {}
        self._trading_halted: bool = False
        self._halt_reason: str = ""

        logger.info(
            f"RiskManager initialized | Capital: ₹{capital:,.0f} | "
            f"Max risk/trade: ₹{self.max_risk_per_trade:,.0f} | "
            f"Max daily loss: ₹{self.max_daily_loss:,.0f}"
        )

    # ─────────────────────────────────────────────────────────
    # PRE-TRADE CHECKS
    # ─────────────────────────────────────────────────────────

    def can_trade(self, symbol: str = "") -> tuple[bool, str]:
        """
        Kya ab trade kar sakte hain?
        
        Returns:
            (True/False, reason)
        """
        self._reset_daily_if_needed()

        # 1. Trading halted check
        if self._trading_halted:
            return False, f"Trading halted: {self._halt_reason}"

        # 2. Daily loss limit
        if self._daily_pnl <= -self.max_daily_loss:
            self._halt_trading(f"Daily loss limit hit: ₹{self._daily_pnl:.2f}")
            return False, f"Daily loss limit reached (₹{abs(self._daily_pnl):.0f})"

        # 3. Max open positions
        if len(self._active_positions) >= self.max_positions:
            return False, f"Max positions reached ({len(self._active_positions)}/{self.max_positions})"

        # 4. Symbol already in position?
        if symbol and symbol in self._active_positions:
            return False, f"{symbol} already in active position"

        return True, "OK"

    def calculate_position_size(
        self,
        price: float,
        stop_loss: float,
        risk_amount: Optional[float] = None,
        product: str = "MIS",
    ) -> int:
        """
        Position size calculate karo based on risk.
        
        Formula: Quantity = Risk Amount / (Price - Stop Loss)
        With 5X leverage for Intraday (MIS).
        
        Args:
            price:       Entry price
            stop_loss:   Stop loss price
            risk_amount: Custom risk amount (default: max_risk_per_trade)
            product:     "MIS" (5X leverage) or "CNC" (1X)
            
        Returns:
            Quantity (shares)
        """
        if risk_amount is None:
            risk_amount = self.max_risk_per_trade

        risk_per_share = abs(price - stop_loss)
        if risk_per_share <= 0:
            logger.warning("Invalid stop loss - risk per share is 0")
            return 0

        # Risk-based quantity
        qty_by_risk = int(risk_amount / risk_per_share)

        # Capital-based max quantity (with 5X leverage for MIS intraday)
        is_mis = str(product).upper() == "MIS"
        leverage = 5.0 if is_mis else 1.0
        max_position_value = self.current_capital * (self.max_position_pct / 100) * leverage
        qty_by_capital = int(max_position_value / price)

        # Jo bhi kam ho
        qty = min(qty_by_risk, qty_by_capital)
        qty = max(qty, 1)  # Minimum 1 share

        logger.debug(
            f"Position size: {qty} shares | Price: ₹{price:.2f} | "
            f"SL: ₹{stop_loss:.2f} | Leverage: {leverage}X | Risk: ₹{risk_per_share * qty:.2f}"
        )
        return qty

    def validate_trade(
        self,
        symbol: str,
        price: float,
        stop_loss: float,
        target: float,
        quantity: int,
        direction: str = "LONG",
        product: str = "MIS",
    ) -> tuple[bool, str]:
        """
        Trade valid hai check karo.
        
        Returns:
            (True/False, message)
        """
        # 1. Basic checks
        can, reason = self.can_trade(symbol)
        if not can:
            return False, reason

        # 2. Stop loss valid?
        if direction == "LONG" and stop_loss >= price:
            return False, f"Stop loss (₹{stop_loss:.2f}) price se upar nahi ho sakta"
        if direction == "SHORT" and stop_loss <= price:
            return False, f"Stop loss (₹{stop_loss:.2f}) price se niche nahi ho sakta"

        # 3. Target valid?
        if direction == "LONG" and target <= price:
            return False, f"Target (₹{target:.2f}) price se upar hona chahiye"
        if direction == "SHORT" and target >= price:
            return False, f"Target (₹{target:.2f}) price se niche hona chahiye"

        # 4. Risk:Reward check (minimum 1:1.5)
        risk = abs(price - stop_loss)
        reward = abs(target - price)
        rr = reward / risk if risk > 0 else 0
        if rr < 1.5:
            return False, f"Risk:Reward ratio too low ({rr:.1f}). Minimum 1:1.5 chahiye"

        # 5. Position margin check (5X leverage for MIS intraday)
        is_mis = str(product).upper() == "MIS"
        margin_required = (price * quantity) / 5.0 if is_mis else (price * quantity)
        max_allowed_margin = self.current_capital * (self.max_position_pct / 100)
        if margin_required > max_allowed_margin:
            lev_lbl = "5X Margin: ₹" if is_mis else "₹"
            return False, f"Required margin {lev_lbl}{margin_required:,.0f} too high (max allowed ₹{max_allowed_margin:,.0f})"

        # 6. Risk amount check
        trade_risk = risk * quantity
        if trade_risk > self.max_risk_per_trade * 1.1:  # 10% tolerance
            return False, f"Trade risk ₹{trade_risk:.0f} exceeds limit ₹{self.max_risk_per_trade:.0f}"

        return True, f"Valid trade | R:R={rr:.1f} | Risk: ₹{trade_risk:.0f}"

    # ─────────────────────────────────────────────────────────
    # TRADE LIFECYCLE
    # ─────────────────────────────────────────────────────────

    def register_entry(
        self,
        symbol: str,
        direction: str,
        price: float,
        quantity: int,
        stop_loss: float,
        target: float,
        strategy: str = "",
    ):
        """Trade entry register karo"""
        self._active_positions[symbol] = {
            "direction":   direction,
            "entry_price": price,
            "quantity":    quantity,
            "stop_loss":   stop_loss,
            "target":      target,
            "entry_time":  datetime.now(IST_tz),
            "strategy":    strategy,
        }
        logger.info(
            f"📝 Entry registered: {symbol} {direction} {quantity} @ ₹{price:.2f} | "
            f"SL: ₹{stop_loss:.2f} | Target: ₹{target:.2f}"
        )

    def register_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str = "",
    ) -> Optional[TradeRecord]:
        """
        Trade exit register karo aur P&L calculate karo.
        
        Returns:
            TradeRecord with P&L details
        """
        pos = self._active_positions.pop(symbol, None)
        if not pos:
            logger.warning(f"No active position found for {symbol}")
            return None

        record = TradeRecord(
            symbol=symbol,
            direction=pos["direction"],
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            quantity=pos["quantity"],
            entry_time=pos["entry_time"],
            exit_time=datetime.now(IST_tz),
            stop_loss=pos["stop_loss"],
            target=pos["target"],
            strategy=pos.get("strategy", ""),
            exit_reason=exit_reason,
        )

        # P&L update karo
        self._daily_pnl += record.pnl
        self.current_capital += record.pnl
        self._trades_today.append(record)

        emoji = "✅" if record.is_winner else "❌"
        logger.info(
            f"{emoji} Exit: {symbol} @ ₹{exit_price:.2f} | "
            f"P&L: ₹{record.pnl:+.2f} ({record.pnl_pct:+.1f}%) | "
            f"Daily P&L: ₹{self._daily_pnl:+.2f} | {exit_reason}"
        )

        # Daily loss check karo
        if self._daily_pnl <= -self.max_daily_loss:
            self._halt_trading(f"Daily loss limit: ₹{abs(self._daily_pnl):.0f}")

        return record

    def update_stop_loss(self, symbol: str, new_sl: float):
        """Stop loss update karo (trailing SL ke liye)"""
        if symbol in self._active_positions:
            old_sl = self._active_positions[symbol]["stop_loss"]
            self._active_positions[symbol]["stop_loss"] = new_sl
            logger.info(f"📌 SL updated: {symbol} ₹{old_sl:.2f} → ₹{new_sl:.2f}")

    # ─────────────────────────────────────────────────────────
    # REPORTING
    # ─────────────────────────────────────────────────────────

    def get_daily_stats(self) -> dict:
        """Aaj ke trading stats"""
        self._reset_daily_if_needed()
        trades = self._trades_today
        winners = [t for t in trades if t.is_winner]
        losers = [t for t in trades if not t.is_winner]

        total_trades = len(trades)
        win_rate = len(winners) / total_trades * 100 if total_trades > 0 else 0
        avg_win = sum(t.pnl for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t.pnl for t in losers) / len(losers) if losers else 0
        profit_factor = abs(avg_win * len(winners) / (avg_loss * len(losers))) if losers and avg_loss != 0 else float("inf")

        # Daily loss remaining
        loss_remaining = self.max_daily_loss + self._daily_pnl  # positive = remaining headroom
        loss_used_pct = abs(min(self._daily_pnl, 0)) / self.max_daily_loss * 100

        return {
            "date":            date.today().isoformat(),
            "total_trades":    total_trades,
            "winners":         len(winners),
            "losers":          len(losers),
            "win_rate":        round(win_rate, 1),
            "daily_pnl":       round(self._daily_pnl, 2),
            "daily_pnl_pct":   round(self._daily_pnl / self.initial_capital * 100, 2),
            "avg_win":         round(avg_win, 2),
            "avg_loss":        round(avg_loss, 2),
            "profit_factor":   round(profit_factor, 2),
            "current_capital": round(self.current_capital, 2),
            "active_positions": len(self._active_positions),
            "loss_used_pct":   round(loss_used_pct, 1),
            "loss_remaining":  round(loss_remaining, 2),
            "trading_halted":  self._trading_halted,
            "halt_reason":     self._halt_reason,
        }

    def get_trade_history(self) -> list[dict]:
        """Aaj ke saare trades ka history"""
        return [
            {
                "symbol":      t.symbol,
                "direction":   t.direction,
                "entry":       round(t.entry_price, 2),
                "exit":        round(t.exit_price, 2),
                "qty":         t.quantity,
                "pnl":         round(t.pnl, 2),
                "pnl_pct":     round(t.pnl_pct, 2),
                "result":      "WIN" if t.is_winner else "LOSS",
                "strategy":    t.strategy,
                "exit_reason": t.exit_reason,
                "held_hrs":    round(t.holding_time, 2),
                "entry_time":  t.entry_time.strftime("%H:%M:%S"),
                "exit_time":   t.exit_time.strftime("%H:%M:%S"),
            }
            for t in self._trades_today
        ]

    def get_active_positions_risk(self) -> list[dict]:
        """Active positions ki unrealized risk"""
        result = []
        for symbol, pos in self._active_positions.items():
            max_loss = abs(pos["entry_price"] - pos["stop_loss"]) * pos["quantity"]
            result.append({
                "symbol":     symbol,
                "direction":  pos["direction"],
                "entry":      pos["entry_price"],
                "stop_loss":  pos["stop_loss"],
                "target":     pos["target"],
                "qty":        pos["quantity"],
                "max_loss":   round(max_loss, 2),
                "strategy":   pos.get("strategy", ""),
            })
        return result

    def get_status_bar(self) -> str:
        """One-line status string for display"""
        stats = self.get_daily_stats()
        status = "🔴 HALTED" if self._trading_halted else "🟢 ACTIVE"
        return (
            f"{status} | P&L: ₹{stats['daily_pnl']:+.0f} ({stats['daily_pnl_pct']:+.1f}%) | "
            f"Trades: {stats['total_trades']} ({stats['win_rate']:.0f}% WR) | "
            f"Positions: {stats['active_positions']}/{self.max_positions} | "
            f"Capital: ₹{stats['current_capital']:,.0f}"
        )

    # ─────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────

    def _halt_trading(self, reason: str):
        """Trading temporarily band karo"""
        self._trading_halted = True
        self._halt_reason = reason
        logger.warning(f"🛑 TRADING HALTED: {reason}")

    def resume_trading(self):
        """Trading resume karo (manual)"""
        self._trading_halted = False
        self._halt_reason = ""
        logger.info("✅ Trading resumed manually")

    def _reset_daily_if_needed(self):
        """Naya din aane pe daily counters reset karo"""
        today = date.today()
        if today != self._today:
            logger.info(f"📅 New trading day: {today}. Resetting daily stats.")
            self._today = today
            self._daily_pnl = 0.0
            self._trades_today.clear()
            self._trading_halted = False
            self._halt_reason = ""

    def force_reset(self):
        """Manual reset (testing ke liye)"""
        self._daily_pnl = 0.0
        self._trades_today.clear()
        self._active_positions.clear()
        self._trading_halted = False
        logger.warning("⚠️  Risk manager force reset")
