# bhoonidhi-cli

Search & download **LISS-4** (ResourceSat-2 / 2A L2) satellite products from the
official [Bhoonidhi (NRSC) API](https://bhoonidhi-api.nrsc.gov.in) — STAC
catalogue search plus authenticated product download.

A **standalone, stdlib-only** Python package: **no runtime dependencies**
(Python 3.11+). Works as a command, a module, or a library.

> A registered Bhoonidhi account is required:
> <https://bhoonidhi.nrsc.gov.in/bhoonidhi/login.html>

## Features

- Password + refresh-token auth against `POST /auth/token`, transparent
  re-authentication on HTTP 401, JWT cached under `~/.config/bhoonidhi_cli/`
  (XDG-aware, mode 600) and refreshed automatically when it expires
- STAC search with paging, CQL2-JSON filters, and GeoJSON / point / bbox AOIs
- Six PS-10 benchmark-site presets (`--site delhi-urban`, `--site thar-desert`, …)
- Rate-limit aware: search 3 r/s, download starts ≤ 2/min, ≤ 5 concurrent
  streams (2 workers), HTTP 429/412 → back-off, 504 / 401 → retry
- Only `Online = Y` items are downloaded (per the API spec, `N` products must
  be ordered via Browse & Order anyway)
- Resumable: already-downloaded zips are skipped; writes `search_results.json`
  and `manifest.json` next to the product files

## Install

Everything is published on GitHub (no PyPI):

```bash
# 1) GitHub Release artifact — simplest, no registry setup needed
pipx install https://github.com/souravraha/bhoonidhi-downloader/releases/latest/download/bhoonidhi_cli-0.1.0-py3-none-any.whl

# …or plain pip:
pip install "bhoonidhi-cli @ https://github.com/souravraha/bhoonidhi-downloader/releases/latest/download/bhoonidhi_cli-0.1.0-py3-none-any.whl"

# 2) GitHub Packages (PyPI registry) — needs a PAT with `read:packages`
export PIP_INDEX_URL="https://<user>:<PAT>@github.com/souravraha/bhoonidhi-downloader/pypi/simple"
pip install bhoonidhi-cli
unset PIP_INDEX_URL
```

> **Releases:** tag a version and CI does the rest —
> `git tag v0.1.0 && git push origin v0.1.0` builds the wheel, creates the
> GitHub Release, and pushes to the repo's Packages registry.

From a source checkout (development):

```bash
pixi install     # or: python -m venv .venv && .venv/bin/pip install . 
pixi run install # -> pip install --no-deps . , giving you `bhoonidhi`
```

`bhoonidhi-cli` is *not* the same project as the community
[`bhoonidhi-downloader`](https://pypi.org/project/bhoonidhi-downloader/)
(which ships the `bhd` command) — this one is purpose-built for LISS-4,
zero-dependency.

## Credentials

Set the two variables (e.g. via direnv, see below):

```bash
export BHOONIDHI_USER=...
export BHOONIDHI_PASS=...
```

Alternatively pass `--user` / `--passwd` on the command line; the password is
prompted if omitted. The password is held in memory only and never written to
disk; the JWT cache lives at `~/.config/bhoonidhi_cli/bhoonidhi_token.json`
(mode 600, overridable via `$BHOONIDHI_TOKEN_DIR` / `$XDG_CONFIG_HOME`).

### Install credentials with direnv (optional)

```bash
cp .envrc.local.example .envrc.local
direnv allow   # if direnv is installed
```

`.envrc` sources `.envrc.local` automatically when present. Only `.envrc.local`
is gitignored.

## Usage

```bash
# search + list LISS-4 over the Delhi-NCR benchmark site (no download)
bhoonidhi --site delhi-urban --start 2025-01-01 --end 2025-02-28 --preview

# same search, then download up to 4 products (default ~/bhoonidhi_downloads/)
bhoonidhi --site thar-desert --start 2025-01-01 --end 2025-02-28 \
    --download --max-downloads 4
```

`pixi run preview` / `pixi run download` are pre-wired for the Delhi-NCR site,
Jan–Feb 2025.

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
- `--out` — output directory (default `~/bhoonidhi_downloads/`, or `$BHOONIDHI_OUT`)
- `--reauth` — discard the cached token and force a fresh password login

As a library:

```python
from bhoonidhi_cli import Session, search, with_details, downloads, summarize

sess = Session(user="...")          # logs in (or reuses the cached JWT)
items = with_details(sess, search(sess, args))   # args from cli.parse_args([...])
summarize(items)
results = downloads(sess, items, out_dir="/some/dir")
```

## Output

Per run, in `--out`:

- `search_results.json` — the full STAC item list returned by the search
- `manifest.json` — per-product download status, timestamps
- `<Collection>__<ItemID>.zip` — the product archives

## Development

```bash
pixi install
pixi run lint    # ruff check + format --check
pixi run test    # pytest
pixi run check   # lint + test
```

## License

[MIT](LICENSE) — the license applies to the code in this repository only. The
imagery you download is owned by ISRO/NRSC and governed by the
[Bhoonidhi EULA](https://bhoonidhi.nrsc.gov.in/bhoonidhi/htmls/TnC.html)
(credit the source with **ISRO-IRS**; open-data products may not be
redistributed commercially in their original form).
