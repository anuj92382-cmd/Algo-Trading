# 🤖 Zerodha Kite Algo Trading Bot

Python mein bana hua **Intraday + Swing Trading** bot jo **Zerodha Kite Connect API** use karta hai.

---

## 📁 Project Structure

```
algo_trading/
├── main.py              ← Main bot (yahi chalao)
├── dashboard.py         ← Live terminal dashboard
├── config.py            ← Saari settings
├── auth.py              ← Zerodha login & token management
├── data.py              ← Market data + technical indicators
├── order_manager.py     ← Orders place/modify/cancel
├── risk_manager.py      ← Capital & risk protection
├── ticker.py            ← Real-time WebSocket feed
├── .env                 ← API keys (PRIVATE - git mein mat daalna!)
├── requirements.txt     ← Python dependencies
├── strategies/
│   ├── intraday.py      ← EMA + RSI + VWAP intraday strategy
│   └── swing.py         ← EMA + MACD + ADX swing strategy
├── utils/
│   ├── logger.py        ← Colorful logging setup
│   └── notifier.py      ← Telegram alerts
├── logs/                ← Trading logs
├── data/                ← Access token, SQLite DB
└── reports/             ← Daily trade reports (CSV)
```

---

## ⚡ Setup - Step by Step

### Step 1: Zerodha Kite Connect App banana

