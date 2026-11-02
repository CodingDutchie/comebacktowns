import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "container"))

import jobs  # noqa: E402  (container/ is not a package)
import server  # noqa: E402


def test_ingest_builds_one_argv_per_source() -> None:
    (cmd,) = jobs.commands_for("ingest", {"source": "permits"})
    assert cmd[-2:] == ["ingest", "permits"]


@pytest.mark.parametrize("bad", ["", "Permits", "a b", "x;rm -rf /", "../etc", None, 3])
def test_ingest_rejects_unsafe_sources(bad: object) -> None:
    with pytest.raises(ValueError):
        jobs.commands_for("ingest", {"source": bad})


def test_unknown_job_is_refused() -> None:
    with pytest.raises(ValueError):
        jobs.commands_for("rm", {})


def test_validate_is_all_dry_and_shares_metrics_csv() -> None:
    cmds = jobs.commands_for("validate", {"skip_pilot": True})
    assert all("--dry-run" in c for c in cmds)
    assert "--no-pilot" in cmds[1] and "--no-pilot" not in cmds[2]
    assert all("metrics.csv" in c for c in cmds[:2]) and "metrics.csv" in cmds[2]


def test_load_writes_and_skips_pilot_only_on_request() -> None:
    cmds = jobs.commands_for("load", {})
    assert [c[3] for c in cmds] == ["transform", "score", "momentum"]
    assert not any("--dry-run" in c or "--no-pilot" in c for c in cmds)
    with pytest.raises(ValueError):
        jobs.commands_for("load", {"skip_pilot": "yes"})


def test_server_scrubs_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "s3cr3t-token-value")
    assert server.scrub("auth s3cr3t-token-value ok") == "auth *** ok"


def test_job_runner_reports_failure_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "APP_DIR", str(tmp_path))
    job = {"state": "running", "exit_code": None, "log": "", "stdout": ""}
    server._run(
        job,
        [
            [sys.executable, "-c", "print('hi')"],
            [sys.executable, "-c", "raise SystemExit(3)"],
            [sys.executable, "-c", "print('never')"],
        ],
    )
    assert job["state"] == "failed" and job["exit_code"] == 3
    assert "never" not in job["log"]
