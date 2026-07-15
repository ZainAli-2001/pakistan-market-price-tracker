# Pakistan E-commerce Price Tracker

A pipeline that scrapes daily staple food prices from two major Pakistani
e-commerce platforms and logs them as a growing time series — built to
have real market data to forecast against, instead of a synthetic Kaggle
dataset.

## What it tracks

- **Sources:** Daraz.pk, Naheed.pk
- **Categories:** flour, rice, cooking oil, pulses, sugar, ghee, dairy, tea
- **Frequency:** twice daily, via GitHub Actions
- **Storage:** Supabase (Postgres) — every run appends new price
  observations, nothing is overwritten, so the full history is always
  queryable

## Features

- Retries failed requests with backoff instead of dropping the page
- Filters out non-commodity noise before it reaches the dataset (e.g.
  hair oil showing up under "cooking oil")
- Cross-source price validation, checked in both directions (too expensive
or suspiciously cheap), preferring each source's own current-run median
and borrowing the other's (or a static fallback) only when its own
sample is too thin
- Every rejected item is logged with a reason, not just silently dropped
- Each price row is tagged with the exact pipeline version that produced
  it, so results stay comparable across future changes

## How to use

### Setup

```bash
git clone https://github.com/ZainAli-2001/pk-ecommerce-price-pipeline.git
cd pk-ecommerce-price-pipeline
pip install -r requirements.txt
pip install -r requirements-dev.txt   # optional — adds pandas, only needed to run
                                      # daraz_scraper.py / naheed_scraper.py standalone
```

Create a free [Supabase](https://supabase.com) project, run the schema
SQL in `database.py` once in the SQL Editor, then set:

```bash
export SUPABASE_URL=...
export SUPABASE_KEY=...   # service_role key, not anon
```

### Running

```bash
python main.py
```

Scrapes both sources and saves everything to Supabase.

### Dry run

```bash
python main.py --dry-run
```

Runs the full scrape and validation pipeline exactly as normal, but skips
the database write — useful for testing changes without touching real
data.

### Debug mode

Set `DEBUG_DARAZ` / `DEBUG_NAHEED` to `True` in `utils/config.py` to also
write, per run, to a local `debug/` folder:

- A CSV of every rejected item and why it was rejected
- Raw HTML/JSON snapshots when a page's structure looks unexpected
- Verbose per-item parse logs

(Failed-request logs are written to `debug/` on every run regardless of
this flag — they're not gated behind debug mode.)

## Status

Actively running. Forecasting model and analysis are being built as a
separate follow-up project.

## Tech stack

Python · BeautifulSoup · Supabase (Postgres) · GitHub Actions