1. [kite.trade](https://kite.trade) pe jaao
2. Account banao → New App create karo
3. **API Key** aur **API Secret** note karo
4. Redirect URL: `https://127.0.0.1/`

### Step 2: Python Environment

```bash
# Python 3.10+ required
python --version

# Virtual environment banao
python -m venv venv

# Activate karo
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Dependencies install karo
pip install -r requirements.txt
```

### Step 3: .env File Configure Karo

`.env` file kholo aur apni details bharo:

```env
KITE_API_KEY=abcdefgh12345678       ← Kite app se copy karo
KITE_API_SECRET=xxxxxxxxxxxxxxxx    ← Kite app se copy karo
KITE_USER_ID=AB1234                 ← Zerodha User ID

TRADING_MODE=PAPER                  ← Pehle PAPER rakhna! Baad mein LIVE karna
TOTAL_CAPITAL=100000                ← Kitna capital use karna hai
MAX_RISK_PER_TRADE=1.0              ← 1% per trade risk
MAX_DAILY_LOSS=3.0                  ← 3% daily loss limit
```

> ⚠️ **IMPORTANT**: Pehle hamesha `TRADING_MODE=PAPER` rakhna! Real trading se pehle paper trading mein test karo.

### Step 4: Config Check Karo

```bash
python config.py
```

Output aana chahiye:
```
✅ Config sahi hai!
⚠️  WARNING: PAPER TRADING mode ON hai.
```

---

## 🚀 Bot Chalane Ka Tarika

### Main Bot Start Karo

```bash
cd d:\algotrading\algo_trading
python main.py
```

**Pehli baar chalane pe:**
1. Browser mein Zerodha login page khulega
2. Login karo
3. Redirect URL se `request_token` copy karo
   - URL kuch aisa dikhega: `https://127.0.0.1/?request_token=xxxxxxxx&action=login&status=success`
4. `request_token=` ke baad wala value terminal mein paste karo
5. Bot start ho jayega!

**Doosri baar se:** Token auto-save hota hai, browser nahi khulaega (same day).

### Dashboard Start Karo (alag terminal mein)

```bash
python dashboard.py
```

Dashboard dikhata hai:
- Live P&L
- Active positions
- Today's trades
- Watchlist prices
- Risk meter

---

## 📈 Strategies

### Intraday Strategy (EMA + RSI + VWAP)

| Setting | Value |
|---------|-------|
| Timeframe | 5-minute candles |
| Entry | EMA 9/21 crossover + RSI 40-65 + Price > VWAP + Volume spike |
| Stop Loss | 1.5x ATR |
| Target | 2:1 Risk:Reward |
| Trailing SL | 1x ATR |
| Entry Cutoff | 2:30 PM ke baad koi entry nahi |
| Force Exit | 3:15 PM |
| Product | MIS (Intraday) |

**Buy Signal:** Fast EMA (9) Slow EMA (21) ke upar cross kare + RSI 40-65 + Price VWAP se upar + Volume average se 1.5x zyada

**Short Signal:** Fast EMA (9) Slow EMA (21) ke niche cross kare + RSI 35-60 + Price VWAP se niche + Volume spike

### Swing Strategy (EMA + MACD + ADX)

| Setting | Value |
|---------|-------|
| Timeframe | Daily candles |
| Entry | EMA 20/50 crossover + MACD bullish + RSI 40-65 + ADX > 25 |
| Stop Loss | 5% ya 2x ATR (jo bhi closer) |
| Target | 10% |
| Trailing SL | 3% |
| Holding Period | 3-15 days |
| Product | CNC (Delivery) |

**Conviction Score:** 5 mein se kitni conditions meet hui (3+ = trade lo)

---

## ⚙️ Settings Customize Karna

`config.py` mein jaao aur apne hisaab se change karo:

### Watchlist Change Karna

```python
# Intraday watchlist
INTRADAY_CONFIG = {
    "watchlist": [
        "RELIANCE", "TCS", "INFY",   # Apne stocks add/remove karo
        ...
    ],
}

# Swing watchlist
SWING_CONFIG = {
    "watchlist": [
        "RELIANCE", "TCS", ...
    ],
}
```

### Capital aur Risk Change Karna

`.env` mein:
```env
TOTAL_CAPITAL=200000       ← 2 lakh capital
MAX_RISK_PER_TRADE=0.5     ← 0.5% per trade (conservative)
MAX_DAILY_LOSS=2.0         ← 2% daily loss limit
```

### Indicators Adjust Karna

```python
# Intraday
INTRADAY_CONFIG["indicators"]["ema_fast"] = 9   # Fast EMA
INTRADAY_CONFIG["indicators"]["ema_slow"] = 21  # Slow EMA
INTRADAY_CONFIG["indicators"]["rsi_period"] = 14

# Swing
SWING_CONFIG["indicators"]["ema_fast"] = 20
SWING_CONFIG["indicators"]["ema_slow"] = 50
```

---

## 🔔 Telegram Alerts Setup (Optional)

1. Telegram mein [@BotFather](https://t.me/BotFather) se bot banao
2. **Bot Token** milega
3. Apna **Chat ID** pata karo: [@userinfobot](https://t.me/userinfobot)
4. `.env` mein add karo:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...
TELEGRAM_CHAT_ID=987654321
```

Ab ye alerts milenge:
- ✅ Trade entry
- ❌ Stop loss hit
- 🎯 Target achieved
- 📊 Daily summary

---

## 🛡️ Risk Management

Bot automatically protect karta hai:

| Rule | Default |
|------|---------|
| Max risk per trade | 1% of capital |
| Max daily loss | 3% of capital |
| Max open positions | 5 |
| Max position size | 20% of capital |
| Min Risk:Reward | 1:1.5 |
| Intraday force exit | 3:15 PM |
| Daily loss halt | Auto-stop trading |

---

## 📊 Daily Reports

Reports `reports/` folder mein CSV format mein save hote hain:

```
reports/
├── report_2024-01-15.csv
├── report_2024-01-16.csv
└── ...
```

Excel mein open karo detailed analysis ke liye.

---

## ❓ Common Issues

**Login loop mein phans gaya?**
```bash
# Token file delete karo
del data\access_token.json
# Phir se chalao
python main.py
```

**"No data returned" error?**
- Market hours check karo (9:15 AM - 3:30 PM)
- Internet connection check karo
- API key valid hai check karo

**Orders nahi ja rahe?**
- `.env` mein `TRADING_MODE=PAPER` hai?
- Paper mode mein real orders nahi jaate (intentional!)
- Live trading ke liye: `TRADING_MODE=LIVE`

**Bahut zyada trades ho rahe hain?**
- `MAX_OPEN_POSITIONS` kam karo (config.py mein)
- `volume_multiplier` badhao (strict volume filter)
- Watchlist chhota karo

---

## ⚠️ Important Disclaimer

> **Yeh software sirf educational purpose ke liye hai.**
>
> - Stock market mein trading mein **capital loss ka risk** hota hai
> - Pehle **PAPER TRADING** mein thoroughly test karo
> - Real money se pehle kisi **SEBI-registered advisor** se consult karo
> - Past performance future returns guarantee nahi karta
> - Apni **khud ki research** karo before live trading

---

## 📞 Quick Reference

```bash
# Bot start karo
python main.py

# Dashboard dekho
python dashboard.py

# Config check karo
python config.py

# Dependencies install karo
pip install -r requirements.txt
```

---

*Built with ❤️ using Python + Zerodha Kite Connect API*
