# Automata

Automata is a local-first browser macro studio. Describe a task in plain English, review the schema-validated plan, run it in an isolated visible Chromium context, inspect live progress and screenshots, then save the successful workflow for deterministic reuse.

The first version is deliberately small: FastAPI + SQLite on the backend, Playwright for browser actions, and a React/Vite dashboard. There is no queue, worker service, cloud database, or remote browser requirement.

## What works

- Plain-English planning through an OpenAI-compatible `/chat/completions` adapter.
- A deterministic built-in planner for the included local catalog demo when no API key is configured.
- Versioned macro validation with structural parameter references such as `{{search_term}}`.
- Real Playwright Chromium execution with role, label, test-id, text, placeholder, and CSS locators.
- Navigate, click, fill, clear, select, check/uncheck, press, wait/assert, read, record extraction, bounded pagination, new tabs, screenshots, downloads, and CSV/JSON export.
- Live server-sent events, pause/resume/stop, one active run at a time, cancellation checks, screenshots, logs, and failure diagnostics.
- Optional bounded AI-assisted repair with a two-attempt default and repair records.
- SQLite persistence for macros, settings, runs, and run events; active runs are marked failed with recovery guidance after a restart.
- Macro library search, duplicate/edit/delete, JSON export, readable Python Playwright export, and run history.
- A local demo site at `/demo/catalog` with search, pagination, product cards, and a downloadable CSV.
- Manual visible browser sessions that can be explicitly saved and removed.

## Quick start on Windows PowerShell

From the repository root:

```powershell
.\scripts\start.ps1 -Install -InstallBrowsers
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The backend listens on `http://127.0.0.1:8000`.

For subsequent starts, when dependencies are already installed:

```powershell
.\scripts\start.ps1
```

To run the backend alone:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

To run the frontend alone:

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1
```

The visible browser is launched by default. Set `AUTOMATA_BROWSER_HEADLESS=true` for CI or unattended tests.

## Model setup

Copy `.env.example` to `.env`, or set the variables in the PowerShell process before starting:

```powershell
$env:AUTOMATA_MODEL_ENDPOINT = 'https://api.openai.com/v1'
$env:AUTOMATA_MODEL_NAME = 'gpt-4o-mini'
$env:AUTOMATA_MODEL_API_KEY = 'your-key'
```

The Settings screen can also save an endpoint, model, timeout, capability flags, and a backend-only key into the local SQLite store. Keys are never returned to the frontend, placed in exports, or written to execution logs. For a local compatible server, set the endpoint to its `/v1` base URL and leave the key blank.

Without a key, planning still works for the included catalog demo through the deterministic fallback. The dashboard labels that plan as a fallback. Model connection testing is only verified when a reachable compatible endpoint and credentials are supplied.

## Demo workflow

1. Open the dashboard and choose **Task composer**.
2. Keep the prefilled demo URL and example instruction, or use `/demo/catalog` directly.
3. Set variables such as `{"search_term":"desk","max_pages":2}`.
4. Generate the editable plan.
5. Save it, then run it. The browser window, activity feed, screenshot, extracted table, and CSV artifact update as the run progresses.
6. Open **Macro library** to run the saved macro with new inputs without another planning call, or download JSON/Python exports.

## Tests

Install dependencies and Chromium first, then run:

```powershell
pytest -q
Set-Location frontend
npm run build
```

The test suite covers schema validation, structural variable resolution, cancellation, failure diagnostics, and an end-to-end run against the local FastAPI demo website using a real Playwright browser. The end-to-end test uses headless Chromium so it is repeatable; normal application runs remain visible by default.

## Project layout

```text
backend/
  browser.py          deterministic Playwright runner and lifecycle controls
  demo_site.py        local catalog demo site
  exports.py          JSON and readable Python exports
  main.py             FastAPI API, SSE, sessions, and artifact routes
  model_adapter.py    hosted/local OpenAI-compatible adapter
  planner.py          model planner plus deterministic demo fallback
  schemas.py          versioned macro/run contracts
  storage.py, db.py   SQLite persistence
frontend/
  src/App.tsx         dashboard views and live run UI
  src/styles.css      dashboard styling
examples/             importable example macro
scripts/start.ps1     one-command Windows startup
```

## Troubleshooting

- `Executable doesn't exist`: run `python -m playwright install chromium`.
- The dashboard says the model is not configured: set `AUTOMATA_MODEL_API_KEY` or save a key in Settings. The demo fallback remains available.
- A run says a locator is ambiguous: edit the step to use a more specific role/name, label, test id, or CSS selector.
- A saved session is not available: open it from Settings, sign in manually in the visible browser, then click **Save current session**.
- If the app restarts during a run, the run is marked failed with an interrupted-run message. Start it again after checking the last recorded step.

## Known limitations

- One active browser run is supported initially.
- The first version pauses between actions; it does not embed an interactive browser in the dashboard.
- CAPTCHA, MFA, and other access challenges require manual handling in the visible browser.
- Frame-specific authoring, complex conditional branching, arbitrary JavaScript, and unrestricted expressions are intentionally not supported.
- Saved API keys are stored in the local SQLite file for this first version; protect the data directory on shared machines and prefer environment variables for higher-sensitivity deployments.

