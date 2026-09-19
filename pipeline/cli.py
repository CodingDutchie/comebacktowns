"""``python -m pipeline.cli <command>``: the single entry point for every pipeline step."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline.ingest.base import normalise_as_of
from pipeline.ingest.registry import DISCOVERERS, FEEDS, discover_new_years, fetch_all, fetch_one
from pipeline.qa import QAError
from pipeline.settings import scope_config
from pipeline.storage import raw_store

log = logging.getLogger("pipeline")


def cmd_ingest(args: argparse.Namespace) -> int:
    store = raw_store()
    names = list(FEEDS) if args.all else args.source
    if not names:
        log.error("name at least one source or pass --all; known: %s", ", ".join(FEEDS))
        return 2
    unknown = [n for n in names if n not in FEEDS]
    if unknown:
        log.error("unknown source(s): %s; known: %s", unknown, ", ".join(FEEDS))
        return 2
    keys = (
        fetch_all(args.as_of, store=store)
        if args.all
        else {n: fetch_one(n, args.as_of, store=store) for n in names}
    )
    for name, source_keys in keys.items():
        print(f"{name}\t{len(source_keys)} file(s)")
        for key in source_keys[: args.show]:
            print(f"\t{key}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Print one line per source that has a newly published year: ``source<TAB>year year``.

    Nothing is fetched or written; the refresh workflows use the output to decide which
    sources to pull. Sources with nothing new print nothing.
    """
    names = args.source or list(DISCOVERERS)
    unknown = [n for n in names if n not in DISCOVERERS]
    if unknown:
        log.error("no year discovery for: %s; known: %s", unknown, ", ".join(DISCOVERERS))
        return 2
    for name, years in discover_new_years(names).items():
        if years:
            print(f"{name}\t{' '.join(years)}")
        else:
            log.info("%s: nothing beyond the configured years", name)
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    from pipeline.ingest import gazetteer, popest
    from pipeline.qa.towns import validate_towns
    from pipeline.scope import TOWN_COLUMNS, build_towns

    scope = scope_config()
    store = raw_store()
    as_of = normalise_as_of(args.as_of)
    popest_key = popest.fetch(as_of, store=store)
    gaz_key = gazetteer.fetch(as_of, store=store)
    towns = build_towns(store.get_bytes(popest_key), store.get_bytes(gaz_key), scope)
    try:
        validate_towns(towns, scope)
    except QAError as exc:
        log.error("%s", exc)
        return 1
    if args.out:
        with Path(args.out).open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(TOWN_COLUMNS)
            writer.writerows(t.row() for t in towns)
        log.info("scope: wrote %s", args.out)
    if args.dry_run:
        print(f"{len(towns)} towns in scope (dry run, nothing written to D1)")
        return 0
    from pipeline.load.d1 import D1Client
    from pipeline.load.towns import load_towns

    d1 = D1Client.from_env()
    written, removed = load_towns(towns, d1)
    print(f"towns: {written} upserted, {removed} removed, {d1.count('towns')} now in D1")
    return 0


def cmd_transform(args: argparse.Namespace) -> int:
    from pipeline.qa.metrics import check_coverage, coverage_report, validate_metrics
    from pipeline.scope import towns_from_store
    from pipeline.transform import METRIC_COLUMNS
    from pipeline.transform.run import run_transforms

    store = raw_store()
    as_of = normalise_as_of(args.as_of)
    towns = towns_from_store(store, as_of)
    rows = run_transforms(store, as_of, towns=towns, only=args.only or None)
    dates = sorted({(r.source_id, r.as_of) for r in rows})
    print("snapshots used: " + ", ".join(f"{s}={d}" for s, d in dates))
    try:
        validate_metrics(rows)
    except QAError as exc:
        log.error("%s", exc)
        return 1
    report = coverage_report(rows, len(towns))
    print("coverage of scoring inputs (usable share of towns):")
    for name, share in report.items():
        print(f"  {name:32s} {share:6.1%}")
    from pipeline.settings import momentum_config

    print("coverage of momentum inputs (shown, not gated):")
    for name, share in coverage_report(rows, len(towns), scoring=momentum_config()).items():
        print(f"  {name:32s} {share:6.1%}")
    if args.out:
        with Path(args.out).open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(METRIC_COLUMNS)
            writer.writerows(r.row() for r in rows)
        log.info("transform: wrote %s", args.out)
    if not args.only:
        try:
            check_coverage(report)
        except QAError as exc:
            log.error("coverage gate failed: %s", exc)
            if not args.allow_low_coverage:
                return 1
    if args.dry_run:
        print(f"{len(rows)} metric rows (dry run, nothing written to D1)")
        return 0
    from pipeline.load.d1 import D1Client
    from pipeline.load.metrics import load_metrics

    d1 = D1Client.from_env()
    written = load_metrics(rows, d1)
    print(f"metrics: {written} upserted, {d1.count('metrics')} rows now in D1")
    return 0


