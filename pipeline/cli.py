"""``python -m pipeline.cli <command>``: the single entry point for every pipeline step."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pipeline.ingest.base import normalise_as_of
from pipeline.ingest.registry import FEEDS, fetch_all, fetch_one
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
    try:
        validate_metrics(rows)
    except QAError as exc:
        log.error("%s", exc)
        return 1
    report = coverage_report(rows, len(towns))
    print("coverage of scoring inputs (usable share of towns):")
    for name, share in report.items():
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


def cmd_score(args: argparse.Namespace) -> int:
    from pipeline.load.d1 import D1Client
    from pipeline.load.scores import load_scores, read_metrics, read_towns
    from pipeline.qa.pilot import PilotFixtureMissingError, check_pilot, load_pilot
    from pipeline.scope import Town
    from pipeline.score.curves import CURVES
    from pipeline.score.engine import SCORE_COLUMNS, explain, score_all
    from pipeline.settings import scoring_config

    d1 = D1Client.from_env()
    towns = [Town(**row) for row in read_towns(d1)]
    scores = score_all(towns, read_metrics(d1), version=args.config_version)
    by_geoid = {t.geoid: t for t in towns}
    if args.explain:
        town = next((t for t in towns if args.explain in (t.geoid, t.slug)), None)
        if town is None:
            log.error("no town with geoid or slug %s", args.explain)
            return 2
        score = next(s for s in scores if s.geoid == town.geoid)
        print(
            explain(score, town, scoring_config(args.config_version), CURVES[args.config_version])
        )
        return 0
    graded = sum(1 for s in scores if s.grade)
    print(f"scored {len(scores)} towns, {graded} graded, {len(scores) - graded} without a grade")
    for band in sorted({s.band for s in scores}):
        members = [s for s in scores if s.band == band]
        letters = {g: sum(1 for s in members if s.grade == g) for g in "ABCDF"}
        print(f"  band {band:12s} n={len(members):3d} grades {letters}")
    if args.out:
        with Path(args.out).open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([*SCORE_COLUMNS, "slug", "band"])
            for s in scores:
                writer.writerow([*s.row(), by_geoid[s.geoid].slug, s.band])
        log.info("score: wrote %s", args.out)
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
    written = load_scores(scores, d1)
    print(f"scores: {written} rows written for config {args.config_version}")
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

    score = sub.add_parser("score", help="metrics -> readiness scores and grades -> D1")
    score.add_argument("--config-version", default="v1")
    score.add_argument(
        "--explain", metavar="GEOID_OR_SLUG", help="print the audit trail for one town"
    )
    score.add_argument("--dry-run", action="store_true", help="score and validate, skip D1")
    score.add_argument("--out", help="also write the scores as CSV to this path")
    score.add_argument(
        "--no-pilot", action="store_true", help="proceed when seed/pilot_v0.csv is missing"
    )
    score.set_defaults(func=cmd_score)
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
