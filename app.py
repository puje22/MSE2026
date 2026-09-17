import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="MSE Daily Prices", layout="wide")

DATA_PATH = "data/mse_daily_prices.csv"


@st.cache_data(ttl=3600)  # refresh at most hourly, so daily commits show up
def load_data():
    df = pd.read_csv(DATA_PATH)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad_rows = df["date"].isna().sum()
    if bad_rows:
        st.warning(f"Dropped {bad_rows} row(s) with an unparseable date.")
    df = df.dropna(subset=["date"])
    df = df.sort_values(["ticker", "date"])
    return df


df = load_data()
all_tickers = sorted(df["ticker"].unique())

st.title("Mongolian Stock Exchange — Daily Prices")
st.caption(
    f"Data source: old.mse.mn · {df['date'].min().date()} to "
    f"{df['date'].max().date()} · auto-updated daily via GitHub Actions"
)

# ---- Sidebar controls ------------------------------------------------------

st.sidebar.header("Filters")
selected = st.sidebar.multiselect(
    "Tickers", all_tickers, default=all_tickers[:5]
)

min_date = df["date"].min()
data_max_date = df["date"].max()
today = pd.Timestamp.now(tz="Asia/Ulaanbaatar").tz_localize(None).normalize()
max_date = max(data_max_date, today)  # let the picker reach today even if data lags

ytd_start = pd.Timestamp(year=today.year, month=1, day=1)
default_start = max(ytd_start, min_date)
default_end = data_max_date  # default to latest actual data, not future today

date_range = st.sidebar.date_input(
    "Date range", (default_start, default_end),
    min_value=min_date, max_value=max_date
)

if not selected:
    st.info("Pick at least one ticker in the sidebar to see charts.")
    st.stop()

if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
else:
    start, end = default_start, default_end

filtered = df[
    df["ticker"].isin(selected)
    & (df["date"] >= start)
    & (df["date"] <= end)
]

# ---- Latest snapshot table --------------------------------------------------


def trailing_pct_change(ticker_df, days):
    ticker_df = ticker_df.sort_values("date")
    if ticker_df.empty:
        return None
    latest_date = ticker_df["date"].iloc[-1]
    latest_close = ticker_df["close"].iloc[-1]
    target_date = latest_date - pd.Timedelta(days=days)
    hist = ticker_df[ticker_df["date"] <= target_date]
    if hist.empty:
        return None
    base_close = hist["close"].iloc[-1]
    return (latest_close / base_close - 1) * 100 if base_close else None


def ytd_pct_change(ticker_df):
    ticker_df = ticker_df.sort_values("date")
    if ticker_df.empty:
        return None
    latest_date = ticker_df["date"].iloc[-1]
    latest_close = ticker_df["close"].iloc[-1]
    year_start = pd.Timestamp(year=latest_date.year, month=1, day=1)
    hist = ticker_df[ticker_df["date"] >= year_start]
    if hist.empty:
        return None
    base_close = hist.iloc[0]["close"]
    return (latest_close / base_close - 1) * 100 if base_close else None


st.subheader("Latest close")
rows = []
for ticker in selected:
    tfull = df[df["ticker"] == ticker].sort_values("date")
    if tfull.empty:
        continue
    last_row = tfull.iloc[-1]
    prev_row = tfull.iloc[-2] if len(tfull) > 1 else None
    day_pct = (last_row["close"] / prev_row["close"] - 1) * 100 if prev_row is not None and prev_row["close"] else None
    rows.append({
        "ticker": ticker,
        "company_name": last_row["company_name"],
        "date": last_row["date"].date(),
        "close": last_row["close"],
        "change_%": round(day_pct, 2) if day_pct is not None else None,
        "30d_%": (lambda v: round(v, 2) if v is not None else None)(trailing_pct_change(tfull, 30)),
        "90d_%": (lambda v: round(v, 2) if v is not None else None)(trailing_pct_change(tfull, 90)),
        "ytd_%": (lambda v: round(v, 2) if v is not None else None)(ytd_pct_change(tfull)),
        "volume": last_row["volume"],
    })
latest = pd.DataFrame(rows)
st.dataframe(latest, use_container_width=True, hide_index=True)
st.caption(
    "30d/90d/YTD % change are based on each ticker's full price history "
    "(not limited by the date-range filter above)."
)

