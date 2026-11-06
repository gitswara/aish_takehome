# Architecture

Inputs → scripts → outputs. (Pipeline sections get added as I build each step.)

## Pipeline (Task 1, planned)

```
data/maildir/{lay-k,skilling-j,whalley-l,lavorato-j,delainey-d}/**   (read-only, 21,662 files)
        │
        ▼
 src/parse_emails.py [--limit N] ── discover files → read bytes, CRLF→LF, decode cp1252, QP if declared, fix \x01, → ' → header fields (UTC dates, lenient address lists) → body split (strip D17 block, cut at first marker) → has_attachment (filename patterns) → mandatory-field check (fail → error_log.txt) → email parser → fields → body split → checks
        │
        ├──► output/parsed_emails.jsonl      one parsed email per line (input to Task 2); 51 MB, git-ignored
        ├──► output/sample_parsed_emails.jsonl  18-record sample, committed (D23)
        ├──► error_log.txt                   path <TAB> reason, one failed file per line
        └──► output/extraction_stats.json    totals, failures by reason, completeness % per field
```

**Regenerating the JSONL:** `output/parsed_emails.jsonl` is git-ignored because it's 51 MB (D23). To rebuild it, run `python src/parse_emails.py` from the project root with the `.venv` active and the Enron data in `data/maildir/`. It takes about 11 seconds. A full run (no `--limit`) also refreshes the committed sample.

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
