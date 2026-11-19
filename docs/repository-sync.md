# Repository syncing

An hourly Codex check syncs finished local changes to `itsloganmann/qec-drift` and refreshes the public `itsloganmann/qec-drift-bench` snapshot. It runs on this laptop while Codex is available. Pranav's fork is compared but never modified.

## Before each push

1. Read the current continuation checkpoint and repository rules. Inspect every changed path. Commit only ready, reviewed source, tests, documentation, and anonymous aggregate evidence. Run the tests affected by code changes. Never use a blanket add in the research checkout.
2. Fetch both repositories. Compare their current heads with `.cache/repository-sync/receipt.json`. Preserve remote contributions. Use a normal fast-forward push. If histories diverge or an unfamiliar public commit appears, preserve the work and report the conflict. Never force push or replace a collaborator's changes.
3. Inspect the exact public diff before pushing. Exclude raw trajectories, scorer fixtures, task identities, local paths, credentials, usage telemetry, reference-build logs, caches, and temporary drafts. Run the existing history secret scanner and require zero hits. Prepare snapshots with `scripts/publish_snapshot.sh --no-push`. Verify that the generated commit has the expected public head as its parent, then inspect its exact diff before a separate normal push. The script replaces its destination tree, so never let a scheduled invocation push automatically.
4. Verify the pushed private and public commit hashes against GitHub. Record both hashes, the source commit, changed paths, checks, and time in the local receipt. Unchanged files require no commit.

## Study and paper

The existing schedule is finite: 23 supported configurations on the same 85 eligible tasks, totaling 1,955 Codex evaluations. Syncing does not authorize new experiments, changed scoring, extra attempts, or restarted launchers.

Refresh `data/audits/codex-replication-progress.json` only from matching completed trajectory and execution audits. Keep progress separate from final performance results. Preserve historical scores and interrupted attempts. Capture all emitted trajectory events and check contiguous coverage for each L1/L2/L3 review.

The revised paper remains a draft until all 1,955 evaluations finish and the release checks pass. Read the latest prepared-paper manifest in the continuation checkpoint. Regenerate the final table, aggregate figures, LaTeX macros, PDF, and artifact hashes together. Verify four main pages, citations, extracted text, layout, and the public diff. Never overwrite the published paper with a partial-results draft.

Raw evidence, in-progress drafts, and changing telemetry remain local. Their presence is expected and does not justify an automatic commit. Close any tabs or windows opened for a sync after verification.
