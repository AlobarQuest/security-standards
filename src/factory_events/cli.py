"""factory-events CLI: emit, verify (adapt/ship added by later tasks)."""

import argparse
import json
import sys
from datetime import UTC, datetime

from factory_events import store
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
    record = store.append_event(event)
    print(event["event_id"])
    print(f"seq={record['seq']} head={record['hash']}", file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    errors = store.verify_chain()
    if errors:
        for err in errors:
            print(f"VERIFY FAIL: {err}", file=sys.stderr)
        return 1
    current = store.head()
    print(f"chain ok: {current[0] if current else 0} events"
          + (f", head {current[1]}" if current else ""))
    # Task 7 extends verify with --against-anchor
    return 0


def _cmd_adapt(args: argparse.Namespace) -> int:
    from factory_events.adapters import high_power

    try:
        if args.source == "high-power":
            count = high_power.adapt(reanchor=args.reanchor)
            print(f"high-power: {count} events appended")
    except high_power.WatermarkError as exc:
        print(f"ADAPT FAIL: {exc}", file=sys.stderr)
        return 1
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
    emit.add_argument("--evidence-json", dest="evidence_json", default=None,
                      help="one JSON object appended to evidence[]")
    emit.set_defaults(func=_cmd_emit)

    verify = sub.add_parser("verify", help="verify the full hash chain + schemas")
    verify.set_defaults(func=_cmd_verify)

    adapt = sub.add_parser("adapt", help="translate source logs into the store")
    adapt.add_argument("--source", required=True, choices=["high-power"])
    adapt.add_argument("--reanchor", action="store_true")
    adapt.set_defaults(func=_cmd_adapt)
    # Task 7 extends here: ship
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse: 0 for --help, 2 for usage errors
        return 0 if exc.code == 0 else 1
    return args.func(args)
