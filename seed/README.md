# seed/

`pilot_v0.csv` belongs here: the 20 towns scored by hand during research. It is the
regression fixture for QA rule 4 (rebuilt scores must land within ±3 points). It was not in
the repository when the build started; the owner needs to add it before Phase 3.

Expected columns (adjust the loader in `pipeline/qa/` if the real file differs):
`geoid,name,readiness,grade,notes`.
