# Plan

Status: `[ ]` todo · `[x]` done. **M** = must-have, **N** = nice-to-have (cut first if time runs short). This is a ~24-hour take-home, so I'm doing the N steps too, after the M steps.

## Task 1: Parser (`src/parse_emails.py`)

1. [x] **M** Discover files: walk the 5 mailboxes and count them (expect 21,662). Done: found 21,662. `--limit N` picks an evenly spread sample (D15).
2. [x] **M** Read each file safely: bytes → normalise CRLF to LF → parse with `email`. Decode quoted-printable only when it's declared (D13). Read non-ASCII as Windows-1252. Wrap each file in try/except so one bad file never stops the run. Done: 21,662 of 21,662 read, 0 errors, 924 QP decoded. Open question: `\x01` artifacts (D16).
3. [x] **M** Header fields (done: 21,662 processed, 0 errors; D17 and D18 added):
   - `message_id`
   - `date` → UTC; fail on the 1979 placeholder (D6)
   - `from_address`; fail if it isn't a real address (D14)
   - `to_addresses` / `cc_addresses` / `bcc_addresses` as lowercased lists; fail if there's no `To` (D4); Bcc stored as given (D7)
   - `subject`: unfolded, `""` allowed (D5)
   - `x_from`, `x_to`, `x_cc`, `x_bcc`, `x_folder`, `x_origin`, `content_type`
   - `source_file`
4. [x] **M** Body split: cut at the first marker into `body` / `forwarded_content` / `quoted_content` (D8). Done: 6 marker types incl. the two-line Notes form; 12 D17 blocks stripped. Open: D19 (`>` rule), D20 (24-hour Notes dates).
5. [x] **M** `has_attachment` from filename patterns (D10). Done: 1,336 true with the D21 default (body + forwarded). Open: D21 scope.
6. [x] **M** Mandatory-field check → `error_log.txt` (`path<TAB>reason`). Done: 20,339 parsed / 1,323 failed, as predicted. D22 decided (b): fail only if all text fields are empty.
7. [x] **M** Write `output/parsed_emails.jsonl`, one email per line (D12). Done: 20,339 records, 19 fields (+ `headings` in step 10), 51 MB, git-ignored. A committed 18-record sample is in `output/sample_parsed_emails.jsonl` (D23).
8. [x] **M** Stats: files found, parsed, failed (by reason), and completeness % per field. Printed and saved to `output/extraction_stats.json`. Done: completeness is reported over all processed files and over parsed OK; subject shown as header present (100%) and non-blank (92.8%).
9. [x] **M** Run on all 21,662 files, check the counts against DECISIONS.md, and spot-check about 10 records by hand. Fill in the *(at run)* counts. Done: 17/17 count checks ✔, no text lost in 20,339 records, 10/10 spot-checks ✔.
10. [x] **N** `headings`: ALL-CAPS and numbered section lines, primary body only (D11). Done: 1,354 parsed emails have headings; ~60–70% precision on a hand check of 30 lines.
11. [x] **N** pytest: 5–8 small cases on parser edge cases: nested forward, D17 Notes block, D19 single `>` not a quote, missing To → failure, placeholder date → failure. Done: 8 tests in `tests/test_parse_emails.py`, all pass (`pytest -q`); 3 mutation checks confirm they catch broken rules.

After each step: update PLAN.md, DECISIONS.md (counts) and ARCHITECTURE.md, and append the step report to `docs/FINDINGS_task1.md`.

## Task 2: Database (`schema.sql`, `src/load_db.py`, `sample_queries.sql`)

Decisions D25–D34. Findings in `docs/FINDINGS_task2.md`.

1. [x] **M** `schema.sql`:
   - tables `emails`, `addresses`, `email_recipients` (D26, D27), with the Task 3/4 columns on `emails` (D28)
   - `UNIQUE(message_id)`; `CHECK` on `recipient_type`
   - foreign keys
   - indexes on `date`, `from_address`, `subject` (spec), plus `email_recipients(address_id)` and `emails(is_duplicate)`
   - every statement `IF NOT EXISTS`
2. [x] **M** `src/load_db.py`, the load itself:
   - read the JSONL and apply `schema.sql`
   - upsert emails without touching Task 3/4 columns (D30)
   - insert addresses if new and look up their ids
   - delete + re-insert each email's recipients, skipping repeats (D29)
   - one transaction; config block at the top
3. [x] **M** Re-run safety (D30), *tested on the sample DB: all 4 stale/notified cases and the `--rebuild` guard behave as decided*:
   - report emails in the DB but not in the JSONL; delete them unless `notification_sent = 1` (keep and report those)
   - `--rebuild` refuses if any notification has been sent
   - run report: inserted / updated / deleted / kept / recipient rows / repeats skipped
4. [x] **M** Load all 20,339 (`--limit` first, to a separate DB file as in D24). Check row counts: emails 20,339; addresses 13,390; recipients 191,044 minus repeats. **Run it twice** and confirm the second run gives 0 inserted / 20,339 updated, with Task 3/4 columns unchanged. *Done: 20,339 / 11,146 / 190,390; re-run 0 inserted / 20,339 updated; integrity + FK checks clean.*
5. [x] **M** `sample_queries.sql`: queries 1–5 with their real outputs written into the expected-output comments (D34). Done; the DB is unchanged after running it (MD5).
6. [~] **N** Query 6 (duplicate groups): written now (returns no rows yet); **fill its real output after Task 3.**
7. [ ] **N** pytest: upsert keeps Task 3/4 state; recipients are replaced; a stale row is deleted, but kept if notified; the unique constraint rejects a plain duplicate INSERT.

After each step: update PLAN.md, DECISIONS.md and ARCHITECTURE.md, and append the step report to `docs/FINDINGS_task2.md`.

**Stale originals (D30, decided):** delete the stale email and clear the flags of duplicates pointing to it. But **keep** it if it was notified itself or a notified email points to it ("stale, kept for notification history").

## Later tasks (planned when I get there)

- Task 3: Duplicate detection (similarity on the full text, D9) + `duplicates_report.csv`
  - **Sender aliases (found in Task 2):** the same person can have several addresses, e.g. `john.lavorato@enron.com` (2,299 sent) and `lavorato@enron.com` (401). The spec's rule needs the *same* `from_address`, so copies sent from different aliases won't group. **Plan:** follow the spec exactly and document this limitation. **If time allows (N):** report how many duplicate groups would merge if aliases were combined, without changing any flags.
- Task 4: Draft `.eml` replies + live send via MCP, to my Gmail only
- README.md and AI_USAGE.md, written at the end. README must say: `output/parsed_emails.jsonl` is git-ignored (D23); regenerate it with `python src/parse_emails.py`; a committed 18-record sample is in `output/sample_parsed_emails.jsonl`. Quote the **parsed** attachment count: **1,149** of 20,339 parsed emails have `has_attachment = true` (1,336 across all processed files). `--limit N` writes to `output/sample_run/` (D24).
