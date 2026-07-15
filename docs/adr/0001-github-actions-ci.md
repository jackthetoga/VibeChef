# 0001. Use GitHub Actions CI mirroring `make check`

- **Status:** Accepted
- **Date:** 2026-07-14

## Context
The repo had no CI. `make check` already defined the intended quality bar (ruff, pytest,
oxlint, vitest, vite build) but nothing ran it automatically, so a change could land red.
This project is explicitly a practice run in reviewing and trusting AI-assisted code — that
trust requires an automated gate, not discipline alone.

## Decision
Add `.github/workflows/ci.yml` that runs on every PR and every push to `main`, mirroring
`make check`, in three jobs: **backend** (`ruff` + `pytest`), **frontend** (`oxlint` +
`vitest` + `vite build`), and **migrations** (spin up a Postgres service and run
`alembic upgrade head`). Once stable, enable branch protection requiring these checks before
merge.

## Alternatives considered
- **No CI, rely on `make check` locally.** Rejected: humans forget, and the whole point is a
  gate that doesn't depend on remembering.
- **Run pytest against Postgres too.** Rejected for now: the suite uses in-memory SQLite via
  `create_all` (see `conftest.py`), which is fast and matches how tests are written. But that
  means tests never exercise the Alembic chain — so we added the separate `migrations` job to
  cover exactly that gap.
- **A single mega-job.** Rejected: separate jobs parallelize and make failures legible (you
  see *which* layer broke at a glance).

## Consequences
- Every PR gets an automated verdict; broken migrations are caught even though unit tests use
  SQLite.
- CI was red on arrival due to pre-existing lint (see ADR-0005's companion lint fix) — that is
  CI doing its job, not a workflow bug.
- Frontend and backend test *depth* are not enforced yet (only pass/fail). Coverage reporting
  is a follow-up; a hard coverage floor is intentionally deferred to avoid gaming.
