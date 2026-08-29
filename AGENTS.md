# AGENTS.md

## Cursor Cloud specific instructions

This repo is **Aurea**: a FastAPI + static `web/` SPA (player valuation, scout, Süper Lig transfers)
plus a **Python 3.10+ CLI** TFF Fantezi Lig squad recommender under `src/`. Dependencies come from
`requirements.txt` (`pip install -r requirements.txt`). Site: `python -m app` (port 8787). CLI:
`python -m src.main` and `calistir.bat`. Tests: see README.

### Services / commands
- Site: `python -m app` (needs Transfermarkt open data on first run; writes `data/` and `models/`).
- Tests (offline, no network): `python3 -m unittest discover -s tests -v` (no live APIs required for the suite).
- CLI squad run: `python3 -m src.main` (flags documented in `README.md`).
- No linter/formatter and no CI are configured — there is nothing to run for lint.

### Non-obvious gotchas
- **Sofascore API is blocked from cloud VMs.** The stats fetch hits `www.sofascore.com/api/v1/...`
  which returns `403 {"reason":"challenge"}` from datacenter/cloud IPs even with `curl_cffi` browser
  impersonation (the site homepage returns 200, but the API is challenged). Because the pipeline
  requires Süper Lig stats, a full live squad run (`python -m src.main`) fails with
  `HATA: Oyuncu istatistiği boş.` here. This is an external network block, not a setup problem.
  A residential IP / proxy is needed for true end-to-end live runs.
- **Offline prices for local runs:** `cp data/prices.example.csv data/prices.csv` then use
  `python -m src.main --no-fetch-prices`. This still needs Sofascore for stats, so it only gets
  past price-fetching, not the stats step.
- To exercise the core ILP optimizer (`src/optimize.py`) + report (`src/report.py`) without network,
  feed `optimize_squad` a DataFrame with columns `player, display_name, team, position, price_m,
  projected_pts`. Optional `selection_pts` is the 3-week horizon used for squad picking; captain and
  autosub still use this-week `pts_if_plays`. It enforces TFF rules (100M budget, 2 GK / 5 DF / 5 MF / 3 FW, max 3 per club) and
  auto-picks formation + XI + bench + captain via PuLP/CBC (CBC ships with PuLP).
- Match strength lives in `src/team_model.py` (Poisson attack/defence, no JAX). It feeds fixture
  multipliers and player goal-share inside `src/scoring.py`; there is no standalone score predictor.
- `calibrate_leagues.py` (offline maintenance) imports `numpy`, which is **not** pinned in
  `requirements.txt` (usually present transitively via pandas). Not needed for normal squad runs —
  the calibrated model `data/league_translation.json` is already committed.
- TFF live prices need credentials (`data/tff_login.txt` or `TFF_EMAIL`/`TFF_PASSWORD`); the TFF/
  Keycloak endpoints may also be geo/IP-restricted from cloud VMs.
- Site `FANTASY_ROOT` defaults to this repo when `src/optimize.py` exists. Do not commit
  `data/tff_login.txt`, parquet warehouses, or `models/*.joblib`.
