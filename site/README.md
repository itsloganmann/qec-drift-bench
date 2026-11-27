# Quantum Agent Bench site

The public site and leaderboard. Plain static files: no build step, no framework.

- `index.html`: the page. `app.js` wires it, `views.js` draws what an agent sees, `charts.js` draws the results, `chip*.js` draw the 3D chip
  (three.js 0.160.0 from jsDelivr, pinned in the import map).
- `data/results.json`: every number on the page. `data/instances.json`: the public instances the
  data viewer plots.
- `build_data.py`: rebuilds both data files from a mismatch-envs checkout.

## Preview

```
uv run python -m http.server 8000 --directory site
```

Then open http://localhost:8000. Opening `index.html` as a file does not work, because the page
fetches its data.

## Rebuild the data

```
uv run python site/build_data.py --envs ../mismatch-envs
```

Run it in the mismatch-envs environment (numpy, scipy, stim, pymatching). It reads the scored
results that the benchmark already wrote and does not run any agent. Commit both JSON files.

## Deploy

Cloudflare Pages uses Direct Upload. Deploy the static files in `site/` to the existing project
after testing the merged commit. No build command is needed.

## Rules for this folder

- Read benchmark results from the generated data.
- Never show, plot or name a task's unlisted change. The data viewer only gets instances whose
  change fits the task's own model, as agents do.
- Keep the canary string in `index.html` and in every task file.
- Keep source files under 600 lines (AGENTS.md rule 7). Generated data is exempt.
