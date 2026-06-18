<!-- governance:start -->
## Security & Governance

<!-- Generated from governance-map.toml in security-standards. Do not hand-edit. -->
<!-- Regenerate: cd ~/Projects/security-standards && make sync -->

**Build-agent class:** tool-home — you open this repo to *develop* its tools.
**Lane:** detect (detect / mutate / approve).
**Owns:** `security_scan (python package)`, `security-scan.sh`, `skills-security-scan.sh`, `bws-write-guard.sh`, `bws-read-guard.sh`, `bws-scan-gate.sh`.
**Deploy:** `make install`  •  **Verify:** `make verify`.
**Consumers:** security-standards, infraops-mcp-server, change-manager.
<!-- governance:end -->
