# Question: is `lane-credential-policy` only the event actor, or also the approver?

## Question

The handoff's description brief says the id "appears only as the `actor` on that `package.approved`
event and the policy approver." The code shows it can be the actor and can't be the approver. Do you
accept the PR's wording, or did you mean something else?

## What the code shows

I read these at intent-packages `origin/main` `636ceacb` and orchestrator `origin/main` `4852e0b0`,
read only:

- **The ledger approver can't be this id.** `verify_approval` (`operations.py`, around line 550)
  accepts a ledger approver only through `_is_recognised_approver`. That function accepts a human
  operator, meaning `registry.is_human_operator`, which needs `authority_profile: human-operator-v1`.
  It also accepts a string matching `POLICY_APPROVER_RE` (`^policy:<profile>@v<N>$`,
  `approval_policy.py:68`). This id has `none-v1`, and its shape can't match the regex. Recorded as
  the approver, it fails `verify-approval`.
- **`approve --by-policy` computes the approver.** In `cli.py` `_run_approve`, the approver is
  `load_policy().approver_for(profile)`, a `policy:…@v<N>` string.
- **The event actor is separate.** It comes from `FACTORY_AGENT_ID` (`emitter.py:92`; the default is
  `claude-code-interactive`).
- **The orchestrator matches the approval on evidence, not on the actor.** `package_sources.py`
  `_matching_event_evidence` and `work_carrier/standing.py` `_verified_approval` match the event's
  evidence `approver` against that `policy:` string. Neither reads the event's `actor`.

## What the PR says

PR #89 (`ebfc165`) opens with "The actor recorded when…". The handoff said "The approver recorded…".
The PR also says the id "appears only as the `actor` on that `package.approved` event, beside the
`policy:<profile>@v<N>` approver its evidence carries." This wording matches D-38 A as quoted in the
handoff ("the `package.approved` event names a new registry agent").

## Options

- **A: Accept the PR's wording.** The PR stays as it is, and I mark the report done.
- **B: Restore the handoff's wording verbatim.** I revert `ebfc165`. "Policy approver" would then
  mean an approver that this id isn't in the ledger.
- **C: Something else.** For example, the id is meant to become an approver, which would need an
  intent-packages change. Tell me what you want, and I'll stop for it.

## State

All checks pass, and the PR is open and ready. The report's outcome stays `blocked` until you answer.
