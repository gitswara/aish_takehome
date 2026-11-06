# Enron email deduplication pipeline

I parse a subset of the Enron email dataset, store it in SQLite, find duplicate emails, and send duplicate notices through a Gmail MCP server. One command runs everything: `python main.py`.

## Results at a glance

```
21,662 email files (5 mailboxes)
 ├── 1,323 failed a mandatory field ──► error_log.txt
 │      1,293 no To · 23 placeholder date · 5 both · 2 invalid From
 └── 20,339 parsed ──► output/enron.db
        │
        ▼  same sender + same subject (Re:/Fw: removed) + ≥ 90% similar text
     4,558 duplicate groups · 10,675 emails flagged
     (average group size 3.34: the original plus 2.34 duplicates)
        ├── 9,979 folder copies       same email filed in several folders, same timestamp
        └──   696 later than their original
                ├── 280 export copies  same email from two exports (Notes/Outlook), clock shifted by whole hours
                └── 416 real re-sends
                      │
                      ▼  one notice per group, to the latest duplicate
                    118 groups whose latest duplicate is a real re-send (live-eligible)
                      │
                      ▼  capped (10 in total)
                     10 live notices sent via MCP ──► output/send_log.csv
   + 10,675 draft notices (.eml), one per flagged email ──► output/replies/
```

Re-runs are safe. Each run reports how many rows it wrote ("rows flagged this run"). On a re-run that number is **10,665, not 10,675**: the 10 emails that already got a live notice are never rewritten (D40). The total flagged stays 10,675.

## What it does

| Step | Script | What it does |
| --- | --- | --- |
| 1. Parse | `src/parse_emails.py` | Reads the raw files and extracts the spec's fields (dates in UTC; To/Cc/Bcc as lists). Splits each body into the sender's own text, forwarded content and quoted replies. Detects attachments and headings. Logs failures. |
| 2. Load | `src/load_db.py` | Loads the parsed emails into SQLite. Addresses go in their own table. Safe to re-run: it updates in place and never overwrites duplicate or notification state. |
| 3. Dedupe | `src/detect_duplicates.py` | Groups duplicates (oldest email = original), flags the rest, and writes `duplicates_report.csv` and stats. |
| 4. Notify | `src/notify.py` | Writes a draft notice for every flagged email. With `--send-live`, sends notices through the Gmail MCP server (`mcp_server/gmail_server.py`) to my own inbox. |

## Setup

See [SETUP.md](SETUP.md): dataset download, mailbox extraction, Python environment, Gmail App Password, MCP server registration. In short: Python 3.13, `pip install -r requirements.txt` (exact versions in `requirements-lock.txt`), and a `.env` with `GMAIL_USER`, `GMAIL_APP_PASSWORD` and `NOTIFY_TO`. The `.env` file is never committed.

## How to run

```bash
source .venv/bin/activate
python main.py                          # full pipeline, dry run: drafts only, nothing sent (~38 s)
python main.py --preview                # also list the notices that would be sent live (sends nothing)
python main.py --send-live              # send up to 10 notices this run, to NOTIFY_TO only
python main.py --send-live --max-sends 1
pytest -q                               # 23 tests, no Enron data needed
```

- **Dry run is the default.** Live sends need `--send-live`. They always go to `NOTIFY_TO`, never to the original (dead) Enron addresses. They're limited to 10 per run and 10 in total, and a notice is never sent twice for the same email.
- Each step can be run on its own, e.g. `python src/detect_duplicates.py`. Add `--limit N` to try a quick sample: parse and load write to `output/sample_run/`, and dedupe prints only.
- `python src/load_db.py --rebuild` starts the database fresh. It refuses once any notice has been sent, so notification history can't be wiped.

## Outputs

| File | What it is | In git? |
| --- | --- | --- |
| `error_log.txt` | every failed file and its reason(s) | yes |
| `output/parsed_emails.jsonl` | all 20,339 parsed emails, one JSON per line (51 MB) | no, regenerate with `python main.py` |
| `output/sample_parsed_emails.jsonl` | 18-email sample of the above | yes |
| `output/extraction_stats.json` | parse totals, failure reasons, completeness per field | yes |
| `schema.sql` | database schema (includes `is_duplicate`, `duplicate_of`, `similarity_score`, `notification_sent`, `notification_date`) | yes |
| `output/enron.db` | the SQLite database (61 MB) | no |
| `sample_queries.sql` | 6 example queries with their expected output: `sqlite3 output/enron.db < sample_queries.sql` | yes |
| `duplicates_report.csv` | one row per flagged email: the 7 spec columns + `same_timestamp`, `likely_export_copy`, `recipient_overlap` | yes |
| `output/dedup_stats.json` | groups, flagged, average group size, splits and score bands | yes |
| `output/replies/` | 10,675 draft notices (`.eml`), one per flagged email | yes |
| `output/send_log.csv` | every live send: timestamp, recipient, subject, status, error (+ intended recipient) | yes |
| `mcp_config.json.example` | MCP server config template with placeholder paths (no credentials) | yes |
| `docs/` | step-by-step findings per task, plus screenshots of a draft and a live send | yes |

