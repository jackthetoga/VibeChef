# 0004. Keep the `hazan.epub` sample cookbook (for now)

- **Status:** Accepted
- **Date:** 2026-07-14

## Context
`backend/hazan-uploads/hazan.epub` (a copyrighted cookbook) and a cover image are committed to
the repo. Committing binary/copyrighted content is normally a smell — it bloats history and
raises licensing questions. But it is also a genuinely useful end-to-end ingestion fixture,
and today this is a **private, self-hosted** tool used for books we personally own.

## Decision
**Keep it for now.** Do not rewrite git history to remove it. Separately, make sure *real*
runtime user uploads can never be committed by accident (gitignore the upload directories).

## Alternatives considered
- **Remove it from history immediately (filter-repo/BFG).** Rejected as premature: history
  rewriting is disruptive (coordinated force-push) and the personal-use case is defensible.
- **Replace with a public-domain sample now.** Deferred: worth doing, but not urgent while the
  repo is private and the file is a helpful fixture.

## Consequences
- We keep a realistic ingestion fixture with zero extra work.
- The repo carries a copyrighted blob in history. That is fine for private personal use but
  **must be revisited before any public deploy or public repo** — redistributing a copyrighted
  EPUB is a different legal question. This ADR is the reminder so it isn't forgotten.
- Follow-up: gitignore `backend/uploads/` and any generated `*-uploads/` so user data stays out
  of version control.
