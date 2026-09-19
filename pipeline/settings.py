"""Environment, secrets and config access.

Secrets are read from ``os.environ`` only: never a literal, never a default. A missing secret
fails immediately with a message naming which one, so the pipeline can never degrade to an
unkeyed request.
"""

from __future__ import annotations

import os
import re
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
MIGRATIONS_DIR = ROOT / "migrations"


class MissingSecretError(RuntimeError):
    """Raised when a required environment variable is absent."""


def require_env(name: str) -> str:
    """Return the value of ``name`` from the environment, or fail naming it."""
    value = os.environ.get(name)
    if not value:
        raise MissingSecretError(
            f"{name} is not set. Provide it via the environment "
            "(GitHub Secrets in CI, .dev.vars or a shell export locally)."
        )
    return value


_KEY_PARAM = re.compile(r"([?&])key=[^&#]*", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Strip the value of any ``key=`` query parameter before a URL is logged."""
    return _KEY_PARAM.sub(r"\1key=REDACTED", url)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return data


@cache
def site_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "site.yml")


@cache
def scope_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "scope.yml")


@cache
def sources_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "sources.yml")


def scoring_config(version: str = "v1") -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / f"scoring.{version}.yml")


# The momentum config the CLI scores with and the export publishes. Readiness stays at v1
# (its default everywhere); momentum moves by adding a file and pointing this at it.
MOMENTUM_VERSION = "v2"


def momentum_config(version: str = MOMENTUM_VERSION) -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / f"momentum.{version}.yml")


@cache
def wrangler_config() -> dict[str, Any]:
    with (ROOT / "wrangler.toml").open("rb") as fh:
        return tomllib.load(fh)


def d1_database_id() -> str:
    """The D1 database id: ``D1_DATABASE_ID`` if set, else the binding in wrangler.toml."""
    explicit = os.environ.get("D1_DATABASE_ID")
    if explicit:
        return explicit
    for db in wrangler_config().get("d1_databases", []):
        if db.get("binding") == "DB":
            return str(db["database_id"])
    raise RuntimeError("No D1 binding named DB in wrangler.toml and D1_DATABASE_ID is unset")


def r2_bucket_name() -> str:
    explicit = os.environ.get("R2_BUCKET")
    if explicit:
        return explicit
    for bucket in wrangler_config().get("r2_buckets", []):
        if bucket.get("binding") == "RAW":
            return str(bucket["bucket_name"])
    raise RuntimeError("No R2 binding named RAW in wrangler.toml and R2_BUCKET is unset")
