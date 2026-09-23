"""
order_manager.py - Order Management Module
Zerodha Kite ke through orders place, modify, cancel aur track karo

Paper Trading mode mein real orders nahi jaate - sirf simulate hote hain
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from pathlib import Path

import pytz

from kiteconnect import KiteConnect

from config import (
    IS_PAPER_TRADING, TRADING_MODE, KITE_API,
    INTRADAY_CONFIG, SWING_CONFIG
)

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class OrderStatus(Enum):
    PENDING   = "PENDING"
    OPEN      = "OPEN"
    COMPLETE  = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED  = "REJECTED"
    PAPER     = "PAPER"       # Paper trade simulate


@dataclass
class Order:
    """Ek order ki poori details"""
    order_id:      str
    symbol:        str
    exchange:      str
    transaction:   str        # "BUY" ya "SELL"
    order_type:    str        # "MARKET", "LIMIT", "SL", "SL-M"
    product:       str        # "MIS" (intraday) ya "CNC" (delivery)
    quantity:      int
    price:         float      # 0 for MARKET orders
    trigger_price: float = 0.0
    status:        OrderStatus = OrderStatus.PENDING
    filled_qty:    int    = 0
    avg_price:     float  = 0.0
    tag:           str    = ""   # Strategy tag
    timestamp:     datetime = field(default_factory=lambda: datetime.now(IST_tz))
    exchange_order_id: str = ""
    message:       str    = ""   # Error message if rejected

    @property
    def is_buy(self) -> bool:
        return self.transaction == "BUY"

    @property
    def value(self) -> float:
        """Order ki total value"""
        p = self.avg_price if self.avg_price > 0 else self.price
        return p * self.quantity

    def __str__(self):
        return (
            f"[{self.status.value}] {self.transaction} {self.quantity} {self.symbol} "
            f"@ ₹{self.price:.2f} | ID: {self.order_id[:8]}... | {self.tag}"
        )


class OrderManager:
    """
    Saare orders manage karta hai.

    Paper mode mein:  Orders simulate hote hain, koi real API call nahi
    Live mode mein:   Real Kite API se orders jaate hain
    """

    def __init__(self, kite: KiteConnect):
        self.kite = kite
        self.is_paper = IS_PAPER_TRADING

        # In-memory order book
        self._orders: dict[str, Order] = {}
        self._trade_log: list[dict] = []

        mode_str = "📄 PAPER TRADING" if self.is_paper else "🔴 LIVE TRADING"
        logger.info(f"OrderManager initialized - {mode_str}")

    # ─────────────────────────────────────────────────────────
    # PLACE ORDERS
    # ─────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        transaction: str,       # "BUY" or "SELL"
        quantity: int,
        exchange: str = "NSE",
        product: str = "MIS",   # MIS=intraday, CNC=delivery
        tag: str = "",
    ) -> Optional[Order]:
        """Market order place karo (turant execute hoga)"""
        return self._place_order(
            symbol=symbol,
            exchange=exchange,
            transaction=transaction,
            order_type="MARKET",
            product=product,
            quantity=quantity,
            price=0,
            trigger_price=0,
            tag=tag,
        )

    def place_limit_order(
        self,
        symbol: str,
        transaction: str,
        quantity: int,
        price: float,
        exchange: str = "NSE",
        product: str = "MIS",
        tag: str = "",
    ) -> Optional[Order]:
        """Limit order place karo (specific price pe execute hoga)"""
        return self._place_order(
            symbol=symbol,
            exchange=exchange,
            transaction=transaction,
            order_type="LIMIT",
            product=product,
            quantity=quantity,
            price=price,
            trigger_price=0,
            tag=tag,
        )

    def place_sl_order(
        self,
        symbol: str,
        transaction: str,
        quantity: int,
        price: float,
        trigger_price: float,
        exchange: str = "NSE",
        product: str = "MIS",
        tag: str = "",
    ) -> Optional[Order]:
        """Stop Loss order place karo"""
        return self._place_order(
            symbol=symbol,
            exchange=exchange,
            transaction=transaction,
            order_type="SL",
            product=product,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            tag=tag,
        )

    def place_sl_market_order(
        self,
        symbol: str,
        transaction: str,
        quantity: int,
        trigger_price: float,
        exchange: str = "NSE",
        product: str = "MIS",
        tag: str = "",
    ) -> Optional[Order]:
        """Stop Loss Market order (trigger pe market order)"""
        return self._place_order(
            symbol=symbol,
            exchange=exchange,
            transaction=transaction,
            order_type="SL-M",
            product=product,
            quantity=quantity,
            price=0,
            trigger_price=trigger_price,
            tag=tag,
        )

    # ─────────────────────────────────────────────────────────
    # BRACKET ORDER (Entry + SL + Target ek saath)
    # ─────────────────────────────────────────────────────────

    def place_bracket_order(
        self,
        symbol: str,
        transaction: str,
        quantity: int,
        entry_price: float,
        stop_loss_points: float,
        take_profit_points: float,
        exchange: str = "NSE",
        tag: str = "",
    ) -> Optional[str]:
        """
        Bracket Order: Entry + SL + Target ek hi order mein.
        Note: Kite Connect v3 mein CO/BO support limited hai.
        """
        if self.is_paper:
            order_id = self._generate_paper_id()
            logger.info(
                f"📄 PAPER Bracket Order: {transaction} {symbol} {quantity} @ ₹{entry_price:.2f} | "
                f"SL pts: {stop_loss_points} | TP pts: {take_profit_points}"
            )
            return order_id

        try:
            variety = self.kite.VARIETY_BO
            order_id = self.kite.place_order(
                variety=variety,
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=transaction,
                quantity=quantity,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                product=self.kite.PRODUCT_MIS,
                price=entry_price,
                squareoff=take_profit_points,
                stoploss=stop_loss_points,
                tag=tag[:20] if tag else "",
            )
            logger.info(f"✅ Bracket order placed: {order_id}")
            return order_id

        except Exception as e:
            logger.error(f"Bracket order error {symbol}: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    # MODIFY & CANCEL
    # ─────────────────────────────────────────────────────────

    def modify_order(
        self,
        order_id: str,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        quantity: Optional[int] = None,
    ) -> bool:
        """Pending order modify karo"""
        if self.is_paper:
            order = self._orders.get(order_id)
            if order:
                if price:
                    order.price = price
                if trigger_price:
                    order.trigger_price = trigger_price
                if quantity:
                    order.quantity = quantity
                logger.info(f"📄 PAPER Order modified: {order_id[:8]}")
            return True

        try:
            order = self._orders.get(order_id)
            if not order:
                logger.warning(f"Order not found: {order_id}")
                return False

            params = {"order_id": order_id, "variety": self.kite.VARIETY_REGULAR}
            if price is not None:
                params["price"] = price
            if trigger_price is not None:
                params["trigger_price"] = trigger_price
            if quantity is not None:
                params["quantity"] = quantity

            self.kite.modify_order(**params)
            logger.info(f"✅ Order modified: {order_id[:8]}")
            return True

        except Exception as e:
            logger.error(f"Order modify error {order_id}: {e}")
            return False

    def cancel_order(self, order_id: str) -> bool:
        """Order cancel karo"""
        if self.is_paper:
            order = self._orders.get(order_id)
            if order:
                order.status = OrderStatus.CANCELLED
                logger.info(f"📄 PAPER Order cancelled: {order_id[:8]}")
            return True

        try:
            self.kite.cancel_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id
            )
            if order_id in self._orders:
                self._orders[order_id].status = OrderStatus.CANCELLED
            logger.info(f"✅ Order cancelled: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Cancel order error {order_id}: {e}")
            return False

    def cancel_all_open_orders(self) -> int:
        """Saare open orders cancel karo"""
        cancelled = 0
        open_orders = self.get_open_orders()
        for order in open_orders:
            if self.cancel_order(order.order_id):
                cancelled += 1
        logger.info(f"✅ {cancelled} orders cancelled")
        return cancelled

    # ─────────────────────────────────────────────────────────
    # ORDER STATUS & POSITIONS
    # ─────────────────────────────────────────────────────────

    def get_orders(self) -> list[Order]:
        """Aaj ke saare orders"""
        if self.is_paper:
            return list(self._orders.values())

        try:
            orders = self.kite.orders()
            result = []
            for o in orders:
                order = Order(
                    order_id=o["order_id"],
                    symbol=o["tradingsymbol"],
                    exchange=o["exchange"],
                    transaction=o["transaction_type"],
                    order_type=o["order_type"],
                    product=o["product"],
                    quantity=o["quantity"],
                    price=o.get("price", 0),
                    trigger_price=o.get("trigger_price", 0),
                    status=OrderStatus(o["status"]) if o["status"] in [s.value for s in OrderStatus] else OrderStatus.OPEN,
                    filled_qty=o.get("filled_quantity", 0),
                    avg_price=o.get("average_price", 0),
                    message=o.get("status_message", ""),
                )
                result.append(order)
                self._orders[order.order_id] = order
            return result
        except Exception as e:
            logger.error(f"Get orders error: {e}")
            return list(self._orders.values())

    def get_open_orders(self) -> list[Order]:
        """Sirf open/pending orders"""
        return [o for o in self.get_orders()
                if o.status in (OrderStatus.OPEN, OrderStatus.PENDING)]

    def get_positions(self) -> dict:
        """Current open positions fetch karo"""
        if self.is_paper:
            return {"net": [], "day": []}

        try:
            return self.kite.positions()
        except Exception as e:
            logger.error(f"Get positions error: {e}")
            return {"net": [], "day": []}

    def get_holdings(self) -> list:
        """Portfolio holdings (CNC positions)"""
        if self.is_paper:
            return []
        try:
            return self.kite.holdings()
        except Exception as e:
            logger.error(f"Get holdings error: {e}")
            return []

    def get_pnl(self) -> dict:
        """Today's P&L calculate karo"""
        if self.is_paper:
            return self._calculate_paper_pnl()

        try:
            positions = self.kite.positions()
            day_positions = positions.get("day", [])
            total_pnl = sum(p.get("pnl", 0) for p in day_positions)
            return {
                "total_pnl":   round(total_pnl, 2),
                "positions":   day_positions,
                "count":       len(day_positions),
            }
        except Exception as e:
            logger.error(f"P&L fetch error: {e}")
            return {"total_pnl": 0, "positions": [], "count": 0}

    def get_funds(self) -> dict:
        """Available margin/funds check karo"""
        if self.is_paper:
            from config import TOTAL_CAPITAL
            try:
                p = PaperPortfolio()
                summary = p.get_margin_summary(self.kite, TOTAL_CAPITAL)
                return {
                    "available_cash":   summary["available_margin"],
                    "used_margin":      summary["used_margin"],
                    "available_margin": summary["available_margin"],
                    "net":              summary["net_capital"],
                    "leverage":         "5X (Intraday MIS)",
                }
            except Exception as e:
                logger.error(f"Paper funds error: {e}")
                return {
                    "available_cash":   TOTAL_CAPITAL,
                    "used_margin":      0,
                    "available_margin": TOTAL_CAPITAL,
                    "net":              TOTAL_CAPITAL,
                }
        try:
            margins = self.kite.margins()
            equity = margins.get("equity", {})
            return {
                "available_cash":   equity.get("available", {}).get("cash", 0),
                "used_margin":      equity.get("utilised", {}).get("debits", 0),
                "available_margin": equity.get("net", 0),
            }
        except Exception as e:
            logger.error(f"Funds fetch error: {e}")
            return {}

    # ─────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────

    def _place_order(
        self,
        symbol: str,
        exchange: str,
        transaction: str,
        order_type: str,
        product: str,
        quantity: int,
        price: float,
        trigger_price: float,
        tag: str = "",
    ) -> Optional[Order]:
        """Internal order placement (paper + live)"""

        # ── PAPER MODE ──────────────────────────────────────
        if self.is_paper:
            order_id = self._generate_paper_id()
            order = Order(
                order_id=order_id,
                symbol=symbol,
                exchange=exchange,
                transaction=transaction,
                order_type=order_type,
                product=product,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                status=OrderStatus.PAPER,
                filled_qty=quantity,
                avg_price=price,
                tag=tag,
            )
            self._orders[order_id] = order
            self._log_trade(order)
            logger.info(f"📄 PAPER {order}")
            return order

        # ── LIVE MODE ────────────────────────────────────────
        retry_count = 0
        while retry_count < KITE_API["max_retries"]:
            try:
                # Kite order type mapping
                kite_order_type = {
                    "MARKET": self.kite.ORDER_TYPE_MARKET,
                    "LIMIT":  self.kite.ORDER_TYPE_LIMIT,
                    "SL":     self.kite.ORDER_TYPE_SL,
                    "SL-M":   self.kite.ORDER_TYPE_SLM,
                }.get(order_type, self.kite.ORDER_TYPE_MARKET)

                kite_product = {
                    "MIS": self.kite.PRODUCT_MIS,
                    "CNC": self.kite.PRODUCT_CNC,
                    "NRML": self.kite.PRODUCT_NRML,
                }.get(product, self.kite.PRODUCT_MIS)

                kite_transaction = (
                    self.kite.TRANSACTION_TYPE_BUY
                    if transaction == "BUY"
                    else self.kite.TRANSACTION_TYPE_SELL
                )

                params = {
                    "variety":          self.kite.VARIETY_REGULAR,
                    "exchange":         exchange,
                    "tradingsymbol":    symbol,
                    "transaction_type": kite_transaction,
                    "quantity":         quantity,
                    "product":          kite_product,
                    "order_type":       kite_order_type,
                }

                if order_type in ("LIMIT", "SL") and price > 0:
                    params["price"] = price
                if order_type in ("SL", "SL-M") and trigger_price > 0:
                    params["trigger_price"] = trigger_price
                if tag:
                    params["tag"] = tag[:20]

                order_id = self.kite.place_order(**params)

                order = Order(
                    order_id=str(order_id),
                    symbol=symbol,
                    exchange=exchange,
                    transaction=transaction,
                    order_type=order_type,
                    product=product,
                    quantity=quantity,
                    price=price,
                    trigger_price=trigger_price,
                    status=OrderStatus.OPEN,
                    tag=tag,
                )
                self._orders[str(order_id)] = order
                self._log_trade(order)
                logger.info(f"✅ LIVE {order}")
                return order

            except Exception as e:
                retry_count += 1
                logger.error(f"Order error (attempt {retry_count}): {e}")
                if retry_count < KITE_API["max_retries"]:
                    time.sleep(KITE_API["retry_delay"])
                else:
                    logger.error(f"❌ Order failed after {retry_count} attempts: {symbol}")
                    return None

        return None

    def _generate_paper_id(self) -> str:
        """Paper trading ke liye fake order ID"""
        return f"PAPER_{uuid.uuid4().hex[:10].upper()}"

    def _log_trade(self, order: Order):
        """Trade log mein entry karo"""
        self._trade_log.append({
            "timestamp":   order.timestamp.isoformat(),
            "order_id":    order.order_id,
            "symbol":      order.symbol,
            "transaction": order.transaction,
            "order_type":  order.order_type,
            "product":     order.product,
            "quantity":    order.quantity,
            "price":       order.price,
            "status":      order.status.value,
            "tag":         order.tag,
            "mode":        "PAPER" if self.is_paper else "LIVE",
        })

    def _calculate_paper_pnl(self) -> dict:
        """Paper trading P&L calculate karo"""
        completed = [o for o in self._orders.values()
                     if o.status in (OrderStatus.COMPLETE, OrderStatus.PAPER)]
        # Simplified P&L (real tracking risk_manager mein hoga)
        return {
            "total_pnl": 0,
            "positions": [],
            "count":     len(completed),
            "note":      "Paper trading - detailed P&L in risk_manager",
        }

    def get_trade_log(self) -> list[dict]:
        """Aaj ka poora trade log"""
        return self._trade_log.copy()

    def get_order_count(self) -> dict:
        """Order statistics"""
        all_orders = list(self._orders.values())
        return {
            "total":     len(all_orders),
            "open":      sum(1 for o in all_orders if o.status in (OrderStatus.OPEN, OrderStatus.PENDING)),
            "complete":  sum(1 for o in all_orders if o.status in (OrderStatus.COMPLETE, OrderStatus.PAPER)),
            "cancelled": sum(1 for o in all_orders if o.status == OrderStatus.CANCELLED),
            "rejected":  sum(1 for o in all_orders if o.status == OrderStatus.REJECTED),
            "buys":      sum(1 for o in all_orders if o.is_buy),
            "sells":     sum(1 for o in all_orders if not o.is_buy),
        }



