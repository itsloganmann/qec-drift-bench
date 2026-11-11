# QEC-Drift workshop manuscript

Four pages of main text, one page of references, and three appendix pages (eight pages in one PDF). The main figures show the L1/L2/L3 failure hierarchy with raw trajectory-review counts and a verified quoted tool-action example. Written in the official ICML2026 preprint style. Authors: Logan Mann and Pranav Reddy. School-only affiliation: University of California, Santa Barbara. The PDF lists loganmann@ucsb.edu and preddy@ucsb.edu. This is a named circulation preprint, with no submission or acceptance claim.

The main-text count follows the checked workshop convention that references and appendices are excluded. Individual workshop limits and templates differ; see `WORKSHOP_FORMAT_RULES.md`.

## Files

- `QEC_Drift_Workshop_Paper.pdf`: final compiled manuscript.
- `paper.tex`, `appendix.tex`, `references.bib`: editable LaTeX source and verified paper citations.
- `figures/`: vector PDF figures: the MECE hierarchy/distribution, the quoted trajectory example, and supplementary diagnosis/family results. Generated PNG previews stay local.
- `make_figures.py`, `evidence/paper-aggregates.json`: reproducible anonymous figure inputs and plotting code.
- `vendor/icml2026.sty`, `vendor/icml2026.bst`, `.latexmkrc`: unmodified official style dependencies and local search-path configuration.
- `WORKSHOP_FORMAT_RULES.md`: current organizer sources and the revision decision.
- `LITERATURE_AND_NOVELTY_AUDIT.md`: search scope, source-by-source overlap and claim support.
- `evidence/reference-verification.json`, `arxiv-metadata.json`, `crossref-*.json`: reference checks.
- `evidence/model-pass-rates.json`: model pass percentages independently recomputed from scored episodes on identical tasks.
- `evidence/hierarchical-taxonomy.json`, `trajectory-example.json`: the regrouping of saved review labels and the verified observable excerpt.
- `evidence/CLAIM_SCOPE_AUDIT.md`: boundaries on generalization, independence and causal interpretation.

The source includes one verified, anonymous excerpt from a visible tool action and its explicit review annotation. Full raw trajectories, hidden labels, per-candidate result tables, local credentials, private task identities, and third-party paper PDFs are excluded. Public aggregate inputs can reproduce the paper figures, but do not enable complete independent replay of the private transcript audit.

## Build

Use a recent TeX Live distribution with pdfLaTeX, BibTeX and latexmk. The unmodified official ICML2026 `.sty` and `.bst` files are included in `vendor/`; `.latexmkrc` makes them discoverable. Keep this hidden configuration file when copying the source. It is included in the source archive. Standard packages include microtype, graphicx, booktabs, tabularx, amsmath, amssymb, xcolor, hyperref, enumitem, caption, balance and needspace. The upstream style loads its standard dependencies. Its hash and source URL are recorded in `evidence/format-and-author-provenance.json`.

All authored code remains below the repository's 600-line limit. The two unmodified upstream LaTeX style dependencies retain their original contents.

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build paper.tex
cp build/paper.pdf QEC_Drift_Workshop_Paper.pdf
```

The generated vector figures are included. To rebuild them with the pinned plotting version recorded in `evidence/final-validation.json`:

```sh
uv run --with matplotlib==3.11.2 --with numpy==2.5.4 python make_figures.py
```

The figure inputs record the public snapshot and source hashes. The hierarchy deterministically regroups the saved labels: it does not introduce new model calls or revise raw annotations. Review-coded passes (146/533) remain distinct from measured passes (144/533), and the four repair-floor contradictions remain disclosed. Metrics are descriptive, the development set is selected, and the full model grid remains incomplete. This manuscript adds no model runs or changes to historical scores.
