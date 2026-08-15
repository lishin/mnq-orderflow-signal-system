# ⚡ MNQ Overnight Volume Profile & Order Flow Signal System

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/package%20manager-uv-green.svg)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[繁體中文說明文件 (Traditional Chinese README)](README_zh.md)

A high-performance, asynchronous algorithmic trading & signal engine for **Micro E-mini Nasdaq-100 Futures (MNQ)**. Built entirely on free data feeds via **Interactive Brokers (IBKR)** using `ib_async`, pure `numpy` vectorization, and modern Python 3.12+ `asyncio`.

---

## 🎯 Key Capabilities

- 📊 **Overnight Session Fixed Range Volume Profile (FRVP)**:
  - Automatically fetches overnight (ETH) 1-minute historical bars (18:00–09:30 ET).
  - Fast $O(N)$ integer-tick binning to compute **Point of Control (POC)**, **Value Area High (VAH)**, and **Value Area Low (VAL)** using the classic CBOT 70% Steidlmayer / Greedy Value Area algorithms.
- 🌊 **Real-Time Aggressor Classification (Lee-Ready)**:
  - Subscribes to un-sampled `AllLast` + `BidAsk` tick streams.
  - Classifies every execution into **Aggressive Buy (+1)** or **Aggressive Sell (-1)** using Quote Matching with Tick Rule fallback.
- 🧊 **Footprint & Order Flow Absorption Detection**:
  - Aggregates trades into dynamic 1-minute Footprint matrices (`Bid × Ask` per tick).
  - Traps institutional liquidity via rolling 95th percentile dynamic big-trade filters and wick imbalance ratios.
- 🎯 **Algorithmic Signal Engine**:
  - **Failed Auction (Short/Long)**: Detects false breakouts at VAH/VAL with order absorption and mean reversion back into Value.
  - **Breakout Acceptance (Short/Long)**: Detects acceptance outside Value with aggressive momentum follow-through.
  - Built-in **09:30 ET cash open cool-down filter** and confidence scoring (0–100).
- 🖥️ **Ultra-Fast Terminal Dashboard (Rich TUI)**:
  - Real-time Head-Up Display (HUD) updating at 4 FPS decoupled from the high-throughput tick stream.
- 📱 **Telegram Alerts & Optional Automated Execution**:
  - Instant HTML webhook pushes with Entry, SL, TP1 (POC), TP2, and rationale.
  - Optional 3-legged Bracket Order automated execution (`Entry LMT`, `TP LMT`, `SL STP`).

---

## 🏗️ System Architecture

```
[ IBKR TWS / IB Gateway ]
         │ (ib_async via asyncio)
         ├── 1. Historical Bars (18:00 - 09:30 ET) ──> [ FRVP Engine: POC / VAH / VAL ]
         └── 2. Tick Streams (AllLast + BidAsk)     ──> [ Orderflow Engine: Lee-Ready + Footprint ]
                                                                     │
                                                                     ▼
                                                          [ Signal Evaluation Engine ]
                                                          - Failed Auction
                                                          - Breakout Acceptance
                                                                     │
                                       ┌─────────────────────────────┼─────────────────────────────┐
                                       ▼                             ▼                             ▼
                            [ Rich Terminal TUI ]       [ Telegram Webhook ]          [ Bracket Order Trader ]
```

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** (recommended for lightning-fast package management)
- **Interactive Brokers TWS or IB Gateway** (Paper or Live account)

### 2. Installation

Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/mnq-signal-system.git
cd mnq-signal-system
```

Install dependencies using `uv`:
```bash
uv sync
```

### 3. TWS / Gateway Configuration
1. Open TWS or IB Gateway.
2. Go to **File / Edit > Global Configuration > API > Settings**:
   - Check **Enable ActiveX and Socket Clients**.
   - Uncheck **Read-Only API** (if using auto-trading).
   - Ensure the Socket Port matches your configuration (TWS Paper: `7497`, Gateway Paper: `4002`).
   - Add `127.0.0.1` to **Trusted IP Addresses**.

### 4. Configuration

Copy the example configuration file:
```bash
cp config.example.toml config.toml
```

Edit `config.toml`:
```toml
[connection]
host = "127.0.0.1"
port = 7497              # TWS Paper: 7497 | Gateway Paper: 4002

[contract]
symbol = "MNQ"
expiry = ""              # Leave empty to automatically select front-month

[signal]
cooldown_after_open_secs = 300   # 5-minute cool-down after 09:30 ET open
auto_trade_enabled = false       # Set true to enable bracket order execution
auto_trade_quantity = 1

[webhook]
telegram_enabled = false
telegram_bot_token = "YOUR_TELEGRAM_BOT_TOKEN"
telegram_chat_id = "YOUR_TELEGRAM_CHAT_ID"
```

### 5. Run

```bash
# Run unit & smoke tests
uv run python test_smoke.py

# Launch the live signal system
uv run python main.py
```

---

## 📊 Terminal Dashboard Preview

```
┌──────────────────────────────────────────────────────────────────┐
│  MNQ Signal System  |  2024-09-20 09:38:15 ET  | Status: ● Running│
├────────────────────────────────┬─────────────────────────────────┤
│ Fixed Range Volume Profile     │ Orderflow Stats                 │
│ VAH:        19,312.25          │ Last Price: 19,310.50           │
│ POC:        19,250.50          │ Bid / Ask:  19,310.25 / 19,310.50│
│ VAL:        19,188.00          │ Cum. Delta: +420                │
│ VA%:        70.8%              │ Buy Vol:    2,340               │
│ Last Price: 19,310.50 (in VA)  │ Sell Vol:   1,920               │
│                                │ Big Trades: 6                   │
├────────────────────────────────┴─────────────────────────────────┤
│ Recent Signals                                                   │
│ Time     Direction  Type                 Entry     SL        TP1  Score│
│ 09:37:00 ▼ SHORT   FAILED_AUCTION_SHORT 19315.50  19319.50  19250.50 85 │
├──────────────────────────────────────────────────────────────────┤
│           [Ctrl+C] Exit | Auto-Trade: OFF | Webhook: ON          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📈 Strategy Logic

| Signal | Trigger Condition | Stop Loss | Take Profit |
| :--- | :--- | :--- | :--- |
| **Failed Auction (Short)** | 1. Price trades above VAH.<br>2. Bearish absorption detected at upper wick.<br>3. Price closes back inside Value Area ($\le \text{VAH}$). | High of absorption zone $+ 3\text{ ticks}$ | **TP1:** POC<br>**TP2:** VAL |
| **Failed Auction (Long)** | 1. Price trades below VAL.<br>2. Bullish absorption detected at lower wick.<br>3. Price closes back inside Value Area ($\ge \text{VAL}$). | Low of absorption zone $- 3\text{ ticks}$ | **TP1:** POC<br>**TP2:** VAH |
| **Breakout (Short)** | 1. Price consolidates below VAL.<br>2. Breaks consolidation low with heavy sell delta & big trade follow-through. | High of breakout candle / range | $1:2+$ Risk/Reward |

---

## ⚠️ Disclaimer

> [!CAUTION]
> Futures and derivatives trading involves substantial risk of loss and is not suitable for every investor. The signals, analytics, and code provided in this repository are for educational, research, and informational purposes only and do not constitute financial or investment advice. Always test thoroughly in a Paper Trading simulation environment before deploying live capital.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