# ═════════════════════════════════════════════════════════════
# PAPER TRADING PORTFOLIO - Backtesting ke liye
# ═════════════════════════════════════════════════════════════

@dataclass
class PaperPosition:
    """Paper trading mein ek position"""
    symbol:        str
    exchange:      str
    quantity:      int              # +ve for long, -ve for short
    avg_price:     float            # average buy/sell price
    product:       str              # MIS / CNC
    entry_time:    datetime
    stop_loss:     float = 0.0
    target:        float = 0.0
    tag:           str = ""

    def pnl(self, current_price: float) -> float:
        """Current P&L calculate karo"""
        if self.quantity > 0:  # LONG
            return (current_price - self.avg_price) * self.quantity
        else:  # SHORT
            return (self.avg_price - current_price) * abs(self.quantity)

    def pnl_pct(self, current_price: float) -> float:
        """P&L percentage"""
        if self.avg_price == 0:
            return 0.0
        base = self.avg_price * abs(self.quantity)
        return (self.pnl(current_price) / base) * 100 if base > 0 else 0.0


@dataclass
class PaperOrder:
    """Paper trading order record"""
    order_id:      str
    symbol:        str
    exchange:      str
    transaction:   str  # BUY / SELL
    order_type:    str  # MARKET / LIMIT / SL / SL-M
    product:       str
    quantity:      int
    price:         float
    trigger_price: float
    stop_loss:     float
    target:        float
    tag:           str
    timestamp:     datetime
    status:        str = "COMPLETE"  # Paper orders turant complete ho jaate hain


