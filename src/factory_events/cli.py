"""factory-events CLI: emit, verify, adapt, ship, import-file.

emit, verify and adapt use the database chain when FACTORY_EVENTS_APPEND_PASSWORD or
FACTORY_EVENTS_READ_PASSWORD is set (chain.py), and the file chain when neither is.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from factory_events import chain, db, store
from factory_events.db import ChainError
from factory_events.envelope import EnvelopeError, make_event


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmd_emit(args: argparse.Namespace) -> int:
    try:
        evidence = [json.loads(args.evidence_json)] if args.evidence_json else []
        event = make_event(
            actor=args.actor,
            action=args.action,
            result=args.result,
            target=args.target,
            correlation_id=args.correlation_id,
            evidence=evidence,
            timestamp=_utc_now(),
            source={"system": "direct", "ref": args.ref},
        )
    except (EnvelopeError, json.JSONDecodeError) as exc:
        print(f"emit failed: {exc}", file=sys.stderr)
        return 1
    try:
        record = chain.append_event(event)
    except ChainError as exc:
        print(f"emit failed: {exc}", file=sys.stderr)
        return 1
    # The bare id is stdout's last line, after any JSON log record, all of which carry this
    # same id: intent-packages' _parse_event_id reads either.
    print(event["event_id"])
    print(f"seq={record['seq']} head={record['hash']}", file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        params = chain.verify_params()
    except ChainError as exc:
        print(f"VERIFY FAIL: {exc}", file=sys.stderr)
        return 1
    if params:
        return _verify_database(params, args)
    if getattr(args, "record_anchor", False):
        print("VERIFY FAIL: --record-anchor needs the database chain", file=sys.stderr)
        return 1
    tolerate_torn_tail = getattr(args, "tolerate_torn_tail", False)
    errors = store.verify_chain(tolerate_torn_tail=tolerate_torn_tail)
    if errors:
        for err in errors:
            print(f"VERIFY FAIL: {err}", file=sys.stderr)
        return 1
    records = store.parsed_records(tolerate_torn_tail=tolerate_torn_tail)
    current = (records[-1]["seq"], records[-1]["hash"]) if records else None
    if getattr(args, "against_anchor", False):
        from factory_events import ship as ship_mod

        anchor = ship_mod.last_anchor()
        if anchor is not None:
            seqs = {rec["seq"]: rec["hash"] for rec in records}
            if seqs.get(anchor[0]) != anchor[1]:
                print(
                    f"VERIFY FAIL: anchored head (seq {anchor[0]}) not in chain — "
                    "store rewritten since last anchor",
                    file=sys.stderr,
                )
                return 1
            print(f"anchor ok: seq {anchor[0]} present")
    _print_chain_ok(current)
    return 0


def _print_chain_ok(current: tuple[int, str] | None) -> None:
    print(
        f"chain ok: {current[0] if current else 0} events"
        + (f", head {current[1]}" if current else "")
    )


def _verify_database(params: db.ConnectParams, args: argparse.Namespace) -> int:
    if getattr(args, "tolerate_torn_tail", False):
        print("VERIFY FAIL: --tolerate-torn-tail applies to the file chain only", file=sys.stderr)
        return 1
    record_anchor = getattr(args, "record_anchor", False)
    try:
        anchor = chain.read_anchor() if args.against_anchor or record_anchor else None
        result = db.verify(params, anchor_seq=anchor[0] if anchor else None)
    except ChainError as exc:
        print(f"VERIFY FAIL: {exc}", file=sys.stderr)
        return 1
    if result.errors:
        for err in result.errors:
            print(f"VERIFY FAIL: {err}", file=sys.stderr)
        return 1
    if anchor is not None:
        if result.anchor_hash != anchor[1]:
            print(
                f"VERIFY FAIL: anchored head (seq {anchor[0]}) not in chain — "
                "chain rewritten since last anchor",
                file=sys.stderr,
            )
            return 1
        print(f"anchor ok: seq {anchor[0]} present")
    if record_anchor and result.head:
        chain.write_anchor(result.head)
    _print_chain_ok(result.head)
    return 0


def _cmd_ship(args: argparse.Namespace) -> int:
    try:
        database_mode = chain.database_mode()
    except ChainError as exc:
        print(f"SHIP FAIL: {exc}", file=sys.stderr)
        return 1
    if database_mode:
        # The file isn't the chain in database mode; projecting it would ship a stale copy.
        print(
            "SHIP FAIL: ship projects the file chain, and a chain password is set",
            file=sys.stderr,
        )
        return 1
    from factory_events import ship as ship_mod

    try:
        inserted, current = ship_mod.ship(rebuild=args.rebuild)
    except Exception as exc:  # noqa: BLE001 — any DB failure is a hard job failure
        print(f"SHIP FAIL: {exc}", file=sys.stderr)
        return 1
    if current:
        print(f"shipped={inserted} head_seq={current[0]} head={current[1]}")
    else:
        print("shipped=0 (empty store)")
    return 0


def _cmd_adapt(args: argparse.Namespace) -> int:
    from factory_events.adapters import change_manager, high_power

    failures = 0
    if args.source in ("high-power", "all"):
        try:
            count = high_power.adapt(reanchor=args.reanchor)
            print(f"high-power: {count} events appended")
        except (high_power.WatermarkError, high_power.SourceError, ChainError) as exc:
            print(f"ADAPT FAIL (high-power): {exc}", file=sys.stderr)
            failures += 1
    if args.source in ("change-manager", "all"):
        try:
            count = change_manager.adapt()
            print(f"change-manager: {count} events appended")
        except (change_manager.ConfigError, OSError, ChainError) as exc:
            print(f"ADAPT FAIL (change-manager): {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def _cmd_import_file(args: argparse.Namespace) -> int:
    try:
        # The one-time import runs as the append-only role (ADR-0055 amendment 25 item 4).
        params = chain.connection_params(chain.APPEND_ROLE)
        head = db.import_file(params, Path(args.path).expanduser())
    except ChainError as exc:
        print(f"IMPORT FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"imported: {head[0] if head else 0} events" + (f", head {head[1]}" if head else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory_events")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit", help="append one direct event to the store")
    emit.add_argument("--actor", required=True)
    emit.add_argument("--action", required=True)
    emit.add_argument("--result", required=True, choices=["success", "failure", "unknown"])
    emit.add_argument("--ref", required=True, help="source.ref, e.g. the emitter name")
    emit.add_argument("--target", default=None)
    emit.add_argument("--correlation-id", dest="correlation_id", default=None)
    emit.add_argument(
        "--evidence-json",
        dest="evidence_json",
        default=None,
        help="one JSON object appended to evidence[]",
    )
    emit.set_defaults(func=_cmd_emit)

    verify = sub.add_parser("verify", help="verify the full hash chain + schemas")
    verify.add_argument("--against-anchor", action="store_true")
    verify.add_argument(
        "--tolerate-torn-tail",
        action="store_true",
        help="accept one truncated final line (restored-copy verification)",
    )
    verify.add_argument(
        "--record-anchor",
        action="store_true",
        help="database chain: check the anchor, then anchor the verified head",
    )
    verify.set_defaults(func=_cmd_verify)

    adapt = sub.add_parser("adapt", help="translate source logs into the store")
    adapt.add_argument("--source", required=True, choices=["high-power", "change-manager", "all"])
    adapt.add_argument("--reanchor", action="store_true")
    adapt.set_defaults(func=_cmd_adapt)

    ship_cmd = sub.add_parser("ship", help="upsert events into the Postgres projection")
    ship_cmd.add_argument(
        "--rebuild",
        action="store_true",
        help="truncate factory_events (never chain_heads) and replay",
    )
    ship_cmd.set_defaults(func=_cmd_ship)

    import_cmd = sub.add_parser(
        "import-file",
        help="replay a verified events file into an empty database chain "
        "(as the append role: FACTORY_EVENTS_APPEND_PASSWORD and the DB settings)",
    )
    import_cmd.add_argument("--path", required=True, help="the events file to import")
    import_cmd.set_defaults(func=_cmd_import_file)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse: 0 for --help, 2 for usage errors
        return 0 if exc.code == 0 else 1
    return args.func(args)
