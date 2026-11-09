# Development audit and visible baseline, November 9, 2026

The fixed visible-only baseline passed 4 of 23 selected development tasks under both
joint pass rules. Recomputing all reference rates changed none of the 533 historical
model pass decisions. Strict numerical reference parity failed. These are separate
results; unchanged decisions do not establish exact reproducibility.

The tasks were selected during earlier development. This is not a held-out evaluation.
The already frozen 92-candidate fresh-seed study is a separate within-family replication;
its incomplete results are not included here.

## Predictions and observed results

Before the baseline run, the [frozen method note](visible-baseline.md) predicted few
adequacy false positives on adequate IID cases, better time-order detection for sustained
switching than IID mixtures, localization over-reporting, and possible scoring timeouts
on larger circuits. No minimum pass count was assumed.

Adequacy was correct on 23/23 tasks, including the two adequate tasks. Stationarity was
correct on 22/23. Full diagnosis was correct on only 6/23. The stationary bad-qubit task
was falsely called nonstationary. Localized errors were often over-reported, and many
moving faults were called global. Four d=7 decoders exceeded the fixed 300-second scoring
deadline; two of those had correct diagnoses. No fit exceeded its 3600-second limit.
Nineteen decoders returned scored outputs. All four timeouts count as failures.

The four joint passes were `d5-none-s6`, `d9-none`, `d5-none-dmeas5`, and
`d5-none-dwander30-s5-n2000`. The full baseline uses visible inputs for diagnosis as well
as decoding. Earlier localization-only diagnostics that supplied true scope are not
equivalent baselines. Neither the parameters nor the deadlines were tuned after this run.

## Reference parity and score sensitivity

Every comparison used 300,000 hidden shots and the predeclared absolute tolerance 1e-12.

| Reference group | Rates | Matches at 1e-12 | Matches at five decimal places |
|---|---:|---:|---:|
| Nominal and pairwise refit | 92 | 68 | 92 |
| Oracle and stale | 67 | 45 | 67 |
| Window | 19 | 13 | 19 |
| Adaptive | 19 | 14 | 19 |
| Total | 197 | 140 | 197 |

The 57 nonmatching rates each differed by one error in 300,000 shots. They agree after
rounding to five decimal places. The original cache conversion path is unverified;
rounding agreement does not turn the strict check into a pass.

The sensitivity audit first reconstructed all 533 original decisions with zero
mismatches. It then substituted the recomputed references while keeping each model's
error rate and diagnosis fixed. Absolute passes stayed at 159 and relative passes at
144, with zero verdict changes. The largest error-rate threshold shift was about
0.0000033333 under either rule. Historical caches and score tables were not edited.

## Diagnosis contract

The 533 model rows contain 478 submitted reports and 55 missing reports. Parsed defaults
are not actual answers. Of 57 parsed adequacy errors, 3 came from submitted reports and
54 from missing-report defaults. Of 185 parsed mechanism errors, 130 came from submitted
reports and 55 from defaults. Eight absolute passes and six relative passes have wrong
mechanism answers because mechanism is reported separately and is not part of the joint
pass gate. These counts do not change the scoring contract.

## Evidence and remaining work

[Machine-readable results](../data/audits/development-closeout-20261109.json) contain all
23 baseline rows, audit totals, and input hashes. The baseline method and original runner
are at commit `58091afb2bfd1e4afcc66ebdd136953d646bbcec`. Its recorded runner hash, frozen
source files, fixture manifest, every fixture file, and all 23 identities were checked
before this report. The reported baseline pass decisions were independently reconstructed
from the saved diagnosis and decoding metrics.

The subsequent runner fix preserves diagnosis and decoding observations when a fresh
candidate has undefined references. Its joint scores are null, including on execution
failure. Such cases remain visible in the candidate inventory and are not eligible model
episodes. Defined but degenerate gaps retain the existing failure rule. This does not
alter the completed development results or the frozen baseline method.

Transcript reviews, the frozen fresh-seed study, missing original grid entries, and the
Kaggle port remain in the finite completion backlog. Hosted Kaggle isolation and resource
limits are still unverified. No scored Kaggle result is claimed.
