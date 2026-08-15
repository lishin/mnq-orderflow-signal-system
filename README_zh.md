# ⚡ MNQ 隔夜盤 Volume Profile 與訂單流訊號系統

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/package%20manager-uv-green.svg)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

專為 **微型那斯達克 100 期貨 (MNQ)** 設計之高性能、純非同步量化訊號與自動交易引擎。完全基於 **Interactive Brokers (IBKR)** 免費數據接口（`ib_async`）、純 `numpy` 向量化運算與 Python 3.12+ `asyncio`。

---

## 🎯 核心功能特色

- 📊 **隔夜盤固定區間成交量分佈 (FRVP)**：
  - 自動抓取隔夜盤（ETH）1 分鐘 K 線（美東時間 18:00–09:30）。
  - 以 $O(N)$ 整數 Tick 空間快速運算 **POC（控制點）**、**VAH（價值區高點）** 與 **VAL（價值區低點）**（支援 CBOT 70% Steidlmayer 雙層擴展與 Greedy 單層演算法）。
- 🌊 **即時主動單（Aggressor）分類（Lee-Ready）**：
  - 訂閱 IBKR 逐筆無取樣 `AllLast` 與 `BidAsk` 數據串流。
  - 透過 Quote Matching 與 Tick Rule 補償機制，精確分類每一筆成交為 **主動買單 (+1)** 或 **主動賣單 (-1)**。
- 🧊 **Footprint 與訂單流「吸收（Absorption）」偵測**：
  - 每分鐘動態聚合成交量矩陣（各價位之 Bid/Ask 分佈）。
  - 結合滾動 95 分位數動態大單門檻與 K 線影線失衡比率，精準捕捉主力被動吸收與流動性陷阱。
- 🎯 **策略訊號引擎**：
  - **Failed Auction（假突破 / 拍賣失敗做多/做空）**：VAH/VAL 邊界出現吸收且收回價值區內時觸發均值回歸。
  - **Breakout Acceptance（真突破順勢做多/做空）**：盤整突破伴隨主動單強力推進（Follow-through）。
  - 內建 **09:30 開盤 5 分鐘冷靜期濾網** 與 **0~100 信心度動態評分**。
- 🖥️ **極簡高刷新終端儀表板 (Rich TUI)**：
  - 獨立線程 4 FPS 渲染，HUD 介面流暢無延遲，不佔用行情運算 CPU。
- 📱 **Telegram 即時警報與自動交易支援**：
  - 觸發時非同步推播 HTML 格式警報（進場點、止損點、TP1/TP2、觸發理由）。
  - 可選啟用 3 腳 Bracket Order 自動下單功能（`Entry LMT`、`TP LMT`、`SL STP`）。

---

## 🚀 快速上手教學

### 1. 環境需求
- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** 套件管理工具
- **IBKR TWS 或 IB Gateway**（建議先以模擬帳戶 Paper Trading 測試）

### 2. 下載與安裝

```bash
git clone https://github.com/YOUR_USERNAME/mnq-signal-system.git
cd mnq-signal-system
uv sync
```

### 3. TWS / Gateway API 設定
1. 開啟 TWS 或 IB Gateway。
2. 前往 **File / Edit > Global Configuration > API > Settings**：
   - 勾選 **Enable ActiveX and Socket Clients**。
   - 取消勾選 **Read-Only API**（若需使用自動下單）。
   - 確認通訊埠（TWS 模擬盤預設 `7497`，Gateway 模擬盤預設 `4002`）。
   - 在 Trusted IP Addresses 加入 `127.0.0.1`。

### 4. 設定檔配置

複製範例設定檔：
```bash
cp config.example.toml config.toml
```

編輯 `config.toml` 填入您的設定：
```toml
[connection]
host = "127.0.0.1"
port = 7497              # TWS Paper: 7497 | Gateway Paper: 4002

[contract]
symbol = "MNQ"
expiry = ""              # 留空則自動偵測最近到期之前月合約

[signal]
cooldown_after_open_secs = 300   # 09:30 開盤後冷靜期（秒）
auto_trade_enabled = false       # 設為 true 開啟自動交易 Bracket Order
auto_trade_quantity = 1

[webhook]
telegram_enabled = false
telegram_bot_token = "YOUR_TELEGRAM_BOT_TOKEN"
telegram_chat_id = "YOUR_TELEGRAM_CHAT_ID"
```

### 5. 啟動系統

```bash
# 1. 執行演算法單元驗證
uv run python test_smoke.py

# 2. 啟動主系統
uv run python main.py
```

---

## 📈 核心策略邏輯彙整

| 訊號類型 | 觸發條件 (Entry Trigger) | 停損 (SL) | 停利 (TP) |
| :--- | :--- | :--- | :--- |
| **Failed Auction (做空)** | 1. 價格曾高於 VAH。<br>2. 出現頂部主動買單被吸收（Bearish Absorption）。<br>3. 價格收回 VAH 之內（$\le \text{VAH}$）。 | 吸收區最高價上方 2~4 Ticks | **TP1:** POC (減倉/保本)<br>**TP2:** VAL |
| **Failed Auction (做多)** | 1. 價格曾低於 VAL。<br>2. 出現底部主動賣單被吸收（Bullish Absorption）。<br>3. 價格收回 VAL 之上（$\ge \text{VAL}$）。 | 吸收區最低價下方 2~4 Ticks | **TP1:** POC (減倉/保本)<br>**TP2:** VAH |
| **Breakout (順勢做空)** | 1. 價格在 VAL 之下盤整累積平衡。<br>2. 跌破盤整低點且伴隨大量主動賣單推進。 | 突破 K 線高點或盤整區上緣 | 1:2+ 風報比目標 |

---

## ⚠️ 免責聲明 (Disclaimer)

> [!CAUTION]
> 期貨及衍生性金融商品交易具有高度風險，未必適合所有投資人。本開源專案所提供之代碼、訊號與分析僅供學術研究與教育參考，不構成任何投資建議。使用者於實盤交易前，務必於模擬環境（Paper Trading）充分驗證策略表現，並自行承擔交易風險。

---

## 📄 開源授權

本專案採用 [MIT License](LICENSE) 開源授權。
