import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="MSE Daily Prices", layout="wide")

DATA_PATH = "data/mse_daily_prices.csv"


@st.cache_data(ttl=3600)  # refresh at most hourly, so daily commits show up
def load_data():
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.sort_values(["ticker", "date"])
    grouped = df.groupby("ticker", group_keys=False)
    for period in (20, 50, 200):
        df[f"ma_{period}"] = grouped["close"].transform(
            lambda values, window=period: values.rolling(window, min_periods=1).mean()
        )
    df["volume_ma_20"] = grouped["volume"].transform(
        lambda values: values.rolling(20, min_periods=1).mean()
    )
    df["week_52_low"] = grouped["low"].transform(
        lambda values: values.rolling(252, min_periods=1).min()
    )
    df["week_52_high"] = grouped["high"].transform(
        lambda values: values.rolling(252, min_periods=1).max()
    )
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

min_date, max_date = df["date"].min(), df["date"].max()
date_range = st.sidebar.date_input(
    "Date range", (min_date, max_date), min_value=min_date, max_value=max_date
)

if not selected:
    st.info("Pick at least one ticker in the sidebar to see charts.")
    st.stop()

if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
else:
    start, end = min_date, max_date

filtered = df[
    df["ticker"].isin(selected)
    & (df["date"] >= start)
    & (df["date"] <= end)
]

# ---- Latest snapshot table --------------------------------------------------

st.subheader("Latest snapshot")
latest = (
    filtered.sort_values("date")
    .groupby("ticker")
    .tail(2)
)
latest_rows = []
for ticker in selected:
    ticker_rows = latest[latest["ticker"] == ticker].sort_values("date")
    if ticker_rows.empty:
        continue
    row = ticker_rows.iloc[-1]
    range_size = row["week_52_high"] - row["week_52_low"]
    latest_rows.append({
        "ticker": ticker,
        "company_name": row["company_name"],
        "date": row["date"].date(),
        "close": row["close"],
        "change_%": (
            round((row["close"] / ticker_rows.iloc[-2]["close"] - 1) * 100, 2)
            if len(ticker_rows) > 1 else None
        ),
        "volume": row["volume"],
        "52-week low": row["week_52_low"],
        "52-week high": row["week_52_high"],
        "range position_%": round(
            (row["close"] - row["week_52_low"]) / range_size * 100, 1
        ) if range_size else 100.0,
    })
latest = pd.DataFrame(latest_rows)
st.dataframe(latest, use_container_width=True, hide_index=True)

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

# ---- Moving averages --------------------------------------------------------

st.subheader("Moving averages")
fig_ma = go.Figure()
for ticker in selected:
    tdf = filtered[filtered["ticker"] == ticker]
    fig_ma.add_trace(go.Scatter(
        x=tdf["date"], y=tdf["close"], name=f"{ticker} close", mode="lines"
    ))
    for period, column in [(20, "ma_20"), (50, "ma_50"), (200, "ma_200")]:
        fig_ma.add_trace(go.Scatter(
            x=tdf["date"],
            y=tdf[column],
            name=f"{ticker} MA{period}",
            mode="lines",
            line=dict(dash="dot" if period != 200 else "dash"),
            visible="legendonly" if period == 200 else True,
        ))
fig_ma.update_layout(
    height=500,
    xaxis_title="Date",
    yaxis_title="Price (MNT)",
    legend_title="Series",
    margin=dict(l=10, r=10, t=30, b=10),
)
st.plotly_chart(fig_ma, use_container_width=True)

# ---- Volume trends ----------------------------------------------------------

st.subheader("Volume trends")
fig_volume = go.Figure()
for ticker in selected:
    tdf = filtered[filtered["ticker"] == ticker]
    fig_volume.add_trace(go.Bar(
        x=tdf["date"], y=tdf["volume"], name=f"{ticker} volume", opacity=0.45
    ))
    fig_volume.add_trace(go.Scatter(
        x=tdf["date"],
        y=tdf["volume_ma_20"],
        name=f"{ticker} 20-day avg",
        mode="lines",
    ))
fig_volume.update_layout(
    height=400,
    barmode="overlay",
    xaxis_title="Date",
    yaxis_title="Shares traded",
    legend_title="Series",
    margin=dict(l=10, r=10, t=30, b=10),
)
st.plotly_chart(fig_volume, use_container_width=True)

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

# ---- Raw data / download -----------------------------------------------------

with st.expander("Raw data"):
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.download_button(
        "Download filtered CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name="mse_filtered.csv",
        mime="text/csv",
    )
