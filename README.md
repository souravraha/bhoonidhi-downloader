# Bhoonidhi (NRSC) Satellite Data Downloader

Search & download satellite products — **all registered STAC collections by
default** (ISRO CartoSat/ResourceSat/EOS-04/06, NISAR, Novasar, Sentinel —
incl. LISS-4, LISS-3, OCM, AWIFS, SAR — 63 collections at last check) — from
the official [Bhoonidhi API](https://bhoonidhi-api.nrsc.gov.in): STAC
catalogue search plus authenticated product download.

A registered Bhoonidhi account is required:
<https://bhoonidhi.nrsc.gov.in/bhoonidhi/login.html>

## Features

- Password + refresh-token auth against `POST /auth/token`, transparent
  re-authentication on HTTP 401, JWT cached in `.auth/bhoonidhi_token.json`
  (mode 600, gitignored)
- STAC search with paging, CQL2-JSON filters, and GeoJSON / point / bbox AOIs
- Searches across **every collection registered on the API** (fetched live
  from `GET /data/collections`); narrow with `--platform` (e.g. `EOS-06`) or
  explicit `--collections`
- Downloads every eligible item by default; `--max-downloads` caps if you want
- Rate-limit aware: search 3 r/s, download starts 2/min, ≤ 5 concurrent
  streams (2 workers), HTTP 429/412 → back-off, 504 → retry
- Only `Online = Y` items are downloaded (per the API spec, `N` products must
  be ordered via Browse & Order anyway)
- Resumable: already-downloaded zips are skipped; writes
  `search_results.json` and `manifest.json` next to the product files

Stdlib only — Python 3.10+, no dependencies to install.

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

`.envrc` sources `.envrc.local` automatically when present (both are
gitignored, so the template is the only tracked file).

## Usage

Run from the repo root:

```bash
# search + list every registered collection over the Delhi-NCR benchmark site
python scripts/download_bhoonidhi.py \
    --site delhi-urban --start 2025-01-01 --end 2025-02-28 --preview

# same search, then download every eligible product into data/bhoonidhi/
python scripts/download_bhoonidhi.py \
    --site thar-desert --start 2025-01-01 --end 2025-02-28 --download

# only one platform, e.g. the EOS-06 ocean-colour collections
python scripts/download_bhoonidhi.py \
    --platform EOS-06 --site delhi-urban --start 2025-01-01 \
    --end 2025-02-28 --preview

# cap the number of products fetched (default: no cap)
python scripts/download_bhoonidhi.py \
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

### Collection scope

| flag | meaning |
|------|---------|
| *(default)* | every collection registered on the API (listed live, 63 at last check) |
| `--platform` | every collection whose id starts with the prefix, e.g. `EOS-06`, `ResourceSat-2A`, `NISAR`, `Sentinel-1A` |
| `--collections A B …` | an explicit list of STAC collection ids (overrides both) |

### Other useful flags

- `--online-only` / `--no-online-filter` — restrict to `Online = Y` (default: on)
- `--extra-filter` — raw CQL2-JSON, e.g.
  `'{"args":[{"property":"Cloud_Cover"},"80"],"op":"lt"}'`
- `--limit` — max items returned by the search (default 500, the API page cap)
- `--max-downloads` — cap on products fetched (default 0 = no cap)
- `--out` — output directory (default `data/bhoonidhi/`)
- `--reauth` — discard the cached token and force a fresh password login

## Output

Per run, in `--out`:

- `search_results.json` — the full STAC item list returned by the search
- `manifest.json` — per-product download status, timestamps
- `<Collection>__<ItemID>.zip` — the product archives
