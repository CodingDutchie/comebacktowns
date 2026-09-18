"""``python -m pipeline.cli <command>``: the single entry point for every pipeline step."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pipeline.ingest.base import normalise_as_of
from pipeline.ingest.registry import FEEDS, fetch_all
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
        else {n: FEEDS[n](args.as_of, store=store) for n in names}
    )
    for name, key in keys.items():
        print(f"{name}\t{key}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline.cli")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="fetch raw feeds into R2 under a dated key")
    ingest.add_argument("source", nargs="*", help="source ids from config/sources.yml")
    ingest.add_argument("--all", action="store_true")
    ingest.add_argument("--as-of", help="ISO date for the snapshot key (default: today)")
    ingest.set_defaults(func=cmd_ingest)

    scope = sub.add_parser("scope", help="build the in-scope town list and write the towns table")
    scope.add_argument("--as-of", help="ISO date of the popest/gazetteer snapshot to use")
    scope.add_argument("--dry-run", action="store_true", help="build and validate, skip D1")
    scope.add_argument("--out", help="also write the towns as CSV to this path")
    scope.set_defaults(func=cmd_scope)
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
