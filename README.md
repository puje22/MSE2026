# MSE Daily Prices — auto-updating dashboard

Scrapes daily OHLCV data for 21 MSE tickers from `old.mse.mn`, updates itself
daily via GitHub Actions, and displays it in a Streamlit dashboard.

## One-time setup

1. **Create a GitHub repo** and push this whole folder to it.

2. **Build the ticker→ID map** (run locally, once, in the folder where your
   original `mse_scrape_cache.json` lives — the one from the full 1-3000 ID
   crawl you already ran):

   ```bash
   python scripts/build_ticker_map.py
   ```

   This writes `ticker_ids.json`. Move/copy it into `scripts/ticker_ids.json`
   in this repo and commit it. (If MFG or XOC are still missing after the
   1-3000 crawl, they likely use a different URL pattern — let me know and
   we'll dig into that separately; everything else will work fine without
   them.)

3. **Seed the data file.** `data/mse_daily_prices.csv` already contains your
   cleaned historical scrape — just commit it as-is.

4. **Push to GitHub.** The workflow in `.github/workflows/daily_update.yml`
   will start running automatically on its schedule (09:00 UTC daily by
   default — edit the cron line if you want a different time). You can also
   trigger it manually anytime from the repo's **Actions** tab →
   "Daily MSE Data Update" → **Run workflow**.

5. **Deploy the dashboard** on [Streamlit Community Cloud](https://streamlit.io/cloud)
   (free):
   - Sign in with GitHub, click "New app"
   - Point it at your repo, branch `main`, file `app.py`
   - Deploy

   Streamlit Cloud automatically redeploys/rereads the repo whenever it
   changes — so once the daily GitHub Action commits new data, your live
   dashboard picks it up (the app also caches data for at most 1 hour, so
   even without a redeploy it'll refresh on its own).

## How the pieces fit together

```
scripts/scraper_lib.py       shared fetch + parse logic
scripts/ticker_ids.json      ticker -> internal MSE company ID (built once)
scripts/daily_update.py      run daily: fetches 21 pages, merges into CSV
.github/workflows/*.yml      cron trigger + commit-back
data/mse_daily_prices.csv    the growing master dataset
app.py                       Streamlit dashboard reading that CSV
```

## Local testing

```bash
pip install -r requirements.txt
python scripts/daily_update.py     # test the updater manually
streamlit run app.py               # preview the dashboard locally
```
