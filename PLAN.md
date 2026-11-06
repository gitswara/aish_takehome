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
6. [x] **N** Query 6 (duplicate groups): real output filled in after Task 3 (4,558 groups; top 10 listed).
7. [x] **N** pytest: upsert keeps Task 3/4 state; recipients are replaced; a stale row is deleted, but kept if notified; the unique constraint rejects a plain duplicate INSERT. Done: 7 tests in `tests/test_load_db.py` (15 in total with the parser tests); 3 mutation checks catch broken rules.

After each step: update PLAN.md, DECISIONS.md and ARCHITECTURE.md, and append the step report to `docs/FINDINGS_task2.md`.

**Stale originals (D30, decided):** delete the stale email and clear the flags of duplicates pointing to it. But **keep** it if it was notified itself or a notified email points to it ("stale, kept for notification history").

## Task 3: Duplicate detection (`src/detect_duplicates.py`)

Decisions D35–D44 (all decided). Findings in `docs/FINDINGS_task3.md`.

1. [x] **M** Read candidates from `output/enron.db`: build blocks of (`from_address`, normalised subject) (D35); full text with whitespace collapsed (D36). Config block at the top: `SIMILARITY_THRESHOLD = 90`, scorer `fuzz.ratio` (D37, D41).
2. [x] **M** Group within each block, oldest first by (date, source_file), anchored to each group's original (D38, D39 tie-break), plus the D44 body gate (both bodies empty → pass; one empty → fail; else body ≥ 90). Every flagged email records its score against its original. *Done: 4,558 groups / 10,675 flagged (as estimated); lowest score 90.08.*
3. [x] **M** Write flags in one transaction (D40):
   - clear Task 3 columns on non-notified rows
   - set `is_duplicate = 1`, `duplicate_of`, `similarity_score` on every non-original
   - never change notified rows; report conflicts
4. [x] **M** `duplicates_report.csv` (repo root): the 7 spec columns + `same_timestamp`, one row per flagged email (D39, D42).
5. [x] **M** Stats, printed and saved to `output/dedup_stats.json` (*done: 4,558 groups / 10,675 flagged / avg 3.34; re-run identical*):
   - groups, emails flagged, average group size
   - folder copies vs later repeats; score bands
   - the latest duplicate per group (= Task 4 targets)
6. [x] **M** Run: `--limit` first (writes to `output/sample_run/`), then the full DB. Check against the estimates (about 4,537 groups / 10,768 flagged, or ~4,558 / ~10,675 with D44). **Run twice:** same flags; notified rows untouched. Spot-check about 5 groups by hand: **at least** a folder-copy group (`same_timestamp`), a later re-send, and a template false positive (Delainey "Approval for reviewer"), plus a 90–95 near match and a blank-subject block. **List their Message-IDs and source files so I can check one myself.** *Done: 6 groups; 11 rows re-scored from the raw files, all match. New finding → D45 (open).*
7. [x] **M** Fill query 6's real output in `sample_queries.sql` (Task 2 step 6). Done.
8. [x] **N** pytest: subject normalisation; anchor grouping (no flagged score below 90); tie-break; D44 empty-body rule; notified rows untouched on re-run. *Done: 8 tests + D45/D46 tests; 23 total pass; mutation-checked.*
9. [ ] **N** D43 alias report: **only after Task 4 works.** Sender aliases (e.g. `john.lavorato@enron.com` 2,299 sent vs `lavorato@enron.com` 401) won't group under the spec's same-`from_address` rule. Follow the spec, document it, and count the groups that would merge if aliases were combined, without changing flags.

After each step: update PLAN.md, DECISIONS.md and ARCHITECTURE.md, and append the step report to `docs/FINDINGS_task3.md`.

**Heads-up for Task 4:** one notification per group means about 4,537 emails, but Gmail allows roughly 500 sends a day from a personal account. The live run will need a cap.

## Later tasks (planned when I get there)

- Task 4: Draft `.eml` replies + live send via MCP, to my Gmail only
- README.md and AI_USAGE.md, written at the end. README must say: `output/parsed_emails.jsonl` is git-ignored (D23); regenerate it with `python src/parse_emails.py`; a committed 18-record sample is in `output/sample_parsed_emails.jsonl`. **Known limitations to list:** the duplicate rule ignores recipients, so a mass announcement sent in batches to different people (case B, OWA notice: 15 vs 88 recipients, overlap 0) counts as a duplicate (see `recipient_overlap`, D46); template emails ("Approval for reviewer") pass 90%; sender aliases don't group (D43); export copies with shifted clocks (D45). Quote the **parsed** attachment count: **1,149** of 20,339 parsed emails have `has_attachment = true` (1,336 across all processed files). `--limit N` writes to `output/sample_run/` (D24).
