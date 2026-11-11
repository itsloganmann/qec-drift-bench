# QEC-Drift workshop manuscript

Five pages total, including the references. Written in LaTeX in a neutral two-column workshop format. The document does not claim affiliation with, submission to, or acceptance at a conference.

## Files

- `QEC_Drift_Workshop_Paper.pdf`: final compiled manuscript.
- `paper.tex`, `references.bib`: editable LaTeX source and verified paper citations.
- `figures/`: vector PDF figures and PNG counterparts.
- `make_figures.py`, `evidence/paper-aggregates.json`: reproducible anonymous figure inputs and plotting code.
- `LITERATURE_AND_NOVELTY_AUDIT.md`: search scope, source-by-source overlap and claim support.
- `evidence/reference-verification.json`, `arxiv-metadata.json`, `crossref-*.json`: reference checks.
- `evidence/CLAIM_SCOPE_AUDIT.md`: boundaries on generalization, independence and causal interpretation.

No raw trajectories, hidden labels, per-candidate results, local credentials, private task identities, or third-party paper PDFs are included in the distributable bundle. Public aggregate inputs can reproduce the paper figures, but do not enable complete independent replay of the private transcript audit.

## Build

Use a recent TeX Live distribution with pdfLaTeX, BibTeX and latexmk. The source uses standard packages, including newtx, microtype, geometry, natbib, booktabs, tabularx, caption, fancyhdr, titlesec, balance and needspace.

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build paper.tex
cp build/paper.pdf QEC_Drift_Workshop_Paper.pdf
```

The generated vector figures are included. To rebuild them with the pinned plotting version recorded in `evidence/final-validation.json`:

```sh
uv run --with matplotlib==3.11.2 --with numpy==2.5.4 python make_figures.py
```

The figure inputs record the public snapshot and source hashes. Metrics are descriptive, the development set is selected, and the full model grid remains incomplete. This manuscript adds no model runs or changes to historical scores.
