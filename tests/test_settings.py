import os
import re

import pytest

from pipeline import settings


def test_redact_url_strips_key_value():
    url = "https://api.census.gov/data?get=NAME&key=abc123&for=state:36"
    assert (
        settings.redact_url(url) == "https://api.census.gov/data?get=NAME&key=REDACTED&for=state:36"
    )
    assert "abc123" not in settings.redact_url("https://x/?key=abc123")
    assert settings.redact_url("https://x/?other=1") == "https://x/?other=1"


def test_require_env_names_the_missing_secret(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(settings.MissingSecretError, match="CENSUS_API_KEY"):
        settings.require_env("CENSUS_API_KEY")
    monkeypatch.setenv("CENSUS_API_KEY", "")
    with pytest.raises(settings.MissingSecretError):
        settings.require_env("CENSUS_API_KEY")
    monkeypatch.setenv("CENSUS_API_KEY", "x")
    assert settings.require_env("CENSUS_API_KEY") == "x"


def test_config_files_load_and_are_consistent():
    site = settings.site_config()
    assert site["SITE_NAME"] == "Comeback Towns"
    assert site["SITE_DOMAIN"] == "comebacktowns.com"  # plural, always
    scoring = settings.scoring_config("v1")
    assert scoring["version"] == "v1"
    assert abs(sum(f["weight"] for f in scoring["factors"].values()) - 1.0) < 1e-9
    scope = settings.scope_config()
    seen: set[str] = set()
    for counties in scope["regions"].values():
        for fips in counties:
            assert fips not in seen, f"county {fips} in two regions"
            seen.add(fips)
    assert settings.d1_database_id()
    assert settings.r2_bucket_name() == "comebacktowns-raw"


def test_wrangler_toml_holds_no_secrets(monkeypatch):
    text = (settings.ROOT / "wrangler.toml").read_text()
    config = settings.wrangler_config()
    assert "account_id" not in config
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        value = os.environ.get(name)
        if value:
            assert value not in text
    # nothing token-shaped: a 40-char base62 run
    assert not re.search(r"[A-Za-z0-9_-]{40}", text)
