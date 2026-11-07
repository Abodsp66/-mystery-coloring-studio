# Mystery Coloring Studio — Codex Instructions

## Current application: independent Flow Studio

The user explicitly requested a fresh implementation after rejecting the V6
mosaic-like output. The current application is `flow-studio/`, with its own
JavaScript modules and module worker; it must not import the legacy Python/JS
coloring engine. Use `sh scripts/serve-flow.sh` (port 8765) for the current app.
Read `docs/FLOW_STUDIO_AR.md`. Run `sh scripts/check-flow.sh`,
`node --test --test-isolation=none tests/flow_engine.test.mjs`, and the real
`tests/flow_browser.py` against the running current app after engine changes.
The browser test blocks off-site requests and checks actual vector label fit.
Do not publish copyrighted PDF images; use the original project fixtures.
Preserve `dist/`, the original ZIP, reference SVG and PDFs as legacy/reference
material. The instructions below describe that preserved original application.

This repository contains an Arabic RTL browser-based mystery color-by-number web application. The uploaded file `Mystery-Coloring-Studio-V5.2.1-Local-Launch.zip` is the ORIGINAL source bundle. **Before changing code, unpack the archive into the repository root and commit the extracted files.** Do not delete the original zip until the extracted source has been verified.

Expected structure after extraction:
- `dist/index.html`, `dist/style.css`, `dist/app.js`: website UI.
- `dist/worker.js`: Web Worker running Pyodide.
- `dist/v5-core.py`, `dist/pipeline.py`, `dist/engine.js`: coloring engine.
- `dist/reference.svg`: original reference graphic; preserve it.
- `README_AR.md`, `server-local.ps1`, `RUN-WINDOWS.cmd`: original documentation/Windows launcher.

Goal: preserve the existing application's behavior and graphics while making it run reliably in a Codex cloud environment and enabling further iteration of smooth, numbered, printable A4/A3 mystery-coloring sheets. Do not replace the application with a mockup.

To preview, run:
```sh
python3 -m http.server 8765 --bind 0.0.0.0 --directory dist
```
Use the web preview forwarded port 8765. Do not open `dist/index.html` via `file://` because Web Workers require HTTP(S).

Validate Python syntax via `python3 -m py_compile dist/v5-core.py dist/pipeline.py` and JS via `node --check dist/app.js && node --check dist/worker.js && node --check dist/engine.js`.
Full conversion requires browser access and a network connection to the Pyodide/NumPy/SciPy/Shapely dependencies CDN. Test image upload, conversion, SVG download and print workflow in a real browser where possible. Report any tests that could not run.

No secrets should be committed. Do not push changes to any other repository.
