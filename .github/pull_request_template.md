<!--
Keep PRs small and single-purpose. A diff too big to understand gets rubber-stamped —
that is how the "slop jenga tower" gets built. If this PR does two things, split it.
-->

## What
<!-- One or two sentences. What changes and where. -->

## Why (and what you rejected)
<!--
The reasoning is the part that evaporates if it isn't written down. State the problem,
the approach, and at least one alternative you considered and why you didn't take it.
For a *major* decision (schema/contract change, new dependency, auth, a cross-cutting
pattern, anything hard to reverse) add an ADR under docs/adr/ and link it here.
-->

## How to verify
<!-- Exact commands or steps a reviewer runs to see it works. Not "trust me". -->

## Test plan
<!--
What behavior is now pinned by a test, and where. If this changes existing behavior,
say which test would have caught a regression. "No tests because ___" is a valid answer
only for docs/config-only changes — say so explicitly.
-->

## Checklist
- [ ] Small and single-purpose
- [ ] Tests cover the new/changed **behavior** (not implementation details)
- [ ] `make check` passes locally (or CI is green)
- [ ] Major decision? → ADR added and linked above
- [ ] No secrets, no committed user data, no absolute paths
