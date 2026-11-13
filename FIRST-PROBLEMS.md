# First problems

Three real gaps, not exercises. Each comes from ADR-0059 (condition monitoring, built-in test and usage) and the design that specifies its remaining-life kind, `DESIGN-2026-11-11-remaining-life-output-kind.md`. Both are in openddil-contracts under `decisions/`, on branch `docs/rul-output-kind-spec`, which is open as a draft pull request and not yet on `main`. Read ADR-0059 §4 and the design before you start: they say what each piece must be, and what it must not claim.

Each problem lists:
- its inputs;
- the test that says it is done;
- the files it touches, public and overlay;
- what it waits on.

"Public" means openddil-tactical-agents, through a pull request. "Overlay" means your private overlay (`tools/init-overlay.sh`).

**Where to branch from.** openddil-tactical-agents branch `algorithms-ports`, open as a draft pull request: the runtime, the replay harness and the ported units are there, not yet on `master`. Problem 1 starts from branch `rul-scoring`, which sits on top of it. Once they merge, merge `master` into your branch. Never rebase a branch you've pushed: someone may already have built on it, and a rebase rewrites what they built on.

**Start with problem 1, the scoring metrics.** It needs nothing that isn't already here. Problem 2 needs a kind to be accepted. Problem 3 needs data that is being recorded now.

---

## 1. The PHM metrics in the scoring harness

**The gap (ADR-0059 §4.3, design §5).** The scoring harness joins remaining-life outputs to confirmed failures, but its five metrics are named stubs that raise `NotImplementedError`. They are in `scoring/rul.py`: `prognostic_horizon`, `alpha_lambda_performance`, `relative_accuracy`, `cumulative_relative_accuracy` and `convergence`.

The ADR and the design assert no definition of their own. Each metric is implemented from the text of Saxena, Celaya, Saha, Saha and Goebel, "Metrics for Offline Evaluation of Prognostic Performance", IJPHM 2010, and cites the section it implements.

**Scope.**
- **The five metrics, from the paper.** Predictions are quantile sets, not points. Where the paper defines a form over a prediction's distribution as well as a point form, implement both and say which one a report uses.
- **Declare the paper's parameters per run.** That means α, β, the λ points, and any weights. They go in a run-declaration file (design §5.1), never as constants in the code.
- **Group scores by producer stamp** (unit, version, configuration hash), so two versions are never averaged together (design §5.2).
- **Report placeholders.** A report says when the scored unit's parameters are placeholders (design §5.3).
- **Use the declared meter kinds in the synthetic generators.** They default to an `operating_time`/`h` meter, which isn't one of ADR-0051's three. Switch them to the declared kinds.

**Inputs.** Synthetic failures and predictions: `synth_failures` and `synth_predictions` in `scoring/rul.py`. Real ones don't exist yet. No confirmed failure outcome returns to OpenDDIL today (ADR-0059 finding 9), and the field names in `rul.py` are provisional until the remaining-life kind is built.

**Acceptance test.**
- Every metric has hand-worked cases, small enough that a test's docstring shows the arithmetic, each citing the paper's section.
- Properties that must hold:
  - A perfect predictor has relative accuracy 1 and passes α-λ at every λ. Its prognostic horizon is the whole span.
  - A constant relative bias gives the relative accuracy that bias implies.
  - A predictor that converges scores better on convergence than one that doesn't.
- Censored predictions, and failures that are not `confirmed`, enter no metric.
- Two producer stamps are never averaged.
- The existing 20 tests still pass, except the stub tests, which the real metrics replace.

**Files.**
- Public: openddil-tactical-agents branch `rul-scoring`:
  - `scoring/rul.py`;
  - `scoring/README.md`;
  - `tests/test_rul_scoring.py`;
  - a new example run declaration, for example `scoring/examples/run.yaml`.
- Overlay: none for the build. A program's own predictions and confirmed failures are private. Score them in the overlay (a new `scoring/` path), and never commit them to public.

**Waits on.** Nothing for the metrics. Real scores wait on confirmed failure outcomes (ADR-0059 §4.4) and on a unit that isn't a placeholder (problem 2).

---

## 2. The wear unit's remaining life, as a distribution in a declared usage meter

**The gap (ADR-0059 finding 7).** The wear unit reports remaining useful life as a percentage of an authored life (`algorithms/wear/wear.py:21`, `_percent_remaining`), against life totals that are placeholders (`algorithms/wear/unit.yaml`, the `*_life_total_*` params). ISO 13381-1 defines remaining useful life as the use remaining before a defined failure threshold, not a percentage.

The design (§1-§2) requires each remaining-life output to:
- be stated in a declared usage meter's unit;
- be a distribution with a declared form, never a point alone;
- carry a declared horizon and a failure-threshold reference;
- be marked advisory.

**Scope.**
- **A new unit beside `wear`.** The wear unit's `%` output stays as it is: the design leaves it a sustainment output.
- **Barrel only, on `count:rounds`.** Only three meter kinds are declared today: `count:rounds`, `count:moves` and `duration:emitting` (ADR-0051 §3). Barrel life in rounds is the one wear component that maps onto one.
- **Track, engine and suspension stay out.** Track is in km, engine in h and suspension in deg.km, and none of these is a declared meter (ADR-0059 finding 6). Write down which meter each would need. That is a request to ADR-0051, not a choice a unit makes.
- **The distribution comes from a stated life model.** Use a parametric life distribution for the barrel, with its parameters in `params` (type, range, unit, and marked as placeholders), and the remaining rounds conditional on survival to the current reading. A Weibull is one choice. Emit it in the declared form, for example a declared quantile set.
- **No made-up spread.** A unit that can only produce a point keeps a sustainment output (design §2).
- **Leave confidence absent** unless you declare its kind (design §3).
- **Past the horizon, say so.** The output states that the remaining use exceeds the horizon, not a number beyond it.