## MCP integration

- **Server:** my own small FastMCP server, `mcp_server/gmail_server.py`, with one tool: `send_email(to, subject, body, references)`. It sends through Gmail SMTP with an App Password read from `.env`.
- **Why custom instead of an existing Gmail MCP server:**
  - Setup is just a Gmail App Password, with no Google Cloud project or OAuth consent screen.
  - I control the headers. `references` sets both `References` and `In-Reply-To` to the flagged email's Message-ID, as the notice template requires, and `From` shows "Email Deduplication System".
- **Two ways it's used:**
  - **Claude Code** uses it as a tool, registered with `claude mcp add` in project scope.
  - **The pipeline** uses it as an **MCP client over stdio**: `src/notify.py` starts the server as a subprocess, opens one MCP session, and calls `send_email` for each notice. That's how `--send-live` works without Claude.
- **Config:** `mcp_config.json.example` shows the structure (command + args, placeholder paths). Credentials stay in `.env`, which is never committed.
- **Proof of a live send:** [docs/live_send_proof.png](docs/live_send_proof.png), the first notice as it arrived in my Gmail. All 10 sends are in `output/send_log.csv`. Setup steps and issues are in [AI_USAGE.md](AI_USAGE.md).

## Mailbox choice (D3)

I used **`lay-k`, `skilling-j`, `whalley-l`, `lavorato-j`, `delainey-d`**: 21,662 emails. These senior executives wrote to each other, so the same messages appear across their mailboxes and folders. That gives duplicate detection realistic cross-mailbox cases (one verified duplicate runs from Lavorato's mailbox to Skilling's). About 21.7k emails also keeps runs fast while clearing the 10k minimum.

## Known limitations

- **Sender aliases.** The spec's rule needs the *same* `from_address`, so the same person under two addresses doesn't group: `john.lavorato@enron.com` (2,299 sent) and `lavorato@enron.com` (401).
- **Template false positives.** Forms that differ only in a name pass 90%. Example: Delainey's "Approval for reviewer" (the same review form about different employees, 91%) and a "No staff meeting today" notice that matched the regular meeting reminder (90%).
- **Recipients are ignored by the spec's rule.** One flagged pair is the same IT announcement sent to 15 people and later to 88 *different* people: a batch mailing, not an accidental re-send. `recipient_overlap` in the report (0 for that pair) makes these visible, but they're still flagged.
- **Most "duplicates" are folder copies.** 9,979 of 10,675 are the same email filed in several folders with the same timestamp. They follow the spec's definition but aren't re-sends, so live notices only go to real re-sends.
- **Export copies are detected heuristically.** 280 later "duplicates" are the same email from the Lotus Notes and Outlook exports with the clock shifted by whole hours (mostly 12 h). The rule (≥ 99% similar, within 60 s of 1–24 whole hours, one Notes copy + one Outlook copy) is a heuristic.
- **A Notes reply format I don't split.** 5 emails have a Notes reply header with a 24-hour time (`… on 23/01/2001 15:19 CST`); their quoted reply stays in the body (D20).
- **Headings are rough.** On a hand check of 30, about 60–70% were real headings; the rest were names, addresses or list items.
- **Bcc copies Cc.** In this dataset the Bcc header is always an exact copy of Cc (a conversion artifact). I store it as given.
- **Other smaller items:**
  - attachments are detected from filenames in the text only (there are no real attachments in the files)
  - one double-`@` recipient address is dropped
  - "reply CONFIRM to restore" is in the notice template, but replies aren't processed

## How this would scale to 500k emails

- **Parse in parallel.** 500k is about 23× my 21,662 files. Parsing takes about 17 s here, so at 500k it would take roughly 17 s × 23 divided by the number of CPU cores. Each file is parsed independently, so a process pool spreads the work across cores. I'd also stream records to the JSONL instead of holding them all in memory.
- **Load in batches.** Insert with `executemany` in batches of a few thousand. Above a few million rows or with several writers, move to PostgreSQL; the schema is already plain SQL.
- **Dedupe stays mostly cheap** because emails are only compared within the same sender + subject group. The risk is **huge groups**: blank subjects from one sender already reach 865 emails here. For those I'd add a cheaper first pass (exact hash of the text, then MinHash/LSH) so only likely matches get the full fuzzy comparison.
- **Incremental runs.** Only new emails need parsing and comparing against existing group originals; the upsert loader already supports that.
- **Notifications.** Gmail allows about 500 sends a day. At scale I'd use a transactional email service behind the same MCP tool, a send queue, and per-sender batching (one notice per sender listing all their duplicates).

## More detail

- [DECISIONS.md](DECISIONS.md): every decision (D1–D58), the options I considered, and the rows affected
- [ARCHITECTURE.md](ARCHITECTURE.md): inputs → scripts → outputs, schema and data flow
- [AI_USAGE.md](AI_USAGE.md): how I used Claude Code, including MCP setup, prompts, debugging stories and self-corrections
- `docs/FINDINGS_task1.md` … `FINDINGS_task4.md`: what each step found, with counts
