# US Stocks Trading Stack — Complete Guide 🇺🇸

This repository supports dual-market trading for **India (NSE)** and **US Equities (NYSE/NASDAQ)** using DhanHQ Global Stocks APIs.

---

## 1. Quick Start (Paper Mode — Default)

By default, US trading runs in **Paper Mode** (`US_PAPER=true`).
It fetches live market data from Dhan, calculates indicator signals, and manages a virtual USD portfolio ($10,000 starting cash) persisted in `us_paper_portfolio.json`.

### Requirements
Your `.env` file needs valid Dhan credentials:
```env
DHAN_CLIENT_ID=112996229
DHAN_ACCESS_TOKEN=your_token_here
DHAN_PIN=1234
DHAN_TOTP_SECRET=your_totp_secret

# US Paper mode settings
US_PAPER=true
US_PAPER_STARTING_CASH=10000
US_STOCK_UNIVERSE=AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,V,UNH
```

---

## 2. Live Money Arming Safety Gate 🛡️

To place real US stock orders through Dhan Global Stocks:

1. **Activate Global Stocks** on your Dhan account (visit [dhan.co](https://dhan.co) -> Settings -> Global Stocks).
2. Set the following **two environment variables** in `.env`:

```env
US_LIVE_TRADING=true
US_LIVE_CONFIRM=YES_REAL_MONEY
```

> [!WARNING]
> Real orders will only execute if **BOTH** variables are set exactly as shown. If either is missing or incorrect, the bot stays in Paper mode or blocks live orders.

---

## 3. Market Hours & Timezones ⏰

US stock markets operate on **Eastern Time (ET)**:
- **Regular Hours**: 9:30 AM – 4:00 PM ET (Monday – Friday)
- **IST Equivalents**:
  - **Standard Time (EST)**: 8:00 PM – 2:30 AM IST
  - **Daylight Saving Time (EDT)**: 7:00 PM – 1:30 AM IST

The US market loop automatically detects trading hours based on the `America/New_York` timezone and idles outside session hours.

---

## 4. Dhan Global Stocks Architecture & Nuances

- **Shared Session**: The US broker uses the same `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` as the India broker.
- **Security IDs**: US stocks use numeric security IDs from the Dhan Global instrument master (`us_instruments.py`).
- **Global Methods**: Order execution calls `place_global_order()`, portfolio calls `get_global_holdings()`, and funds call `get_global_fund_limit()`.
- **Graceful Fallback**: If Global Stocks is not activated on your Dhan account, the bot logs a warning and keeps India trading active without crashing.

---

## 5. Regulatory Notes (India → US Investing)

- **LRS (Liberalised Remittance Scheme)**: RBI permits resident Indians to remit up to **$250,000 USD** per financial year for overseas investments.
- **TCS (Tax Collected at Source)**: Remittances above ₹7 Lakhs in a financial year attract TCS under Section 207C of the IT Act.
- **GIFT City / INX**: Dhan Global Stocks operates via India INX in GIFT City, providing streamlined clearing and settlement for Indian investors.

---

## 6. Dashboard Interface

The web admin dashboard includes a tab switcher:
- 🇮🇳 **India (NSE)**: INR portfolio, Nifty Large-Caps, NSE market status, India kill switch.
- 🇺🇸 **US (Dhan Global)**: USD portfolio, US Tech & Blue-Chip universe, NYSE market status, US kill switch, manual Buy action.

Access the dashboard at `http://localhost:5000` (or `PORT` on Render/cloud).
