# Quantum Agent Bench site

The public site and leaderboard. Plain static files: no build step, no framework.

- `index.html`: the page. `app.js` wires it, `views.js` draws what an agent sees, `charts.js` draws the results, `chip*.js` draw the 3D chip
  (three.js 0.160.0 from jsDelivr, pinned in the import map).
- `data/results.json`: every number on the page. `data/instances.json`: the public instances the
  data viewer plots.
- `build_data.py`: rebuilds both data files from a mismatch-envs checkout.

## Preview

```
cd site && python -m http.server 8000
```

Then open http://localhost:8000. Opening `index.html` as a file does not work, because the page
fetches its data.

## Rebuild the data

```
python site/build_data.py --envs ../mismatch-envs
```

Run it in the mismatch-envs environment (numpy, scipy, stim, pymatching). It reads the scored
results that the benchmark already wrote and does not run any agent. Commit both JSON files.

## Deploy

Cloudflare Pages: set the build command to none and the output directory to `site`. Any static
host works the same way.

## Rules for this folder

- Every number comes from `build_data.py`. Do not type a result into the page.
- Never show, plot or name a task's unlisted change. The data viewer only gets instances whose
  change fits the task's own model, as agents do.
- Keep the canary string in `index.html` and in every task file.
- Keep each file under 600 lines (AGENTS.md rule 7).
