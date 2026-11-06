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
10. [ ] **N** `headings`: ALL-CAPS and numbered section lines, primary body only (D11). *Not cut: done after 6–9 (24-hour take-home).*
11. [ ] **N** pytest: 5–8 small cases on parser edge cases: nested forward, D17 Notes block, D19 single `>` not a quote, missing To → failure, placeholder date → failure. *Not cut: done after 6–9.*

After each step: update PLAN.md, DECISIONS.md (counts) and ARCHITECTURE.md, and append the step report to `docs/FINDINGS_task1.md`.

## Later tasks (planned when I get there)

- Task 2: SQLite schema + loader from JSONL + sample queries
- Task 3: Duplicate detection (similarity on the full text, D9) + `duplicates_report.csv`
- Task 4: Draft `.eml` replies + live send via MCP, to my Gmail only
- README.md and AI_USAGE.md, written at the end. README must say: `output/parsed_emails.jsonl` is git-ignored (D23); regenerate it with `python src/parse_emails.py`; a committed 18-record sample is in `output/sample_parsed_emails.jsonl`. Quote the **parsed** attachment count: **1,149** of 20,339 parsed emails have `has_attachment = true` (1,336 across all processed files). `--limit N` writes to `output/sample_run/` (D24).
