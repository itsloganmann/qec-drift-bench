# The failure taxonomy: one label for every episode

Every episode of every arm, on every scaffold (the API harness, Claude Code, Codex), gets
exactly one label from the tree below. The labels are mutually exclusive and, together,
exhaustive: `tests/test_taxonomy.py` runs every combination of the tree's inputs and checks
that each lands in exactly one label and that every label is reachable.

- Code: `scoring/taxonomy.py` (the tree, the transcript features, the legitimacy flags).
- Run: `scripts/legitimacy.py` labels every arm, writes `data/<set>/<arm>_taxonomy.parquet`,
  and regenerates `docs/legitimacy.md`.
- Second opinion: `scripts/judge_transcripts.py` assigns the same labels without seeing the
  rule label. Protocol `identifier-masked-v2` masks known model identifiers and arm paths
  throughout its input while retaining path relationships. Scaffold and tool syntax remain
  clues; this is not complete blinding. Its cache hashes the exact input, rubric, schema and
  judge settings, keyed by arm and task. Earlier judgments remain archived and excluded.
  `docs/judge.md` separates valid rows, available transcripts, current reviews and gaps.
  The hourly publisher evaluates at most eight pending episodes per tick.
- Transcripts: `trajectories/<set>/<arm>/<task>.md`, one page per episode, with the score.

New runs store the same `attempt_id` in the score and its archived transcript. The archive
record is flushed to disk before the score table is replaced atomically. Archives keep prior
attempts. Readers use one score snapshot and match transcripts and derived labels by attempt;
an uncommitted rerun cannot replace the evidence for a committed score. Missing matches are
reported, and stale labels wait for regeneration. This protects process-crash recovery with
one writer per arm; it does not coordinate concurrent writers.

Historical rows without IDs use the last untagged transcript for the task. Older ambiguous
reruns remain ambiguous. Rows without stored source or size metadata
retain the old work-folder fallback; an explicit zero-byte decoder never uses that fallback.
The legacy rescoring scripts refuse rows with IDs, since they cannot preserve this linkage.

## The tree

An episode takes the first gate that applies.

| gate | question | label |
| --- | --- | --- |
| G0 | Did an external failure invalidate the episode? It never ran, it was killed before the agent acted, a provider limit interrupted it, the login was lost, or the environment lacked what the task text promises (a missing stim or pymatching). | `invalid_run` |
| G1 | Did it pass the relative rule: diagnosis right, and the decoder good enough? | `passed` |
| G2 | No scorable decoder, and the episode ended at the 40-tool-call budget or the time limit? | `out_of_budget` |
| G3 | No `decoder.py`, and the agent stopped on its own? | `no_submission` |
| G4 | `decoder.py` exists but did not score (a crash, a timeout, a wrong shape)? | `broken_decoder` |
| G5 | Scored worse than plain matching on the nominal model (`gap_closed` below 0)? | `harmful_decoder` |
| G6 | The decoder was good enough, but the report named the wrong fault? | `misdiagnosis` |
| G7 | The decoder is the nominal model's decoder: the data never reached it? | `nominal_unchanged` |
| G8 | A model fitted to the data, decoded without the correlations? | `plain_matching` |
| G9 | A fitted, correlated decoder that recovered too little of the loss? | `under_adapted` |

`invalid_run` episodes are set aside and rerun; they never count toward a score. G1 to G9
are the scored outcomes: G1 is a pass, G2 to G5 mean no usable decoder, G6 is a wrong
diagnosis on a good decoder, G7 to G9 are a decoder that fell short, named by what it carries.
Whether the diagnosis was also wrong on a G7 to G9 episode is the attribute
`diagnosis_wrong`, not a label.

## The inputs of the tree

- **The decoder leaf** (`scoring/failure_modes_decoder.py`): what the episode shipped. Behaviour
  first: a decoder whose test predictions agree with plain or correlated nominal matching on
  99.99% of the shots is that decoder (nominal); anything else is fitted, and correlated when
  `enable_correlations` is in its source. Rows from before the harness recorded agreement fall
  back to reading the source (an inlined model with other probabilities, a model built from
  computed text, a rewrite of the noise lines, a module or data file of its own).
- **The verdict under the relative rule** (`agent/awareness.py` and the same file): the
  diagnosis (scope right, the stationary flag right, at least half the changed qubits named)
  and the fix (half the plain gap closed, half the drift loss recovered, and at least 0.75 of
  what the honest baseline recovers on that task: the adaptive decoder for a moving fault, the
  pairwise refit for a stationary one).
- **Two run facts from the transcript**: whether the agent acted at all, and whether the
  episode ended at the budget (the harness note "tool-call limit" or "time limit").

## Legitimacy flags: attributes, not labels

Each episode also carries flags that a reader checks; they never change the label.

- `harness`: what put an episode in G0 (`never_acted`, `env_missing`, `login_lost`,
  `provider_limit`, `error_row`). A provider limit invalidates a partial attempt even after
  tool calls or a decoder file; it is archived without scoring and queued for a fresh run.
- `integrity`: the agent reached for something outside the task: `denied` (the sandbox refused
  a path), `network` (an install or a URL), `outside` (a path outside its task folder and the
  venv), `probe` (names of the hidden test, the harness or the references), `own_copy` (it
  installed its own stim, pymatching or numpy), `name_seen` (its own task name is in the transcript; a
  task name says what is wrong, so this must never happen).
- `anomalies`: `beats_oracle` (drift recovery above 1.15: better than per-shot correlated
  matching with the true model, possible with a better decoder, worth reading), `no_report`,
  `over_budget_row`.

## Before this tree

Until 2026-11-03 each episode had two labels: the decoder leaf and a verdict (passed,
missed_diagnosis, missed_fix, missed_both, no_score). The tree above replaces the pair with
one label; both stay in the taxonomy table as the tree's inputs. The paper-era taxonomy of
single responses is in `docs/archive/failure-taxonomy-responses.md`.