# ---- Price chart ------------------------------------------------------------

st.subheader("Close price over time")
fig = go.Figure()
for ticker in selected:
    tdf = filtered[filtered["ticker"] == ticker]
    fig.add_trace(go.Scatter(x=tdf["date"], y=tdf["close"], name=ticker, mode="lines"))
fig.update_layout(
    height=500,
    xaxis_title="Date",
    yaxis_title="Close price (MNT)",
    legend_title="Ticker",
    margin=dict(l=10, r=10, t=30, b=10),
)
st.plotly_chart(fig, use_container_width=True)

# ---- Normalized comparison ---------------------------------------------------

st.subheader("Normalized performance (rebased to 100)")
fig2 = go.Figure()
for ticker in selected:
    tdf = filtered[filtered["ticker"] == ticker].dropna(subset=["close"])
    if tdf.empty:
        continue
    base = tdf["close"].iloc[0]
    fig2.add_trace(go.Scatter(
        x=tdf["date"], y=(tdf["close"] / base) * 100, name=ticker, mode="lines"
    ))
fig2.update_layout(
    height=450,
    xaxis_title="Date",
    yaxis_title="Indexed close (start = 100)",
    margin=dict(l=10, r=10, t=30, b=10),
)
st.plotly_chart(fig2, use_container_width=True)

# ---- Stock Overview (52-week range, volume, moving averages) --------------

st.header("Stock Overview")
st.caption(
    "Technical snapshot only — not financial advice. This shows objective "
    "price/volume patterns; it is not a recommendation to buy, hold, or sell."
)

overview_ticker = st.selectbox("Select a ticker for a detailed overview", all_tickers)

tdf = df[df["ticker"] == overview_ticker].sort_values("date").reset_index(drop=True)

if len(tdf) < 2:
    st.info("Not enough history for this ticker yet.")
