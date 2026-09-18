-- Migration number: 0001 	 2026-09-18
-- Canonical tables for comebacktowns.com (BUILD_PLAN.md §5).

CREATE TABLE IF NOT EXISTS towns (
  geoid TEXT PRIMARY KEY,          -- Census place GEOID, e.g. 3613002
  name TEXT NOT NULL,              -- "Catskill"
  legal_type TEXT NOT NULL,        -- city | village | town
  county TEXT NOT NULL,            -- "Greene"
  county_fips TEXT NOT NULL,       -- "039" (3-digit, within state)
  region TEXT NOT NULL,            -- Hudson Valley | Capital Region | Mohawk Valley
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  pop_latest INTEGER,
  pop_latest_year INTEGER,
  slug TEXT UNIQUE NOT NULL        -- catskill-ny
);

CREATE TABLE IF NOT EXISTS metrics (
  geoid TEXT NOT NULL,
  metric TEXT NOT NULL,            -- median_home_value | vacancy_rate | permits_per_1k | ...
  period TEXT NOT NULL,            -- "2020-2024" | "2025" | "2026-08"
  value REAL,
  moe REAL,                        -- null when not applicable
  suppressed INTEGER NOT NULL DEFAULT 0,
  source_id TEXT NOT NULL,         -- key in config/sources.yml
  as_of TEXT NOT NULL,             -- ISO date pulled
  r2_key TEXT NOT NULL,            -- exact raw file this came from
  PRIMARY KEY (geoid, metric, period)
);
CREATE INDEX IF NOT EXISTS metrics_metric_idx ON metrics (metric, period);

CREATE TABLE IF NOT EXISTS scores (
  geoid TEXT NOT NULL,
  config_version TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  readiness REAL NOT NULL,         -- 0-100
  grade TEXT,                      -- A..F, null when coverage is below the floor
  factor_scores TEXT NOT NULL,     -- JSON
  factor_inputs TEXT NOT NULL,     -- JSON: every input value used
  coverage REAL NOT NULL,          -- 0-1
  PRIMARY KEY (geoid, config_version, computed_at)
);
CREATE INDEX IF NOT EXISTS scores_geoid_idx ON scores (geoid, config_version, computed_at DESC);
