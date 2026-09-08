# Local frontend

From the repository root:

```bash
uv run python tools/dev.py
```

Open **http://localhost:5173**. Saved HTML, CSS, JavaScript, and generated data
changes reload the browser automatically. There is no frontend build or npm
install. Stop the server with Ctrl+C. Use `--port 5174` for a different port.

Startup validates and loads the checked-in extracts from `site/data/`: all
contributions classified as `ENTITY`, and eCheckbook lines for vendor
`AUS6036990` with the exact name `AUSTIN BOARD OF REALTORS`. The content manifest
pins the files by checksum. Validation checks their source lineage, selected
fields, row coverage, dates, amounts, and privacy scanner results. A fresh clone
can run the preview without raw City downloads or network access.

Use `--rebuild-data` only to regenerate local extracts from the original frozen
raw snapshots. That operation also verifies the raw source checksums.

The ignored `frontend/_data/` directory contains only the selected fields. The
server binds to `127.0.0.1` and serves only `frontend/`, with directory listing and
external symlinks disabled. It does not serve the repository or raw source files.
No deployment or CI changes are required. In WSL, Windows browsers can normally
use the same localhost URL through Windows localhost forwarding.

The frontend is vanilla HTML, CSS, and JavaScript. `app.js` renders the record
browser, source directory, and methodology page. `data.js` contains filtering,
sorting, CSV serialization, and official record links. Search and filters are
stored in the URL, so refreshing after an edit preserves the current view.

Regenerating data requires the local raw CSV and metadata snapshots referenced by
`reports/profiles/`, plus the existing metadata acquisition manifests. These are
present in the original development checkout. Restore those same frozen
artifacts to their original locations before regenerating; the frontend does
not silently replace a frozen snapshot with a new City download.

`mor-l0 build-site` uses the same frontend and validated publications to create
the deployable site. It fingerprints CSS, JavaScript, and the icon, and removes
the local reload script. The existing Terraform workflow deploys that archive
to UAT after merge. Scheduled refreshes remain tracked in issues #28 and #30.

Frontend logic checks use Node's built-in runner:

```bash
node --test tests/frontend.test.mjs
```