class PaperPortfolio:
    """
    Paper trading ka complete portfolio tracker.
    Orders aur positions ko JSON file mein save karta hai.
    Live P&L calculate karta hai current market price se.
    """

    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            self.storage_path = str(Path(__file__).resolve().parent / "data" / "paper_portfolio.json")
        else:
            self.storage_path = storage_path
        self.positions:    dict[str, PaperPosition] = {}  # symbol -> position
        self.orders:       list[PaperOrder]         = []
        self.closed_pnl:   float                    = 0.0  # Total realized P&L
        self.load()

    def load(self):
        """JSON file se portfolio load karo"""
        try:
            if not os.path.exists(self.storage_path) or os.path.getsize(self.storage_path) == 0:
                # Create empty portfolio
                self.save()
                logger.info(f"📄 Paper portfolio initialized: {self.storage_path}")
                return

            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)


            # Load positions
            self.positions = {}
            for sym, pos_data in data.get("positions", {}).items():
                self.positions[sym] = PaperPosition(
                    symbol=pos_data["symbol"],
                    exchange=pos_data["exchange"],
                    quantity=pos_data["quantity"],
                    avg_price=pos_data["avg_price"],
                    product=pos_data["product"],
                    entry_time=datetime.fromisoformat(pos_data["entry_time"]),
                    stop_loss=pos_data.get("stop_loss", 0),
                    target=pos_data.get("target", 0),
                    tag=pos_data.get("tag", ""),
                )

            # Load orders
            self.orders = []
            for ord_data in data.get("orders", []):
                self.orders.append(PaperOrder(
                    order_id=ord_data["order_id"],
                    symbol=ord_data["symbol"],
                    exchange=ord_data["exchange"],
                    transaction=ord_data["transaction"],
                    order_type=ord_data["order_type"],
                    product=ord_data["product"],
                    quantity=ord_data["quantity"],
                    price=ord_data["price"],
                    trigger_price=ord_data.get("trigger_price", 0),
                    stop_loss=ord_data.get("stop_loss", 0),
                    target=ord_data.get("target", 0),
                    tag=ord_data.get("tag", ""),
                    timestamp=datetime.fromisoformat(ord_data["timestamp"]),
                    status=ord_data.get("status", "COMPLETE"),
                ))

            self.closed_pnl = data.get("closed_pnl", 0.0)

            logger.info(f"📄 Paper portfolio loaded: {len(self.positions)} positions, {len(self.orders)} orders")

        except Exception as e:
            logger.error(f"Paper portfolio load error: {e}")
            self.positions = {}
            self.orders    = []
            self.closed_pnl = 0.0

    def save(self):
        """Portfolio ko JSON mein save karo"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                "positions": {
                    sym: {
                        "symbol":      pos.symbol,
                        "exchange":    pos.exchange,
                        "quantity":    pos.quantity,
                        "avg_price":   pos.avg_price,
                        "product":     pos.product,
                        "entry_time":  pos.entry_time.isoformat(),
                        "stop_loss":   pos.stop_loss,
                        "target":      pos.target,
                        "tag":         pos.tag,
                    }
                    for sym, pos in self.positions.items()
                },
                "orders": [
                    {
                        "order_id":      ord.order_id,
                        "symbol":        ord.symbol,
                        "exchange":      ord.exchange,
                        "transaction":   ord.transaction,
                        "order_type":    ord.order_type,
                        "product":       ord.product,
                        "quantity":      ord.quantity,
                        "price":         ord.price,
                        "trigger_price": ord.trigger_price,
                        "stop_loss":     ord.stop_loss,
                        "target":        ord.target,
                        "tag":           ord.tag,
                        "timestamp":     ord.timestamp.isoformat(),
                        "status":        ord.status,
                    }
                    for ord in self.orders
                ],
                "closed_pnl": self.closed_pnl,
                "last_updated": datetime.now(IST_tz).isoformat(),
            }

            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Paper portfolio save error: {e}")

    def place_order(
        self,
        symbol: str,
        exchange: str,
        transaction: str,
        quantity: int,
        order_type: str,
        product: str,
        price: float = 0,
        trigger_price: float = 0,
        stop_loss: float = 0,
        target: float = 0,
        tag: str = "",
    ) -> str:
        """
        Paper order place karo aur position update karo.
        Returns: order_id
        """
        order_id = f"PAPER_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"

        # Create order record
        order = PaperOrder(
            order_id=order_id,
            symbol=symbol,
            exchange=exchange,
            transaction=transaction,
            order_type=order_type,
            product=product,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            stop_loss=stop_loss,
            target=target,
            tag=tag,
            timestamp=datetime.now(IST_tz),
            status="COMPLETE",
        )
        self.orders.append(order)

        # Update position
        self._update_position(
            symbol=symbol,
            exchange=exchange,
            transaction=transaction,
            quantity=quantity,
            price=price if price > 0 else 0,  # Price 0 matlab current market price se fill hua
            product=product,
            stop_loss=stop_loss,
            target=target,
            tag=tag,
        )

        self.save()
        logger.info(f"📄 Paper order placed: {transaction} {quantity} {symbol} @ ₹{price:.2f}")
        return order_id

    def _update_position(
        self,
        symbol: str,
        exchange: str,
        transaction: str,
        quantity: int,
        price: float,
        product: str,
        stop_loss: float = 0,
        target: float = 0,
        tag: str = "",
    ):
        """Position ko update karo (add / reduce / reverse)"""
        key = symbol

        if key not in self.positions:
            # New position
            qty = quantity if transaction == "BUY" else -quantity
            self.positions[key] = PaperPosition(
                symbol=symbol,
                exchange=exchange,
                quantity=qty,
                avg_price=price,
                product=product,
                entry_time=datetime.now(IST_tz),
                stop_loss=stop_loss,
                target=target,
                tag=tag,
            )
        else:
            # Existing position - update karo
            pos = self.positions[key]
            new_qty = quantity if transaction == "BUY" else -quantity
            total_qty = pos.quantity + new_qty

            if total_qty == 0:
                # Position completely closed
                realized_pnl = pos.pnl(price)
                self.closed_pnl += realized_pnl
                del self.positions[key]
                logger.info(f"📄 Position closed: {symbol} | P&L: ₹{realized_pnl:.2f}")

            elif (pos.quantity > 0 and total_qty > 0) or (pos.quantity < 0 and total_qty < 0):
                # Same direction - average karo
                total_value = (pos.avg_price * abs(pos.quantity)) + (price * quantity)
                pos.quantity = total_qty
                pos.avg_price = total_value / abs(total_qty)
                if stop_loss > 0:
                    pos.stop_loss = stop_loss
                if target > 0:
                    pos.target = target

            elif abs(total_qty) < abs(pos.quantity):
                # Partial exit
                exit_qty = abs(new_qty)
                realized_pnl = (price - pos.avg_price) * exit_qty if pos.quantity > 0 else (pos.avg_price - price) * exit_qty
                self.closed_pnl += realized_pnl
                pos.quantity = total_qty
                logger.info(f"📄 Partial exit: {symbol} | P&L: ₹{realized_pnl:.2f}")

            else:
                # Position reversed
                realized_pnl = pos.pnl(price)
                self.closed_pnl += realized_pnl
                remaining_qty = total_qty
                pos.quantity = remaining_qty
                pos.avg_price = price
                pos.entry_time = datetime.now(IST_tz)
                if stop_loss > 0:
                    pos.stop_loss = stop_loss
                if target > 0:
                    pos.target = target
                logger.info(f"📄 Position reversed: {symbol} | Realized P&L: ₹{realized_pnl:.2f}")

    def get_positions(self, kite=None) -> list[dict]:
        """
        Saare open positions with live P&L.
        Agar kite object hai toh live LTP fetch karke P&L calculate karo.
        """
        result = []

        if not self.positions:
            return result

        # Try to fetch live prices
        live_prices = {}
        if kite:
            try:
                instruments = [f"{pos.exchange}:{pos.symbol}" for pos in self.positions.values()]
                ohlc_data = kite.ohlc(instruments)
                for key, data in ohlc_data.items():
                    sym = key.split(":")[1]
                    live_prices[sym] = data.get("last_price", 0)
            except Exception as e:
                logger.warning(f"Live price fetch error: {e}")

        for sym, pos in self.positions.items():
            ltp = live_prices.get(sym, pos.avg_price)  # Fallback to avg_price

            pnl     = pos.pnl(ltp)
            pnl_pct = pos.pnl_pct(ltp)

            result.append({
                "symbol":     sym,
                "exchange":   pos.exchange,
                "quantity":   pos.quantity,
                "avg_price":  round(pos.avg_price, 2),
                "ltp":        round(ltp, 2),
                "pnl":        round(pnl, 2),
                "pnl_pct":    round(pnl_pct, 2),
                "product":    pos.product,
                "entry_time": pos.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "stop_loss":  pos.stop_loss,
                "target":     pos.target,
                "tag":        pos.tag,
            })

        return result

    def get_orders(self, limit: int = 50) -> list[dict]:
        """Recent orders history"""
        recent = self.orders[-limit:] if len(self.orders) > limit else self.orders
        recent.reverse()  # Latest first

        return [
            {
                "order_id":      ord.order_id,
                "symbol":        ord.symbol,
                "exchange":      ord.exchange,
                "transaction":   ord.transaction,
                "order_type":    ord.order_type,
                "product":       ord.product,
                "quantity":      ord.quantity,
                "price":         round(ord.price, 2),
                "trigger_price": round(ord.trigger_price, 2),
                "stop_loss":     round(ord.stop_loss, 2),
                "target":        round(ord.target, 2),
                "tag":           ord.tag,
                "timestamp":     ord.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "status":        ord.status,
            }
            for ord in recent
        ]

    def exit_position(self, symbol: str, price: float = 0, kite=None) -> bool:
        """Position ko close karo"""
        if symbol not in self.positions:
            return False

        pos = self.positions[symbol]

        # Agar price nahi di toh live LTP fetch karo
        if price == 0 and kite:
            try:
                ohlc = kite.ohlc([f"{pos.exchange}:{symbol}"])
                key = f"{pos.exchange}:{symbol}"
                price = ohlc.get(key, {}).get("last_price", pos.avg_price)
            except:
                price = pos.avg_price

        # Opposite transaction se exit karo
        exit_txn = "SELL" if pos.quantity > 0 else "BUY"
        exit_qty = abs(pos.quantity)

        self.place_order(
            symbol=symbol,
            exchange=pos.exchange,
            transaction=exit_txn,
            quantity=exit_qty,
            order_type="MARKET",
            product=pos.product,
            price=price,
            tag="EXIT",
        )

        return True

    def get_margin_summary(self, kite=None, total_capital: float = None) -> dict:
        """
        Paper trading margin tracker with 5X Intraday (MIS) leverage.
        - MIS (Intraday): 20% margin requirement (5X Leverage) -> (pos_val / 5.0)
        - CNC (Delivery): 100% margin requirement (1X Leverage) -> pos_val
        """
        if total_capital is None:
            from config import TOTAL_CAPITAL
            total_capital = float(TOTAL_CAPITAL)

        used_margin = 0.0
        open_pnl = 0.0

        live_prices = {}
        if kite and self.positions:
            try:
                instruments = [f"{pos.exchange}:{pos.symbol}" for pos in self.positions.values()]
                ohlc_data = kite.ohlc(instruments)
                for key, data in ohlc_data.items():
                    sym = key.split(":")[1] if ":" in key else key
                    live_prices[sym] = data.get("last_price", 0)
            except Exception:
                pass

        for sym, pos in self.positions.items():
            ltp = live_prices.get(sym, pos.avg_price)
            if ltp == 0:
                ltp = pos.avg_price
            open_pnl += pos.pnl(ltp)
            pos_val = abs(pos.quantity) * pos.avg_price
            if str(pos.product).upper() == "MIS":
                used_margin += (pos_val / 5.0)  # 5X leverage for intraday
            else:
                used_margin += pos_val          # 1X for delivery/CNC

        net_capital = total_capital + self.closed_pnl + open_pnl
        available_margin = max(0.0, net_capital - used_margin)

        return {
            "total_capital": round(total_capital, 2),
            "net_capital": round(net_capital, 2),
            "used_margin": round(used_margin, 2),
            "available_margin": round(available_margin, 2),
            "closed_pnl": round(self.closed_pnl, 2),
            "open_pnl": round(open_pnl, 2),
            "leverage_multiplier": 5,
        }

    def reset(self):
        """Portfolio ko reset karo - saare positions aur orders clear"""
        self.positions = {}
        self.orders = []
        self.closed_pnl = 0.0
        self.save()
        logger.info("📄 Paper portfolio reset")
