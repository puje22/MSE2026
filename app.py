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
    f"Data source: members.mse.mn · {df['date'].min().date()} to "
    f"{df['date'].max().date()} · auto-updated daily via GitHub Actions"
)

# ---- Sidebar controls ------------------------------------------------------

st.sidebar.header("Filters")
default_tickers = ["QPAY"] if "QPAY" in all_tickers else all_tickers[:1]
selected = st.sidebar.multiselect(
    "Tickers", all_tickers, default=default_tickers
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

# ---- Signals & Opportunities (scans the FULL watchlist, not just selected) --

st.header("🔔 Signals & Opportunities")
st.caption(
    "Scans your full watchlist (all tickers, full history) for notable "
    "technical patterns — independent of the ticker/date filters above. "
    "These are objective, rule-based flags, not predictions or "
    "recommendations. Always do your own research. This isn't financial advice."
)


def _compute_watchlist_signals(ticker_df):
    tdf = ticker_df.sort_values("date").reset_index(drop=True)
    if len(tdf) < 30:
        return None

    tdf["sma50"] = tdf["close"].rolling(50, min_periods=1).mean()
    tdf["sma200"] = tdf["close"].rolling(200, min_periods=1).mean()
    gap_pct = (tdf["sma50"] - tdf["sma200"]) / tdf["sma200"] * 100

    latest = tdf.iloc[-1]
    latest_gap = gap_pct.iloc[-1]
    lookback_idx = max(0, len(gap_pct) - 6)  # ~5 trading days ago
    prior_gap = gap_pct.iloc[lookback_idx]
    converging = abs(latest_gap) < abs(prior_gap)

    # RSI (14-day)
    delta = tdf["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14, min_periods=1).mean()
    avg_loss = loss.rolling(14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi_latest = (100 - (100 / (1 + rs))).fillna(50).iloc[-1]

    # 52-week range position
    window_start = latest["date"] - pd.Timedelta(days=365)
    window = tdf[tdf["date"] >= window_start]
    high52, low52 = window["high"].max(), window["low"].min()
    range_pos = (latest["close"] - low52) / (high52 - low52) * 100 if high52 > low52 else 50

    # Volume vs 30-day average
    vol_hist = tdf.iloc[:-1].tail(30)
    avg_vol = vol_hist["volume"].mean() if len(vol_hist) else None
    vol_ratio = (latest["volume"] / avg_vol) if avg_vol else None

    flags = []

    # Crossover already happened in the last 5 trading days
    above = tdf["sma50"] > tdf["sma200"]
    cross_events = above.astype(int).diff()
    recent = cross_events.iloc[-5:]
    if (recent == 1).any():
        flags.append(("cross", "🟢 Golden Cross (just occurred)",
                      "SMA50 crossed above SMA200 within the last 5 trading days"))
    elif (recent == -1).any():
        flags.append(("cross", "🔴 Death Cross (just occurred)",
                      "SMA50 crossed below SMA200 within the last 5 trading days"))
    # Nearing a crossover: gap is small AND shrinking
    elif abs(latest_gap) < 2 and converging:
        if latest_gap < 0:
            flags.append(("cross", "🟡 Golden Cross nearing",
                          f"SMA50 is {abs(latest_gap):.1f}% below SMA200 and closing the gap"))
        else:
            flags.append(("cross", "🟠 Death Cross nearing",
                          f"SMA50 is {abs(latest_gap):.1f}% above SMA200 and the gap is narrowing"))

    if rsi_latest > 70:
        flags.append(("rsi", "📈 Overbought (RSI)", f"RSI at {rsi_latest:.0f} (>70)"))
    elif rsi_latest < 30:
        flags.append(("rsi", "📉 Oversold (RSI)", f"RSI at {rsi_latest:.0f} (<30)"))

    if range_pos >= 95:
        flags.append(("range", "🚀 Near 52-week high", f"{range_pos:.0f}% of 52-week range"))
    elif range_pos <= 5:
        flags.append(("range", "⚠️ Near 52-week low", f"{range_pos:.0f}% of 52-week range"))

    if vol_ratio and vol_ratio >= 2:
        flags.append(("volume", "🔊 Volume spike", f"{vol_ratio:.1f}x the 30-day average"))

    if not flags:
        return None
    return [
        {"ticker": None, "category": cat, "signal": label, "detail": detail,
         "date": latest["date"].date(), "close": latest["close"]}
        for cat, label, detail in flags
    ]


all_signal_rows = []
for t in all_tickers:
    res = _compute_watchlist_signals(df[df["ticker"] == t])
    if res:
        for row in res:
            row["ticker"] = t
            all_signal_rows.append(row)

if not all_signal_rows:
    st.info("No notable signals across your watchlist right now.")
else:
    signals_df = pd.DataFrame(all_signal_rows)
    tab_cross, tab_rsi, tab_range, tab_vol = st.tabs(
        ["Crossover watch", "RSI extremes", "52-week range", "Volume spikes"]
    )
    display_cols = ["ticker", "signal", "detail", "date", "close"]
    with tab_cross:
        rows = signals_df[signals_df["category"] == "cross"]
        if rows.empty:
            st.info("No crossover activity right now.")
        else:
            st.dataframe(rows[display_cols], use_container_width=True, hide_index=True)
    with tab_rsi:
        rows = signals_df[signals_df["category"] == "rsi"]
        if rows.empty:
            st.info("Nothing at an RSI extreme right now.")
        else:
            st.dataframe(rows[display_cols], use_container_width=True, hide_index=True)
    with tab_range:
        rows = signals_df[signals_df["category"] == "range"]
        if rows.empty:
            st.info("Nothing near its 52-week high/low right now.")
        else:
            st.dataframe(rows[display_cols], use_container_width=True, hide_index=True)
    with tab_vol:
        rows = signals_df[signals_df["category"] == "volume"]
        if rows.empty:
            st.info("No volume spikes right now.")
        else:
            st.dataframe(rows[display_cols], use_container_width=True, hide_index=True)

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

overview_ticker = st.selectbox(
    "Select a ticker for a detailed overview", all_tickers,
    index=all_tickers.index("QPAY") if "QPAY" in all_tickers else 0,
)

tdf_full = df[df["ticker"] == overview_ticker].sort_values("date").reset_index(drop=True)

if len(tdf_full) < 2:
    st.info("Not enough history for this ticker yet.")
else:
    # Compute all indicators on FULL history first (so early points in a
    # short display window still have correct long-lookback averages),
    # then slice down to the sidebar date range for display/metrics.
    tdf_full["sma20"] = tdf_full["close"].rolling(20, min_periods=1).mean()
    tdf_full["sma50"] = tdf_full["close"].rolling(50, min_periods=1).mean()
    tdf_full["sma100"] = tdf_full["close"].rolling(100, min_periods=1).mean()
    tdf_full["sma200"] = tdf_full["close"].rolling(200, min_periods=1).mean()
    tdf_full["ema20"] = tdf_full["close"].ewm(span=20, adjust=False).mean()
    tdf_full["ema50"] = tdf_full["close"].ewm(span=50, adjust=False).mean()

    # RSI (14-day)
    delta = tdf_full["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14, min_periods=1).mean()
    avg_loss = loss.rolling(14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    tdf_full["rsi14"] = (100 - (100 / (1 + rs))).fillna(50)

    # Golden Cross (SMA50 crosses above SMA200) / Death Cross (crosses below)
    above = tdf_full["sma50"] > tdf_full["sma200"]
    cross_change = above.astype(int).diff()
    tdf_full["cross_event"] = cross_change.map({1: "golden", -1: "death"})

    # Slice to the sidebar date range for display
    tdf = tdf_full[(tdf_full["date"] >= start) & (tdf_full["date"] <= end)].reset_index(drop=True)

    if tdf.empty:
        st.info(f"No data for {overview_ticker} in the selected date range.")
    else:
        latest = tdf.iloc[-1]
        prev_idx = tdf_full.index[tdf_full["date"] == latest["date"]][0]
        prev = tdf_full.iloc[prev_idx - 1] if prev_idx > 0 else latest
        day_change_pct = (latest["close"] / prev["close"] - 1) * 100 if prev["close"] else 0

        # 52-week window: trailing 365 days ending at the latest point IN VIEW
        # (uses tdf_full so the lookback can reach before the display window)
        window_start = latest["date"] - pd.Timedelta(days=365)
        window = tdf_full[(tdf_full["date"] >= window_start) & (tdf_full["date"] <= latest["date"])]
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

        # Volume vs trailing 30-trading-day average, anchored at latest-in-view
        vol_hist = tdf_full[tdf_full["date"] <= latest["date"]]
        vol_window = vol_hist.iloc[:-1].tail(30)
        avg_vol_30d = vol_window["volume"].mean() if len(vol_window) else None
        vol_vs_avg_pct = (
            (latest["volume"] / avg_vol_30d - 1) * 100
            if avg_vol_30d and avg_vol_30d > 0 else None
        )

        sma20_latest = latest["sma20"]
        sma50_latest = latest["sma50"]
        sma100_latest = latest["sma100"]
        sma200_latest = latest["sma200"]
        rsi_latest = latest["rsi14"]

        # ---- Metric row ----
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            f"{overview_ticker} close on {latest['date'].date()}",
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

        # ---- Price chart with 52w high/low, moving averages, and cross markers ----
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

        # Mark any golden/death crosses that fall within the visible window.
        # (Using add_shape + add_annotation directly rather than add_vline,
        # since add_vline's internal annotation-placement math breaks on
        # datetime x-values in some plotly versions.)
        crosses_in_view = tdf[tdf["cross_event"].notna()]
        for _, cr in crosses_in_view.iterrows():
            is_golden = cr["cross_event"] == "golden"
            color = "gold" if is_golden else "black"
            cross_x = cr["date"].strftime("%Y-%m-%d")
            fig3.add_shape(
                type="line", x0=cross_x, x1=cross_x, y0=0, y1=1,
                yref="paper", line=dict(color=color, dash="solid", width=1.5),
            )
            fig3.add_annotation(
                x=cross_x, y=1, yref="paper", yanchor="bottom", showarrow=False,
                text="Golden Cross" if is_golden else "Death Cross",
                font=dict(color=color, size=10),
            )

        fig3.update_layout(
            height=500, xaxis_title="Date", yaxis_title="Price (MNT)",
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig3, use_container_width=True)
        st.caption(
            "SMA = simple moving average (equal-weighted). EMA = exponentially "
            "weighted moving average (recent prices weighted more heavily, reacts "
            "faster to new price moves). Gold/black vertical lines mark Golden "
            "Cross (SMA50 crosses above SMA200) and Death Cross (crosses below) "
            "events. Click legend items to toggle lines on/off."
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

        # ---- Technical signals (objective, rule-based — not a recommendation) ----
        st.subheader("Technical signals")

        # Most recent golden/death cross overall (may be before the display window)
        all_crosses = tdf_full[tdf_full["cross_event"].notna()]
        last_cross = all_crosses.iloc[-1] if not all_crosses.empty else None

        # Simple trend-structure score: -3 (bearish) to +3 (bullish)
        score = 0
        score += 1 if latest["close"] > sma50_latest else -1
        score += 1 if latest["close"] > sma200_latest else -1
        score += 1 if sma50_latest > sma200_latest else -1

        if score >= 2:
            bias_label, bias_color = "Bullish trend", "🟢"
        elif score <= -2:
            bias_label, bias_color = "Bearish trend", "🔴"
        else:
            bias_label, bias_color = "Neutral / mixed trend", "🟡"

        st.markdown(f"### {bias_color} Overall technical bias: **{bias_label}**")
        st.caption(
            "Based purely on trend structure (price vs. moving averages, "
            "SMA50 vs. SMA200). In trend-following systems this is sometimes "
            "read informally as 'buy' (bullish), 'sell' (bearish), or 'hold' "
            "(neutral) — but it says nothing about fundamentals, valuation, "
            "or company-specific risk. **This is not financial advice or a "
            "recommendation to buy, hold, or sell.**"
        )

        signals = []
        if last_cross is not None:
            cross_word = "Golden Cross" if last_cross["cross_event"] == "golden" else "Death Cross"
            days_ago = (latest["date"] - last_cross["date"]).days
            signals.append(
                f"Most recent SMA50/SMA200 crossover: **{cross_word}** on "
                f"{last_cross['date'].date()} ({days_ago} days ago)."
            )
        else:
            signals.append("No SMA50/SMA200 crossover found yet in this ticker's history.")

        signals.append(
            f"Price is {'above' if latest['close'] > sma50_latest else 'below'} "
            f"its 50-day moving average ({sma50_latest:,.0f})."
        )
        signals.append(
            f"Price is {'above' if latest['close'] > sma200_latest else 'below'} "
            f"its 200-day moving average ({sma200_latest:,.0f})."
        )
        signals.append(
            f"Short-term (20-day) average is {'above' if sma20_latest > sma50_latest else 'below'} "
            f"the medium-term (50-day) average."
        )

        rsi_read = "overbought (>70)" if rsi_latest > 70 else "oversold (<30)" if rsi_latest < 30 else "neutral"
        signals.append(f"RSI (14-day): **{rsi_latest:.0f}** — conventionally read as {rsi_read}.")

        signals.append(
            f"Trading {range_position:.0f}% of the way up its 52-week range "
            f"({'closer to the 52-week high' if range_position > 50 else 'closer to the 52-week low'})."
        )
        if vol_vs_avg_pct is not None:
            signals.append(
                f"Volume is {'above' if vol_vs_avg_pct > 0 else 'below'} "
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