def read_metrics_csv(path: Path) -> list[dict[str, Any]]:
    """Metric rows as written by ``transform --out``, typed like the D1 rows."""
    rows: list[dict[str, Any]] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                {
                    **row,
                    "value": float(row["value"]) if row["value"] not in ("", None) else None,
                    "moe": float(row["moe"]) if row["moe"] not in ("", None) else None,
                    "suppressed": int(row["suppressed"] or 0),
                }
            )
    return rows


def run_scoring(args: argparse.Namespace, *, kind: str) -> int:
    """``score`` (readiness) and ``momentum`` share one path: load, score, explain or
    summarise, run the QA that applies, then write unless this is a dry run."""
    from pipeline.load.d1 import D1Client
    from pipeline.load.scores import (
        MOMENTUM_COLUMNS,
        load_momentum,
        load_scores,
        read_metrics,
        read_towns,
    )
    from pipeline.qa.pilot import PilotFixtureMissingError, check_pilot, load_pilot
    from pipeline.scope import Town
    from pipeline.score.curves import CURVES, MOMENTUM_CURVES
    from pipeline.score.engine import SCORE_COLUMNS, explain, grade_word, score_all
    from pipeline.settings import momentum_config, scoring_config

    if kind == "momentum":
        config = momentum_config(args.config_version)
        curves = MOMENTUM_CURVES[args.config_version]
        columns = MOMENTUM_COLUMNS
    else:
        config = scoring_config(args.config_version)
        curves = CURVES[args.config_version]
        columns = SCORE_COLUMNS
    d1 = D1Client.from_env()
    towns = [Town(**row) for row in read_towns(d1)]
    if args.metrics_csv:
        metric_rows = read_metrics_csv(Path(args.metrics_csv))
        log.info("%s: %d metric rows from %s", kind, len(metric_rows), args.metrics_csv)
    else:
        metric_rows = read_metrics(d1)
    scores = score_all(
        towns, metric_rows, version=args.config_version, config=config, curves=curves
    )
    by_geoid = {t.geoid: t for t in towns}
    if args.explain:
        town = next((t for t in towns if args.explain in (t.geoid, t.slug)), None)
        if town is None:
            log.error("no town with geoid or slug %s", args.explain)
            return 2
        score = next(s for s in scores if s.geoid == town.geoid)
        print(explain(score, town, config, curves))
        return 0
    word = grade_word(config)
    labelled = sum(1 for s in scores if s.grade)
    print(
        f"{kind}: scored {len(scores)} towns, {labelled} with a {word}, "
        f"{len(scores) - labelled} without"
    )
    if word == "label":
        counts = {
            name: sum(1 for s in scores if s.grade == name) for name in config["grading"]["bands"]
        }
        print(f"  labels {counts}")
    else:
        for band in sorted({s.band for s in scores}):
            members = [s for s in scores if s.band == band]
            letters = {g: sum(1 for s in members if s.grade == g) for g in "ABCDF"}
            print(f"  band {band:12s} n={len(members):3d} grades {letters}")
    if args.out:
        with Path(args.out).open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([*columns, "slug", "band"])
            for s in scores:
                writer.writerow([*s.row(), by_geoid[s.geoid].slug, s.band])
        log.info("%s: wrote %s", kind, args.out)
    if kind == "readiness":
        try:
            for line in check_pilot(scores, {t.geoid: t.slug for t in towns}, load_pilot()):
                print("  pilot " + line)
        except PilotFixtureMissingError as exc:
            log.error("%s", exc)
            if not args.no_pilot:
                log.error("QA rule 4 cannot run; pass --no-pilot to write scores regardless")
                return 1
        except QAError as exc:
            log.error("%s", exc)
            return 1
    if args.dry_run:
        print("dry run, nothing written to D1")
        return 0
    written = load_momentum(scores, d1) if kind == "momentum" else load_scores(scores, d1)
    print(f"{kind}: {written} rows written for config {args.config_version}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    return run_scoring(args, kind="readiness")


def cmd_momentum(args: argparse.Namespace) -> int:
    return run_scoring(args, kind="momentum")


def cmd_export(args: argparse.Namespace) -> int:
    from pipeline.export import export_site_data
    from pipeline.load.d1 import D1Client

    counts = export_site_data(
        D1Client.from_env(), version=args.config_version, momentum_version=args.momentum_version
    )
    print(f"export: {counts}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline.cli")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="fetch raw feeds into R2 under a dated key")
    ingest.add_argument("source", nargs="*", help="source ids from config/sources.yml")
    ingest.add_argument("--all", action="store_true")
    ingest.add_argument("--as-of", help="ISO date for the snapshot key (default: today)")
    ingest.add_argument("--show", type=int, default=5, help="keys to print per source")
    ingest.set_defaults(func=cmd_ingest)

    discover = sub.add_parser(
        "discover", help="probe annual feeds for years newer than config/sources.yml"
    )
    discover.add_argument("source", nargs="*", help=f"any of: {', '.join(DISCOVERERS)}")
    discover.set_defaults(func=cmd_discover)

    scope = sub.add_parser("scope", help="build the in-scope town list and write the towns table")
    scope.add_argument("--as-of", help="ISO date of the popest/gazetteer snapshot to use")
    scope.add_argument("--dry-run", action="store_true", help="build and validate, skip D1")
    scope.add_argument("--out", help="also write the towns as CSV to this path")
    scope.set_defaults(func=cmd_scope)

    transform = sub.add_parser("transform", help="raw snapshots -> metrics rows -> D1")
    transform.add_argument("--as-of", help="ISO date of the raw snapshot to transform")
    transform.add_argument("--dry-run", action="store_true", help="build and validate, skip D1")
    transform.add_argument("--out", help="also write the metric rows as CSV to this path")
    transform.add_argument("--only", nargs="*", help="run only these transforms")
    transform.add_argument(
        "--allow-low-coverage", action="store_true", help="write even if the coverage gate fails"
    )
    transform.set_defaults(func=cmd_transform)

    def scoring_args(parser: argparse.ArgumentParser, default_version: str = "v1") -> None:
        parser.add_argument("--config-version", default=default_version)
        parser.add_argument(
            "--explain", metavar="GEOID_OR_SLUG", help="print the audit trail for one town"
        )
        parser.add_argument("--dry-run", action="store_true", help="score and validate, skip D1")
        parser.add_argument("--out", help="also write the results as CSV to this path")
        parser.add_argument(
            "--metrics-csv",
            help="score from a transform --out file instead of the D1 metrics table",
        )

    score = sub.add_parser("score", help="metrics -> readiness scores and grades -> D1")
    scoring_args(score)
    score.add_argument(
        "--no-pilot", action="store_true", help="proceed when seed/pilot_v0.csv is missing"
    )
    score.set_defaults(func=cmd_score)

    momentum = sub.add_parser(
        "momentum", help="metrics -> momentum scores and rising/steady/fading labels -> D1"
    )
    from pipeline.settings import MOMENTUM_VERSION

    scoring_args(momentum, MOMENTUM_VERSION)
    momentum.set_defaults(func=cmd_momentum)

    export = sub.add_parser("export", help="D1 -> site/data/*.json and the dataset download")
    export.add_argument("--config-version", default="v1")
    export.add_argument("--momentum-version", default=MOMENTUM_VERSION)
    export.set_defaults(func=cmd_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # httpx logs every request URL at INFO; those carry the account id and, for the Census
    # API, the key parameter. Our own log lines use redact_url instead.
    for noisy in ("httpx", "httpcore", "botocore", "boto3", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
