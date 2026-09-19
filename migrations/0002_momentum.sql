-- Migration number: 0002 	 2026-09-19
-- Momentum runs (BUILD_PLAN.md Phase 7). Same shape as scores; every run appends.

CREATE TABLE IF NOT EXISTS momentum (
  geoid TEXT NOT NULL,
  config_version TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  momentum REAL NOT NULL,          -- 0-100; 50 is keeping pace with the benchmarks
  label TEXT,                      -- rising | steady | fading, null when coverage is below the floor
  factor_scores TEXT NOT NULL,     -- JSON
  factor_inputs TEXT NOT NULL,     -- JSON: every input value used, with its r2_key
  coverage REAL NOT NULL,          -- 0-1
  PRIMARY KEY (geoid, config_version, computed_at)
);
CREATE INDEX IF NOT EXISTS momentum_geoid_idx ON momentum (geoid, config_version, computed_at DESC);
