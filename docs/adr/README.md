# Architecture Decision Records (ADRs)

An ADR captures **one significant decision**: the context, what we decided, and the
consequences — including the options we rejected and why. The code shows *what* the system
does; ADRs preserve *why*, which is exactly the part that evaporates over time (and the part
AI-generated code omits). They are how someone — including future us — re-understands a choice
without reverse-engineering it from the diff.

## When to write one

Write an ADR for a **major** decision:

- a database schema or **API-contract** change,
- adding or removing a **dependency** or external service,
- anything touching **auth / security**,
- a **cross-cutting pattern** other code will copy,
- anything **hard to reverse**.

Do **not** write one for local, easily-reversible changes (a rename, a bug fix, wiring an
existing pattern). ADRs are cheap only if they stay rare — an ADR for every commit trains
everyone to stop reading them.

## How

1. Copy [`0000-template.md`](0000-template.md) to `NNNN-short-kebab-title.md` (next number).
2. Fill it in. Keep it short — a screen, not an essay.
3. Link it from the PR that implements the decision.
4. ADRs are **immutable once merged**. If a decision changes, write a new ADR that supersedes
   the old one (and mark the old one `Superseded by NNNN`). We never rewrite history — an ADR
   is a record of what we believed *at the time*, which is what makes it trustworthy.

## Index

- [0001](0001-github-actions-ci.md) — Use GitHub Actions CI mirroring `make check`
- [0002](0002-keyset-pagination.md) — Keyset (cursor) pagination for recipe lists
- [0003](0003-openai-compatible-llm-provider.md) — LLM via any OpenAI-compatible endpoint
- [0004](0004-keep-sample-cookbook.md) — Keep the `hazan.epub` sample cookbook (for now)
- [0005](0005-explainability-testability-first.md) — Explainability & testability as the top priority
