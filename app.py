"""
India Markets Dashboard
Tabs: Macro/Market Indicators | Nifty 50 Tracker | Upcoming
Auto-refreshes: data is cached with a TTL, so every reload after the TTL pulls fresh data.
Run:  streamlit run app.py
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="India Markets Dashboard", layout="wide")
st_autorefresh(interval=15 * 60 * 1000, key="refresh")  # page re-runs every 15 min

# Nifty 50 constituents change at index rebalancing: verify against niftyindices.com
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TCS",
    "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
    "WIPRO",
]
TICKERS = [f"{s}.NS" for s in NIFTY50]

MARKET_INDICATORS = {
    "Nifty 50": "^NSEI",
    "Sensex": "^BSESN",
    "Bank Nifty": "^NSEBANK",
    "India VIX": "^INDIAVIX",
    "USD/INR": "INR=X",
    "Brent Crude": "BZ=F",
    "Gold": "GC=F",
    "US 10Y Yield": "^TNX",
    "Dollar Index": "DX-Y.NYB",
    "S&P 500": "^GSPC",
}

FRED_SERIES = {  # needs free FRED_API_KEY (fred.stlouisfed.org). Verify IDs if one returns empty.
    "India CPI (index)": "INDCPIALLMINMEI",
    "India Industrial Production": "INDPROINDMISMEI",
    "India 10Y Govt Bond Yield %": "INDIRLTLT01STM",
    "India Short-term Rate %": "INDIRSTCI01STM",
}

WORLD_BANK = {  # no key needed, annual data
    "GDP growth %": "NY.GDP.MKTP.KD.ZG",
    "Inflation (CPI) %": "FP.CPI.TOTL.ZG",
    "Unemployment %": "SL.UEM.TOTL.ZS",
    "Current account % GDP": "BN.CAB.XOKA.GD.ZS",
    "Fiscal: Govt debt % GDP": "GC.DOD.TOTL.GD.ZS",
}


# ---------- data loaders (cached = auto-update) ----------
@st.cache_data(ttl=900)
def load_market_series(ticker: str, period="5y"):
    return yf.download(ticker, period=period, auto_adjust=True, progress=False)["Close"].squeeze().dropna()


@st.cache_data(ttl=3600)
def load_nifty_prices():
    df = yf.download(TICKERS, period="5y", auto_adjust=True, progress=False)["Close"]
    return df.dropna(how="all")


def _info(t):
    try:
        i = yf.Ticker(t).info
        return t, {
            "Sector": i.get("sector"),
            "Market Cap (Cr)": (i.get("marketCap") or 0) / 1e7,
            "P/E": i.get("trailingPE"),
            "P/B": i.get("priceToBook"),
            "ROE %": (i.get("returnOnEquity") or 0) * 100,
            "Div Yield %": (i.get("dividendYield") or 0) * (1 if (i.get("dividendYield") or 0) > 1 else 100),
            "Debt/Equity": i.get("debtToEquity"),
        }
    except Exception:
        return t, {}


@st.cache_data(ttl=6 * 3600)
def load_fundamentals():
    with ThreadPoolExecutor(8) as ex:
        res = dict(ex.map(_info, TICKERS))
    return pd.DataFrame(res).T


def _calendar(t):
    try:
        cal = yf.Ticker(t).calendar
        d = cal.get("Earnings Date")
        return t, (d[0] if isinstance(d, list) and d else d)
    except Exception:
        return t, None


@st.cache_data(ttl=6 * 3600)
def load_earnings_dates():
    with ThreadPoolExecutor(8) as ex:
        res = dict(ex.map(_calendar, TICKERS))
    s = pd.Series(res, name="Next Earnings").dropna()
    s.index = [i.replace(".NS", "") for i in s.index]
    return s.sort_values()


@st.cache_data(ttl=6 * 3600)
def load_fred(series_id: str, key: str):
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": key, "file_type": "json"},
        timeout=20,
    ).json()
    df = pd.DataFrame(r.get("observations", []))
    if df.empty:
        return pd.Series(dtype=float)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index(pd.to_datetime(df["date"]))["value"].dropna()


@st.cache_data(ttl=24 * 3600)
def load_worldbank(code: str):
    url = f"https://api.worldbank.org/v2/country/IND/indicator/{code}?format=json&per_page=30"
    data = requests.get(url, timeout=20).json()[1]
    s = pd.Series({int(d["date"]): d["value"] for d in data if d["value"] is not None}).sort_index()
    return s.tail(10)


# ---------- UI ----------
st.title("📈 India Markets Dashboard")
tab1, tab2, tab3 = st.tabs(["🌐 Macro & Market Indicators", "🏢 Nifty 50 Tracker", "🗓️ Upcoming"])

# ===== TAB 1 =====
with tab1:
    st.subheader("Market indicators (live, 15-min refresh)")
    cols = st.columns(5)
    for i, (name, tk) in enumerate(MARKET_INDICATORS.items()):
        try:
            s = load_market_series(tk, "1y")
            chg = (s.iloc[-1] / s.iloc[-2] - 1) * 100
            cols[i % 5].metric(name, f"{s.iloc[-1]:,.2f}", f"{chg:+.2f}%")
        except Exception:
            cols[i % 5].metric(name, "n/a")

    pick = st.selectbox("5-year chart", list(MARKET_INDICATORS))
    st.plotly_chart(px.line(load_market_series(MARKET_INDICATORS[pick]), title=pick), use_container_width=True)

    st.subheader("Macro (India)")
    st.caption("Annual data: World Bank (no key)")
    wb_cols = st.columns(len(WORLD_BANK))
    for c, (name, code) in zip(wb_cols, WORLD_BANK.items()):
        try:
            s = load_worldbank(code)
            c.metric(f"{name} ({s.index[-1]})", f"{s.iloc[-1]:.2f}")
        except Exception:
            c.metric(name, "n/a")
    wb_pick = st.selectbox("Macro trend", list(WORLD_BANK))
    try:
        st.plotly_chart(px.bar(load_worldbank(WORLD_BANK[wb_pick]), title=wb_pick), use_container_width=True)
    except Exception:
        st.warning("World Bank data unavailable right now.")

    key = os.getenv("FRED_API_KEY") or st.secrets.get("FRED_API_KEY", "") if hasattr(st, "secrets") else ""
    if key:
        st.caption("Monthly data: FRED")
        f_pick = st.selectbox("Monthly indicator", list(FRED_SERIES))
        s = load_fred(FRED_SERIES[f_pick], key)
        if len(s):
            st.plotly_chart(px.line(s.tail(120), title=f_pick), use_container_width=True)
        else:
            st.warning("No data returned. Check the series ID.")
    else:
        st.info("Monthly macro (CPI, IIP, bond yields) ke liye free FRED API key set karein: env var FRED_API_KEY.")

# ===== TAB 2 =====
with tab2:
    prices = load_nifty_prices()
    fund = load_fundamentals()
    last = prices.ffill().iloc[-1]

    def ret(days):
        return (last / prices.ffill().iloc[-min(days, len(prices))] - 1) * 100

    yrs = (prices.index[-1] - prices.index[0]).days / 365.25
    tbl = pd.DataFrame({
        "Price": last,
        "1D %": ret(2), "1M %": ret(21), "6M %": ret(126), "1Y %": ret(252),
        "5Y CAGR %": ((last / prices.bfill().iloc[0]) ** (1 / yrs) - 1) * 100,
        "52W High": prices.tail(252).max(), "52W Low": prices.tail(252).min(),
    })
    tbl = tbl.join(fund)
    tbl["% from 52W High"] = (tbl["Price"] / tbl["52W High"] - 1) * 100
    tbl.index = [i.replace(".NS", "") for i in tbl.index]
    st.dataframe(tbl.round(2), use_container_width=True, height=500)
    st.download_button("Download CSV", tbl.round(2).to_csv().encode(), "nifty50_tracker.csv")

    st.subheader("Stock detail (5Y)")
    sel = st.selectbox("Stock", NIFTY50)
    st.plotly_chart(px.line(prices[f"{sel}.NS"].dropna(), title=sel), use_container_width=True)

    st.subheader("Normalised comparison (start = 100)")
    comp = st.multiselect("Compare", NIFTY50, default=["RELIANCE", "TCS", "HDFCBANK"])
    if comp:
        sub = prices[[f"{c}.NS" for c in comp]].dropna()
        st.plotly_chart(px.line(sub / sub.iloc[0] * 100), use_container_width=True)

# ===== TAB 3 =====
with tab3:
    st.subheader("Upcoming earnings (Nifty 50)")
    ed = load_earnings_dates()
    st.dataframe(ed.to_frame(), use_container_width=True) if len(ed) else st.info("Earnings dates abhi available nahi.")

    st.subheader("Macro / policy calendar")
    if os.path.exists("events.csv"):
        st.dataframe(pd.read_csv("events.csv"), use_container_width=True)
    else:
        st.info("events.csv banayein (columns: date,event) RBI MPC, CPI/GDP/IIP release, budget dates ke liye. Official calendars se dates bharein.")

st.caption("Data: Yahoo Finance, World Bank, FRED. Informational only, not investment advice.")
