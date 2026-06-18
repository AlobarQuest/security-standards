from __future__ import annotations

import argparse
from pathlib import Path

from .loader import load_map
from .deploy import deploy_artifacts, verify_artifacts
from .stanza import sync_stanza, verify_stanza, ensure_bws_manifest

DEFAULT_MAP = Path(__file__).resolve().parents[3] / "governance-map.toml"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="security_scan.governance")
    ap.add_argument("command", choices=["deploy", "sync", "verify"])
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--artifacts-only", action="store_true",
                    help="verify: check deployed artifacts only, skip CLAUDE.md stanzas")
    args = ap.parse_args(argv)
    manifest = load_map(args.map)

    if args.command == "deploy":
        for name, act in deploy_artifacts(manifest):
            print(f"{act}: {name}")
        return 0

    if args.command == "verify":
        problems = [f"artifact {kind}: {name}" for name, kind in verify_artifacts(manifest)]
        if not args.artifacts_only:
            for r in manifest.repos:
                v = verify_stanza(r, manifest)
                if v != "ok":
                    problems.append(f"stanza {v}: {r.name}")
        if problems:
            print("\n".join(problems))
            return 1
        scope = "artifacts" if args.artifacts_only else "artifacts + stanzas"
        print(f"governance verify: {scope} in sync")
        return 0

    if args.command == "sync":
        for r in manifest.repos:
            print(f"{sync_stanza(r, manifest)}: {r.name}/CLAUDE.md")
            print(f"{ensure_bws_manifest(r)}: {r.name}/.bws-secrets.toml")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