**Inputs.**
- A count of rounds fired, per asset. Nothing feeds it today: `record_round_fired` has no caller (`wear.py`, the Fire input is not wired), and the recording in `data/` has no Fire input.
- The tests therefore drive the unit with a synthetic rounds stream.
- A replay over `data/` must show the barrel as absent, not as zero.

**Acceptance test.**
- The unit's quantiles match the closed-form conditional quantiles of the declared distribution, to a declared tolerance, at several readings, including 0 and readings past the scale.
- Readings past the horizon produce the censored statement, not a number.
- The declaration loads. The validator refuses each of the design §4 cases:
  - no meter kind, no distribution form, no horizon or no threshold reference;
  - a confidence kind that isn't one of ADR-0020's;
  - a payload that sets advisory to false.
- Replaying the same synthetic stream twice gives byte-identical outputs.
- The scoring harness from problem 1 reads the unit's outputs without a refused record.

**Files.**
- Public, the runtime (one PR):
  - `edge/algorithm_runtime/declaration.py` (`OUTPUT_KINDS` and the refusals);
  - `edge/algorithm_runtime/outputs.py` (the builder);
  - `algorithms/declaration.schema.json`;
  - `edge/algorithm_runtime/contract.py`, for a rounds role, if reviewers agree it belongs in the vocabulary;
  - their tests.
- Public, the unit (a second PR): `algorithms/<unit>/unit.yaml`, `algorithms/<unit>/<unit>.py`, `tests/test_<unit>.py`.
- Overlay: a program's own fitted life parameters go only in its own copy of the unit under `algorithms/<unit>/`. Never in public.

**Waits on.** The design's acceptance, and the ADR-0057 amendment it drafts. Until then the runtime refuses any kind other than the ones in `OUTPUT_KINDS`. The kind's token (`remaining_life` is proposed) and its field names are bound when it is built, so use the design's concepts and expect to rename.

---

## 3. Thermal's thresholds, calibrated against the recording

**The gap.** The thermal unit's thresholds are the original rule's numbers (`algorithms/thermal/unit.yaml`):
- `delta_threshold_k` 80;
- `rate_threshold_k_per_sample` 2.0;
- `ewma_alpha` 0.2.

They have never been set against a measured temperature: the unit's `measured.basis` is `recorded-timing-synthetic-values`. ADR-0059 places the thermal unit in its state-detection row. Nothing in the record measures its thresholds.

**What the recording actually holds. Read this first.**
- **No temperatures in `data/`.** `raw-sensor-stream` carries no temperature at all (`DATA.md`). The thermal unit reads `component_temp_k` and `ambient_temp_k` from that topic, so on this data it never steps.
- **The only recorded temperatures are on the element topic** (`asset-element-telemetry`). Each envelope carries a `temp_c` per element and, in `operational`, a `core_temp_c`.
- **No ambient temperature is recorded anywhere.** The delta threshold can't be calibrated from this recording. Say so in the result, and leave that parameter unchanged.
- **The element topic is compacted.** Each pull keeps only the last few minutes, about 20% of the time. Successive records are not successive samples, so rates must be per second across the real gap, not per record.
- **The system is simulated.** Calibrating against it calibrates against the simulator's temperature model. The deliverable is the method, plus parameters with a stated basis, not fielded values.

**Scope.**
- A reproducible calibration script that reads the element topic's recorded files and builds a temperature series per element, from `observed_at_ns`. The runtime roles for reading envelopes (`element_values`, `observed_at_ns`) are on the openddil-tactical-agents branch `algorithms-ports`. This kit's `harness/` predates them.
- Characterise the distribution of temperatures and of rates per element.
- Choose a rate threshold for a declared false-alarm budget. The recording has no known runaway, so every alert on it is false.
- Measure detection on injected synthetic runaways, declared as synthetic.
- The rate parameter is per sample, which doesn't carry across inputs with different rates. If you propose a per-second parameter instead, that is a declared change (new version, new configuration hash) for review, not part of this calibration.
- Making thermal read the element topic is a separate design question. Raise it; don't do it here.

**Inputs.** The element topic from the recording that starts after the next system build settles, which includes that topic. It is added to `data/` when exported. Until then, write and test the script against synthetic envelopes in the same shape.

**Acceptance test.**
- The script's tests pass on synthetic envelopes:
  - known rates come back exactly;
  - a gap between records is divided out, not ignored;
  - an injected runaway is found.
- Run twice on the same export, the script writes a byte-identical report.
- The report, per edge, gives:
  - records, elements, assets and the time covered;
  - the rate quantiles;
  - the chosen threshold and its budget;
  - false alerts per asset-hour at the old and the new parameters, on a held-out part of the recording;
  - detection on the injected runaways;
  - the delta threshold marked uncalibrated: no ambient recorded.

**Files.**
- Public: the script and its synthetic tests in openddil-tactical-agents (a new `tools/calibrate_thermal.py` and `tests/test_calibrate_thermal.py`, or wherever review puts them). Once reviewed, the params in `algorithms/thermal/unit.yaml`, with a basis that names the recording.
- Overlay: the report and any numbers derived from the recording, under a new path such as `calibration/thermal-<edge>.json`. They stay there until review agrees what may cross.

**Waits on.** The new recording and its export. Nothing else.
