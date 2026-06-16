"""Generate a repo's .bws-secrets.toml from its runtime BWS references.

This is the executable remediation for the bws.secret-manifest-present and
bws.manifest-matches-usage rules: it declares exactly the UUIDs the scanner
counts as consumed (manifest.referenced_uuids, runtime code only), optionally
enriched with each secret's name and project from BWS. It reads secret
*metadata* only — never values — and prints to stdout unless --write is given.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from security_scan import manifest


def build_enrich_map(secrets: list[dict], projects: list[dict]) -> dict[str, dict]:
    """uuid -> {name, project} from `bws secret list` + `bws project list`.
    Carries only the secret's key (name) and project — deliberately not `value`."""
    proj_name = {p["id"]: p.get("name") or p["id"] for p in projects}
    out: dict[str, dict] = {}
    for s in secrets:
        pid = s.get("projectId", "")
        out[s["id"]] = {"name": s.get("key", ""), "project": proj_name.get(pid, pid)}
    return out


def _bws_json(*args) -> list | None:
    """Run a read-only `bws ... --output json` command; None on any failure."""
    try:
        res = subprocess.run(["bws", *args, "--output", "json"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return None


def load_enrich_map() -> dict[str, dict] | None:
    """Build the enrich map from BWS, or None if BWS is unreachable/unauthorized."""
    secrets = _bws_json("secret", "list")
    if secrets is None:
        return None
    projects = _bws_json("project", "list") or []
    return build_enrich_map(secrets, projects)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate .bws-secrets.toml from runtime BWS references.")
    ap.add_argument("repo", nargs="?", default=".", help="repo path (default: cwd)")
    ap.add_argument("--write", action="store_true",
                    help="write .bws-secrets.toml in the repo (default: print to stdout)")
    ap.add_argument("--no-enrich", action="store_true",
                    help="skip the BWS lookup; emit UUID-only entries")
    args = ap.parse_args(argv)

    repo_path = Path(args.repo)
    referenced = manifest.referenced_uuids(repo_path)
    if not referenced:
        print(f"# {repo_path}: no runtime BWS references — no manifest needed", file=sys.stderr)
        return 0

    enrich: dict[str, dict] = {}
    if not args.no_enrich:
        loaded = load_enrich_map()
        if loaded is None:
            print("# warning: BWS unreachable — emitting UUID-only manifest", file=sys.stderr)
        else:
            enrich = loaded

    toml = manifest.build_manifest(referenced, enrich=enrich)
    if args.write:
        (repo_path / manifest.MANIFEST).write_text(toml)
        print(f"wrote {repo_path / manifest.MANIFEST} ({len(referenced)} secrets)", file=sys.stderr)
    else:
        sys.stdout.write(toml)
    return 0


if __name__ == "__main__":
    sys.exit(main())
