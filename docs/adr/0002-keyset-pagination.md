# 0002. Keyset (cursor) pagination for recipe lists

- **Status:** Accepted (documenting a decision already in the code)
- **Date:** 2026-07-14

## Context
`GET /recipes` (`app/api/routes/recipes.py`) returns a filtered, sorted list that can grow
large per user. The list is sortable by time, calories, protein, missing-ingredient count,
title, and creation date. We need pagination that stays correct and fast regardless of how
deep the user scrolls. (Recording this retroactively — the original author chose keyset; this
ADR captures *why* so it isn't mistaken for an accident.)

## Decision
Use **keyset (cursor) pagination**: order by `(sort_expr, id)` and page with a `WHERE
(sort_expr, id) > (cursor_value, cursor_id)` comparison, returning an opaque `next_cursor`.
The `id` tie-breaker guarantees a total order so rows can't be skipped or duplicated across
pages.

## Alternatives considered
- **Offset/`LIMIT..OFFSET` pagination.** Rejected: `OFFSET n` makes the DB scan and discard
  `n` rows, so deep pages get linearly slower; and rows shifting between requests cause
  skips/duplicates. Fine for tiny lists, wrong for a growing personal library.
- **Client-side pagination (fetch all, slice in JS).** Rejected: defeats the point of pushing
  `missing_count` and filtering into SQL; doesn't scale and wastes bandwidth.

## Consequences
- Stable, index-friendly pagination that stays fast at any depth; pairs with the composite
  indexes on the sort columns.
- No random access to "page 47" — cursors are sequential only. Acceptable for infinite-scroll;
  revisit if we ever need numbered pages.
- Cursor encoding is coupled to the sort key, so adding a sort dimension means updating the
  cursor encode/decode. Keep that logic in one place.
