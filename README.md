# Bhoonidhi (NRSC) Satellite Data Downloader

Search & download LISS-4 (ResourceSat-2 / 2A L2) products from the official
[Bhoonidhi API](https://bhoonidhi-api.nrsc.gov.in) — STAC catalogue search plus
authenticated product download.

A registered Bhoonidhi account is required:
<https://bhoonidhi.nrsc.gov.in/bhoonidhi/login.html>

## Features

- Password + refresh-token auth against `POST /auth/token`, transparent
  re-authentication on HTTP 401, JWT cached in `.auth/bhoonidhi_token.json`
  (mode 600, gitignored)
- STAC search with paging, CQL2-JSON filters, and GeoJSON / point / bbox AOIs
- Rate-limit aware: search 3 r/s, download starts 2/min, ≤ 5 concurrent
  streams (2 workers), HTTP 429/412 → back-off, 504 → retry
- Only `Online = Y` items are downloaded (per the API spec, `N` products must
  be ordered via Browse & Order anyway)
- Resumable: already-downloaded zips are skipped; writes `search_results.json`
  and `manifest.json` next to the product files

Stdlib only — Python 3.11+, no runtime dependencies. A small [pixi](https://pixi.sh)
project is included so you can just `pixi run preview` / `pixi run download`.

## Credentials

Set the two variables (e.g. in `.envrc.local`, see below):

```bash
export BHOONIDHI_USER=...
export BHOONIDHI_PASS=...
```

Alternatively pass `--user` / `--passwd` on the command line; the password is
prompted if omitted.

## Install credentials with direnv (optional)

Copy the template, then fill in your values:

```bash
cp .envrc.local.example .envrc.local
direnv allow   # if direnv is installed
```

`.envrc` sources `.envrc.local` automatically when present. Both `.envrc`
and the `.envrc.local.example` template are tracked (no secrets); only
`.envrc.local` is gitignored.

## Usage

`pixi run preview` / `pixi run download` are pre-wired for the Delhi-NCR
site, Jan–Feb 2025. To run anything else, call the script directly (any
`python` ≥ 3.11 works):

```bash
# search + list LISS-4 over the Delhi-NCR benchmark site (no download)
pixi run python scripts/download_bhoonidhi.py \
    --site delhi-urban --start 2025-01-01 --end 2025-02-28 --preview

# same search, then download up to 4 products into data/bhoonidhi/
pixi run python scripts/download_bhoonidhi.py \
    --site thar-desert --start 2025-01-01 --end 2025-02-28 \
    --download --max-downloads 4
```

### AOI options (one required)

| flag        | meaning                                              |
|-------------|------------------------------------------------------|
| `--site`    | one of the 6 PS-10 benchmark sites (`--help` lists them) |
| `--point`   | AOI centre as `lon,lat`, radius via `--radius-km`   |
| `--aoi-file`| GeoJSON file whose geometry bounds the search        |
| `--bbox`    | `west,south,east,north`                              |

### Other useful flags

- `--online-only` / `--no-online-filter` — restrict to `Online = Y` (default: on)
- `--extra-filter` — raw CQL2-JSON, e.g.
  `'{"args":[{"property":"Cloud_Cover"},"80"],"op":"lt"}'`
- `--limit` — max items to return (API cap 500)
- `--max-downloads` — cap on products fetched
- `--out` — output directory (default `data/bhoonidhi/`)
- `--reauth` — discard the cached token and force a fresh password login

## Output

Per run, in `--out`:

- `search_results.json` — the full STAC item list returned by the search
- `manifest.json` — per-product download status, timestamps
- `<Collection>__<ItemID>.zip` — the product archives
