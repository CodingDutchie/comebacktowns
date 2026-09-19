import csv

from pipeline import cli


def test_scope_dry_run_writes_csv(
    monkeypatch, tmp_path, popest_bytes, gazetteer_zip, scope, local_store
):
    monkeypatch.setattr(cli, "raw_store", lambda: local_store)
    monkeypatch.setattr(cli, "scope_config", lambda: scope)
    local_store.put_bytes("raw/popest/2026-09-18/sub-est2024.csv", popest_bytes)
    local_store.put_bytes("raw/gazetteer/2026-09-18/2024_Gaz_place_national.zip", gazetteer_zip)
    out = tmp_path / "towns.csv"
    rc = cli.main(["scope", "--as-of", "2026-09-18", "--dry-run", "--out", str(out)])
    assert rc == 0
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 4 and rows[0]["slug"] == "catskill-ny"


def test_momentum_command_shares_the_scoring_options():
    args = cli.build_parser().parse_args(["momentum", "--dry-run", "--metrics-csv", "m.csv"])
    assert args.func is cli.cmd_momentum and args.dry_run and args.metrics_csv == "m.csv"
    assert not hasattr(args, "no_pilot")
    from pipeline.settings import MOMENTUM_VERSION

    assert args.config_version == MOMENTUM_VERSION == "v2"
    assert cli.build_parser().parse_args(["score"]).config_version == "v1"
    assert cli.build_parser().parse_args(["export"]).momentum_version == "v2"
    assert cli.build_parser().parse_args(["score", "--no-pilot"]).func is cli.cmd_score


def test_ingest_rejects_unknown_source(monkeypatch, local_store):
    monkeypatch.setattr(cli, "raw_store", lambda: local_store)
    assert cli.main(["ingest", "nonsense"]) == 2
