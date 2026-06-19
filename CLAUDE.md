<!-- governance:start -->
## Security & Governance

<!-- Generated from governance-map.toml in security-standards. Do not hand-edit. -->
<!-- Regenerate: cd ~/Projects/security-standards && make sync -->

**Build-agent class:** tool-home — you open this repo to *develop* its tools.
**Lane:** detect (detect / mutate / approve).
**Gating scope:** *approve* (change-manager) gates the **autonomous** 4am drift executor only; an **interactive** session reaches infraops mutation tools directly — guardrail-gated (`permissions.deny` + high-power-gate hook + audit log), not approval-gated.
**Owns:** `security_scan (python package)`, `security-scan.sh`, `skills-security-scan.sh`, `bws-write-guard.sh`, `bws-read-guard.sh`, `bws-scan-gate.sh`.
**Deploy:** `make install`  •  **Verify:** `make verify`.
**Consumers:** security-standards, infraops-mcp-server, change-manager.
<!-- governance:end -->
