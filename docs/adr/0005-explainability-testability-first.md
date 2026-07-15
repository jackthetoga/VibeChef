# 0005. Explainability & testability are the top priority

- **Status:** Accepted
- **Date:** 2026-07-14

## Context
This codebase will be built largely with AI assistance. The characteristic failure mode of
that workflow is not *bad* code — it's *plausible* code produced faster than anyone
understands it. Volume outruns comprehension; silent gaps accumulate; eventually the system is
a "jenga tower" nobody can safely change, forcing a full re-understand/refactor. We want to
structurally prevent that.

## Decision
Make **explainability** and **testability** the primary constraints on how we work — above
raw velocity:

1. **Tests as the executable spec.** Test *behavior at boundaries* (API contracts, ingestion
   parsing, the `missing_count` SQL), not implementation details. Before refactoring existing
   or AI-written code, add a characterization/contract test that pins current behavior first.
2. **The "why" lives in the repo.** Major decisions get an ADR; every PR states Why + the
   alternative rejected + how to verify (enforced by the PR template).
3. **Small, single-purpose PRs.** A diff too big to understand gets rubber-stamped.
4. **Boring over clever.** Legible code beats clever code, which is unexplainable later.
5. **CI is the ratchet.** It enforces the bar so discipline doesn't rely on willpower.

## Alternatives considered
- **Move fast, refactor later.** Rejected: "later" is exactly the unrefactorable state we're
  trying to avoid; the cost is paid at 10x during an emergency instead of 1x now.
- **Mandate 100% coverage + an ADR per change.** Rejected: over-application is its own slop —
  implementation-coupled tests break on every refactor, and ADR-per-commit trains people to
  ignore ADRs. We scope "major" deliberately (see `docs/adr/README.md`) and test behavior,
  not getters.

## Consequences
- The first pass on a feature is slower (writing tests + reasoning). That is the intended
  trade: predictable small cost now vs. an unpredictable large cost later.
- Concrete downstream effects: contract-changing work (e.g. de-duplicating API fields) becomes
  test-first; new integrations (storage, events) get a documented seam and boundary tests;
  coverage reporting gets added to CI (reporting first, a floor only once it's earned).
- The current weak spot is explicit: the frontend has ~3 test files for ~3.5k LOC. Closing
  that gap is prioritized over cosmetic work.
