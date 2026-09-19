# Per-record audit notes (ADR-P4)

One file per id, `{id}.json`, `sort_keys=True` — the same shape as `raw/deep_captures/`, so a worker can
own a record end to end without ever writing a shared file. `raw/audit_notes.json` is kept (emptied, not
deleted) so an older checkout still builds; `audit_projects.load_notes()` merges this directory over it,
and this directory wins.

Keys the sheet renders: `worth`, `worth_note`, `what_to_steal`, `what_breaks_first`, `prior_art`,
`clone_cost{estimate,why,assumptions[]}`.

Keys that are never rendered: `hazard_note` (required *only* when a hazard class attaches, and published
as that stamp's line — see `capture_lint.py`'s `notes.hazard-note-when-stamped`) and `hazard_note_absent`
(the reasoning for why a *near-miss* is not a hazard, kept so the next reader does not re-litigate it).
