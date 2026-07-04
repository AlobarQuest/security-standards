from __future__ import annotations

import argparse
from pathlib import Path

from .deploy import deploy_artifacts, reconcile_control_plane, verify_artifacts
from .loader import load_map
from .ownership import (
    ensure_bws_manifest,
    strip_stanza,
    verify_headers,
    verify_ownership,
    write_ownership,
)

DEFAULT_MAP = Path(__file__).resolve().parents[3] / "governance-map.toml"
DEFAULT_OWNERSHIP = "~/.claude/OWNERSHIP.md"


def main(argv=None) -> int:  # noqa: C901
    ap = argparse.ArgumentParser(prog="security_scan.governance")
    ap.add_argument("command", choices=["deploy", "verify", "ownership", "strip-stanzas"])
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument(
        "--artifacts-only",
        action="store_true",
        help="verify: deployed-faithfulness only (artifacts + source headers); "
        "skip OWNERSHIP.md freshness",
    )
    ap.add_argument("--ownership-path", default=DEFAULT_OWNERSHIP)
    args = ap.parse_args(argv)
    manifest = load_map(args.map)

    if args.command == "deploy":
        for name, act in deploy_artifacts(manifest):
            print(f"{act}: {name}")
        # Reconcile the control-plane git baseline so a legit deploy is silent to
        # the Check-13 tamper-evidence scan (and closes the "remember to commit
        # after install" gap). Commits only the deployed paths; never sweeps.
        for root, note in reconcile_control_plane(manifest):
            print(f"{note}: {root}")
        return 0

    if args.command == "ownership":
        print(f"{write_ownership(manifest, args.ownership_path)}: {args.ownership_path}")
        for r in manifest.repos:
            print(f"{ensure_bws_manifest(r)}: {r.name}/.bws-secrets.toml")
        return 0

    if args.command == "verify":
        problems = [f"artifact {kind}: {name}" for name, kind in verify_artifacts(manifest)]
        problems += [f"header {kind}: {name}" for name, kind in verify_headers(manifest)]
        if not args.artifacts_only:
            ov = verify_ownership(manifest, args.ownership_path)
            if ov != "ok":
                problems.append(f"ownership {ov}: {args.ownership_path}")
        if problems:
            print("\n".join(problems))
            return 1
        scope = "artifacts + headers" if args.artifacts_only else "artifacts + headers + ownership"
        print(f"governance verify: {scope} in sync")
        return 0

    if args.command == "strip-stanzas":
        for r in manifest.repos:
            print(f"{strip_stanza(r)}: {r.name}/CLAUDE.md")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
