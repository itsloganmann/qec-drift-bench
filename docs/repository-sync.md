# Repository syncing

`itsloganmann/qec-drift-bench` is the canonical repository and the only publication target. An hourly Codex check publishes ready local changes while this laptop and Codex are available. The former private repository is no longer synchronized. Pranav's fork is compared but never modified.

The running study keeps its existing local research checkout and raw evidence. Its Git history stays local, and private-remote pushes are disabled. Publish only the curated public tree; never push the research checkout's history to the public repository.

## Before each push

1. Read the current continuation checkpoint and repository rules. Inspect every changed path. Commit only ready, reviewed source, tests, documentation, and anonymous aggregate evidence to the local research checkout. These source commits do not require a private remote push. Run the tests affected by code changes. Never use a blanket add in the research checkout.
2. Check the public head and local source head against `.cache/repository-sync/receipt.json`. Preserve public contributions. Use a normal fast-forward public push. If histories diverge or an unfamiliar public commit appears, preserve the work and report the conflict. Never force push or replace a collaborator's changes. Do not fetch, commit to, or push the former private repository as part of synchronization.
3. Inspect the exact public diff before pushing. Exclude raw trajectories, scorer fixtures, task identities, local paths, credentials, usage telemetry, reference-build logs, caches, and temporary drafts. Run the existing history secret scanner and require zero hits. Prepare snapshots with `scripts/publish_snapshot.sh --no-push`. Verify that the generated commit has the expected public head as its parent, then inspect its exact diff before a separate normal push. The script replaces its destination tree, so never let a scheduled invocation push automatically.
4. Push only from the prepared public checkout to `itsloganmann/qec-drift-bench`. Verify its GitHub commit hash. Record the public hash, local source commit, changed paths, checks, and time in the local receipt. Unchanged files require no commit.

## Study and paper

The existing schedule is finite: 23 supported configurations on the same 85 eligible tasks, totaling 1,955 Codex evaluations. Syncing does not authorize new experiments, changed scoring, extra attempts, or restarted launchers.

Refresh `data/audits/codex-replication-progress.json` only from matching completed trajectory and execution audits. Keep progress separate from final performance results. Preserve historical scores and interrupted attempts. Capture all emitted trajectory events and check contiguous coverage for each L1/L2/L3 review.

The revised paper remains a draft until all 1,955 evaluations finish and the release checks pass. Read the latest prepared-paper manifest in the continuation checkpoint. Regenerate the final table, aggregate figures, LaTeX macros, PDF, and artifact hashes together. Verify four main pages, citations, extracted text, layout, and the public diff. Never overwrite the published paper with a partial-results draft.

Raw evidence, in-progress drafts, and changing telemetry remain local. Their presence is expected and does not justify an automatic commit. Close any tabs or windows opened for a sync after verification.
