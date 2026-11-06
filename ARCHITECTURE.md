# Architecture

Inputs → scripts → outputs.

**One command:** `python main.py` runs parse → load → dedupe → notify (dry run). Options: `--preview`, `--send-live [--max-sends N]`. About 38 s end to end. Each step can also be run on its own (`python src/<step>.py`).

## Pipeline (Task 1, planned)

```
data/maildir/{lay-k,skilling-j,whalley-l,lavorato-j,delainey-d}/**   (read-only, 21,662 files)
        │
        ▼
 src/parse_emails.py [--limit N] ── discover files → read bytes, CRLF→LF, decode cp1252, QP if declared, fix \x01, → ' → header fields (UTC dates, lenient address lists) → body split (strip D17 block, cut at first marker) → has_attachment (filename patterns) → headings (primary body) → mandatory-field check (fail → error_log.txt) → email parser → fields → body split → checks
        │
        ├──► output/parsed_emails.jsonl      one parsed email per line (input to Task 2); 51 MB, git-ignored
        ├──► output/sample_parsed_emails.jsonl  18-record sample, committed (D23)
        ├──► error_log.txt                   path <TAB> reason, one failed file per line
        └──► output/extraction_stats.json    totals, failures by reason, split markers, completeness % per field
                                             (over all processed files AND over parsed OK)
```

**Sample runs:** `python src/parse_emails.py --limit 200` writes its three outputs to `output/sample_run/` (git-ignored, D24). It never touches `error_log.txt`, `output/parsed_emails.jsonl` or `output/extraction_stats.json`.

**Regenerating the JSONL:** `output/parsed_emails.jsonl` is git-ignored because it's 51 MB (D23). To rebuild it, run `python src/parse_emails.py` from the project root with the `.venv` active and the Enron data in `data/maildir/`. It takes about 11 seconds. A full run (no `--limit`) also refreshes the committed sample.

## Database (Task 2: D25–D34; schema + loader built)

```
output/parsed_emails.jsonl ──► src/load_db.py ──► output/enron.db (SQLite, git-ignored)
                                   │  applies schema.sql (IF NOT EXISTS)
                                   │  upsert emails ON CONFLICT(message_id): parsed fields only
                                   │  addresses: insert if new → id
                                   │  email_recipients: delete + re-insert per email
                                   └─ stale rows: delete unless notification_sent = 1

emails (id PK, message_id UNIQUE, date, from_address, subject, …,
        is_duplicate, duplicate_of → emails.message_id, similarity_score,
        notification_sent, notification_date)
  └──< email_recipients (email_id, address_id, recipient_type to|cc|bcc) >── addresses (id, address UNIQUE)

sample_queries.sql: 6 queries run against output/enron.db
```

**Why `duplicate_of` has a foreign key but no `ON DELETE` rule:** it's a safety net. Before deleting a stale original, the loader clears every row that points to it (D30). If a future bug skipped that step, SQLite would **refuse the delete** with a foreign-key error instead of silently leaving a duplicate pointing at an email that no longer exists. Foreign keys are switched on for every connection (`PRAGMA foreign_keys = ON`).

**Run:** `python src/load_db.py` (about 3 s, safe to re-run). `--limit N` loads into `output/sample_run/enron.db`; `--rebuild` starts fresh unless a notification has been sent. `output/enron.db` is 61 MB and git-ignored (`*.db`).

## Duplicate detection (Task 3: D35–D44; steps 1–5 built)

```
output/enron.db ──► src/detect_duplicates.py
                     1. load emails; full text (body+fwd+quoted) and body, whitespace collapsed
                     2. blocks: (from_address, subject without Re/Fw/Fwd, lowercased); keep blocks of 2+
                     3. each block oldest first by (date, source_file)
                     4. each email vs each group's ORIGINAL: full text ≥ 90 AND body gate → join, else new group
                     5. write flags (1 transaction; notified rows never changed)
                     6. read flagged pairs back FROM THE DB, add same_timestamp (D39),
                        likely_export_copy (D45), recipient_overlap (D46)
                                                            ──► duplicates_report.csv (repo root)
                                                            └─► output/dedup_stats.json (+ printed)
```

**Run:** `python src/detect_duplicates.py` (about 4 s; re-runnable with identical results). `--limit N` is a print-only preview of N blocks.

## Notifications (Task 4: D47–D56; dry run built)

```
output/enron.db ──► src/notify.py (dry run by default)
                     1. flagged pairs (reuses detect_duplicates.read_flagged_pairs) + each group's target
                     2. notice: §4.2 template body · subject per D52 · References/In-Reply-To = flagged Message-ID
                     3. output/replies/<safe Message-ID>.eml × 10,675 (To = original sender; never sent)
                     --preview: list live targets (sends nothing)
                     --send-live: real re-send targets (D50), ≤ --max-sends per run, ≤ 10 in total (D58)
                       → MCP client (stdio) → mcp_server/gmail_server.py → send_email(to=NOTIFY_TO)
                       → output/send_log.csv (append) + notification_sent / notification_date
```

**Tests:** `pytest -q` runs 15 tests in about 0.1 s, with no Enron data needed:
- `tests/test_parse_emails.py` (8): each writes a small fake email and calls `parse_file()`, the same per-file function `main()` uses.
- `tests/test_load_db.py` (7): each builds a temporary SQLite DB from synthetic records and calls the loader's own functions.

The input files are never modified. Decisions are D4–D14 in DECISIONS.md.

---

## MCP server (Gmail notifications)

```
 Claude Code ──(stdio, MCP)──► mcp_server/gmail_server.py ──(SMTP_SSL :465)──► smtp.gmail.com ──► NOTIFY_TO inbox
      ▲                               │
      │                               └─ reads GMAIL_USER / GMAIL_APP_PASSWORD from .env (not committed)
  .mcp.json (project scope, not committed)
  mcp_config.json.example (committed template, placeholder paths)
```

- **What it is:** a small, separate process that exposes one tool, `send_email(to, subject, body, references)`. It has no knowledge of the dedup pipeline.
- **How it's launched:** Claude Code starts it via `.mcp.json` using the project's `.venv/bin/python` and talks to it over stdin/stdout (stdio transport).
- **How it fits in:** the pipeline writes its results (and drafted replies in `output/replies/`) to disk. Claude Code then calls `send_email` to send live notifications. Because the original Enron addresses are dead, they go to `NOTIFY_TO`. Setting `references` to the original Message-ID makes the email thread as a reply.
- **Secrets:** they only ever live in `.env`, which the server loads itself. `.mcp.json` and the example config contain no credentials.