else:
    latest = tdf.iloc[-1]
    prev = tdf.iloc[-2]
    day_change_pct = (latest["close"] / prev["close"] - 1) * 100

    # 52-week window: trailing 365 calendar days from the latest data point
    window_start = latest["date"] - pd.Timedelta(days=365)
    window = tdf[tdf["date"] >= window_start]
    high_52w = window["high"].max()
    low_52w = window["low"].min()
    high_52w_date = window.loc[window["high"].idxmax(), "date"].date()
    low_52w_date = window.loc[window["low"].idxmin(), "date"].date()

    pct_off_high = (latest["close"] / high_52w - 1) * 100
    pct_off_low = (latest["close"] / low_52w - 1) * 100
    range_position = (
        (latest["close"] - low_52w) / (high_52w - low_52w) * 100
        if high_52w > low_52w else 50
    )

    # Volume: latest vs trailing 30-trading-day average (excluding today)
    vol_window = tdf.iloc[:-1].tail(30)
    avg_vol_30d = vol_window["volume"].mean() if len(vol_window) else None
    vol_vs_avg_pct = (
        (latest["volume"] / avg_vol_30d - 1) * 100
        if avg_vol_30d and avg_vol_30d > 0 else None
    )

    # Moving averages: simple (SMA) at 20/50/100/200 days, plus exponentially
    # weighted (EMA) at 20/50 days — EMA weights recent prices more heavily.
    tdf["sma20"] = tdf["close"].rolling(20, min_periods=1).mean()
    tdf["sma50"] = tdf["close"].rolling(50, min_periods=1).mean()
    tdf["sma100"] = tdf["close"].rolling(100, min_periods=1).mean()
    tdf["sma200"] = tdf["close"].rolling(200, min_periods=1).mean()
    tdf["ema20"] = tdf["close"].ewm(span=20, adjust=False).mean()
    tdf["ema50"] = tdf["close"].ewm(span=50, adjust=False).mean()
    sma50_latest = tdf["sma50"].iloc[-1]
    sma200_latest = tdf["sma200"].iloc[-1]

    # ---- Metric row ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        f"{overview_ticker} last close",
        f"{latest['close']:,.0f}",
        f"{day_change_pct:+.2f}%",
    )
    c2.metric("52-week high", f"{high_52w:,.0f}", f"{pct_off_high:+.1f}% from here")
    c3.metric("52-week low", f"{low_52w:,.0f}", f"{pct_off_low:+.1f}% from here")
    c4.metric(
        "Volume vs 30-day avg",
        f"{latest['volume']:,.0f}",
        f"{vol_vs_avg_pct:+.1f}%" if vol_vs_avg_pct is not None else "n/a",
    )

    # ---- 52-week range position bar ----
    st.write(
        f"**Position within 52-week range:** {range_position:.0f}% "
        f"(0% = 52w low on {low_52w_date}, 100% = 52w high on {high_52w_date})"
    )
    st.progress(min(max(range_position / 100, 0.0), 1.0))

    # ---- Price chart with 52w high/low and moving averages ----
    st.subheader(f"{overview_ticker} — price, moving averages & 52-week range")
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["close"], name="Close", mode="lines",
                               line=dict(width=2)))
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["sma20"], name="SMA 20",
                               mode="lines", line=dict(dash="dot")))
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["sma50"], name="SMA 50",
                               mode="lines", line=dict(dash="dot")))
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["sma100"], name="SMA 100",
                               mode="lines", line=dict(dash="dash")))
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["sma200"], name="SMA 200",
                               mode="lines", line=dict(dash="dash")))
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["ema20"], name="EMA 20 (weighted)",
                               mode="lines", line=dict(dash="dashdot")))
    fig3.add_trace(go.Scatter(x=tdf["date"], y=tdf["ema50"], name="EMA 50 (weighted)",
                               mode="lines", line=dict(dash="dashdot")))
    fig3.add_hline(y=high_52w, line_dash="dot", line_color="green",
                    annotation_text="52w high")
    fig3.add_hline(y=low_52w, line_dash="dot", line_color="red",
                    annotation_text="52w low")
    fig3.update_layout(
        height=500, xaxis_title="Date", yaxis_title="Price (MNT)",
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig3, use_container_width=True)
    st.caption(
        "SMA = simple moving average (equal-weighted). EMA = exponentially "
        "weighted moving average (recent prices weighted more heavily, reacts "
        "faster to new price moves). Click legend items to toggle lines on/off."
    )

    # ---- Volume chart ----
    st.subheader(f"{overview_ticker} — daily volume")
    fig4 = go.Figure()
    fig4.add_trace(go.Bar(x=tdf["date"], y=tdf["volume"], name="Volume"))
    fig4.update_layout(
        height=300, xaxis_title="Date", yaxis_title="Shares traded",
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig4, use_container_width=True)

    # ---- Objective technical snapshot (not a recommendation) ----
    st.subheader("Technical snapshot")
    signals = []
    signals.append(
        f"Price is {'above' if latest['close'] > sma50_latest else 'below'} "
        f"its 50-day moving average ({sma50_latest:,.0f})."
    )
    signals.append(
        f"Price is {'above' if latest['close'] > sma200_latest else 'below'} "
        f"its 200-day moving average ({sma200_latest:,.0f})."
    )
    sma20_latest = tdf["sma20"].iloc[-1]
    signals.append(
        f"Short-term (20-day) average is {'above' if sma20_latest > sma50_latest else 'below'} "
        f"the medium-term (50-day) average — sometimes read as a "
        f"{'bullish' if sma20_latest > sma50_latest else 'bearish'} crossover signal."
    )
    signals.append(
        f"Trading {range_position:.0f}% of the way up its 52-week range "
        f"({'closer to the 52-week high' if range_position > 50 else 'closer to the 52-week low'})."
    )
    if vol_vs_avg_pct is not None:
        signals.append(
            f"Volume today is {'above' if vol_vs_avg_pct > 0 else 'below'} "
            f"its 30-day average by {abs(vol_vs_avg_pct):.0f}%."
        )
    for s in signals:
        st.write(f"- {s}")
    st.caption(
        "These are objective, rule-based observations about price and volume "
        "patterns — they don't account for fundamentals, news, or company-specific "
        "risk, and are not a buy/hold/sell recommendation. This isn't financial advice."
    )

    # ---- Fundamentals (EPS, P/E, ROA, ROE) ----
    st.header("Fundamentals")
    try:
        fin_df = pd.read_csv("data/mse_financials.csv")
    except FileNotFoundError:
        fin_df = pd.DataFrame()

    ticker_fin = fin_df[fin_df["ticker"] == overview_ticker].sort_values("year") \
        if not fin_df.empty else pd.DataFrame()

    if ticker_fin.empty:
        st.info(
            f"No financial statement data found yet for {overview_ticker}. "
            "This fills in as the daily updater runs against members.mse.mn."
        )
    else:
        latest_fin = ticker_fin.iloc[-1]
        latest_fin_year = int(latest_fin["year"])
        current_year = pd.Timestamp.now().year
        years_behind = current_year - latest_fin_year

        st.info(
            f"**These are actual reported/audited figures, not projections or "
            f"estimates.** The most recent year shown is fiscal year "
            f"**{latest_fin_year}** — companies typically file annual reports "
            f"several months after fiscal year-end, so {current_year} figures "
            f"won't appear here until filed"
            + (f" (currently {years_behind} year(s) behind the calendar year)."
               if years_behind > 0 else ".")
        )
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("EPS (latest fiscal year)",
                   f"{latest_fin['eps']:,.0f}" if pd.notna(latest_fin['eps']) else "n/a")
        f2.metric("P/E ratio",
                   f"{latest_fin['pe_ratio']:.2f}" if pd.notna(latest_fin['pe_ratio']) else "n/a")
        f3.metric("ROA",
                   f"{latest_fin['roa']*100:.1f}%" if pd.notna(latest_fin['roa']) else "n/a")
        f4.metric("ROE",
                   f"{latest_fin['roe']*100:.1f}%" if pd.notna(latest_fin['roe']) else "n/a")

        fig5 = go.Figure()
        fig5.add_trace(go.Bar(x=ticker_fin["year"], y=ticker_fin["eps"], name="EPS"))
        fig5.update_layout(
            height=350, title="EPS by fiscal year",
            xaxis_title="Year", yaxis_title="EPS (MNT)",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig5, use_container_width=True)

        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=ticker_fin["year"], y=ticker_fin["roa"] * 100,
                                   name="ROA %", mode="lines+markers"))
        fig6.add_trace(go.Scatter(x=ticker_fin["year"], y=ticker_fin["roe"] * 100,
                                   name="ROE %", mode="lines+markers"))
        fig6.update_layout(
            height=350, title="ROA / ROE by fiscal year",
            xaxis_title="Year", yaxis_title="%",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig6, use_container_width=True)

        fig7 = go.Figure()
        fig7.add_trace(go.Bar(x=ticker_fin["year"], y=ticker_fin["net_income"], name="Net income"))
        fig7.add_trace(go.Bar(x=ticker_fin["year"], y=ticker_fin["total_assets"], name="Total assets"))
        fig7.update_layout(
            height=350, title="Net income vs. total assets", barmode="group",
            xaxis_title="Year", yaxis_title="MNT",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig7, use_container_width=True)

        with st.expander("Full financial history"):
            st.dataframe(ticker_fin, use_container_width=True, hide_index=True)

        st.caption(
            "Source: members.mse.mn company financial statements. Figures are "
            "as filed and may lag the current fiscal year. Not financial advice."
        )

    # ---- Dividend announcement history (dates only, not per-share amounts) ----
    st.subheader("Dividend announcement history")
    try:
        div_df = pd.read_csv("data/mse_dividends.csv")
    except FileNotFoundError:
        div_df = pd.DataFrame()

    ticker_div = div_df[div_df["ticker"] == overview_ticker] if not div_df.empty else pd.DataFrame()
    if ticker_div.empty:
        st.info(f"No dividend declaration announcements found for {overview_ticker}.")
    else:
        st.dataframe(
            ticker_div[["date", "headline"]].sort_values("date", ascending=False),
            use_container_width=True, hide_index=True,
        )
    st.caption(
        "These are declaration dates pulled from MSE announcement headlines — "
        "not per-share dividend amounts, which aren't available in structured "
        "form from this data source. See the original MSE announcement for the "
        "exact amount declared."
    )

# ---- Raw data / download -----------------------------------------------------

with st.expander("Raw data"):
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.download_button(
        "Download filtered CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name="mse_filtered.csv",
        mime="text/csv",
    )
