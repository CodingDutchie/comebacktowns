# seed/

`pilot_v0.csv` is the fixture for QA rule 4 (BUILD_PLAN §7): every `score` run must land
within ±3 points of the `readiness` column for each row that has one, or the run stops.

The 20 rows are the towns the owner scored by hand during research
(`ny_pilot_readiness_v0.1`), with a `slug` column added for matching. Columns:

- `readiness`: the baseline the engine is held to. It is the v1 engine's own output from
  the run of 2026-09-19, set per §11.3 after the hand scores were found to differ from v1
  structurally (5 of 15 in-scope towns within ±3, mean drift −6.6). Blank for the five towns
  outside the v1 scope (Norwich, Geneva, Olean, Hornell, Dunkirk), which are reference only.
- `pilot_score`: the original hand score on 0-100, kept for reference and never compared.
- the remaining columns are the research inputs and the pilot's own five factor scores
  (access, head, char, civic, stress), also reference only.

Re-baseline only with the owner's decision, and only after a methodology change that is
published as a new `config/scoring.*.yml` version.
