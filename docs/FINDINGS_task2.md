# Task 2 findings: Database storage

Workflow step 1: findings, decisions and assumptions. No code yet. Decisions are made by me and recorded in DECISIONS.md once answered.

**Spec (ASSIGNMENT.md §4 Task 2, §5, §7):**
- SQLite (preferred) or local PostgreSQL. Schema provided as `schema.sql`, which must include `is_duplicate`, `duplicate_of`, `notification_sent` and `notification_date`.
- Normalised: to/cc/bcc addresses in a related table, not comma-separated strings.
- A unique constraint on `message_id`.
- Indexes on `date`, `from_address`, `subject`.
- At least 3 sample queries in `sample_queries.sql`, with expected output descriptions.

**My extra requirements:**
- The schema must also hold Task 3/4 state: `similarity_score`.
- The load must be **safe to re-run**.

---

## What I found (measured on `output/parsed_emails.jsonl`, 20,339 records)

### Volume

| Item | Count |
| --- | --- |
| Emails to load | 20,339 |
| To rows | 131,818 |
| Cc rows | 29,613 |
| Bcc rows | 29,613 (identical to Cc, D7) |
| **Total recipient rows** | **191,044** |
| Distinct addresses (from + to + cc + bcc) | 13,390 (**includes senders**) |
| **Distinct recipient addresses** (what the `addresses` table holds) | **11,146** (confirmed by the full load) |
| Distinct senders | 3,429 |
| Emails with Cc (and so Bcc) | 5,471 |

So 191,044 recipient rows (190,390 after D29) point at only **11,146** distinct recipient addresses, about 17 uses each. *(Correction: I first wrote 13,390 here. That counted senders too, but senders are a text column on `emails`, not rows in `addresses`.)*

### Things that affect the schema

1. **Message-IDs are unique** across all 20,339 (verified in Task 1). The unique constraint won't reject anything on the first load. It matters for re-runs, and for showing the constraint works.
2. **The same address repeats inside one list:**
   - in **185** emails' `To` (426 extra rows)
   - in **59** emails' `Cc`, with the same in `Bcc` (114 extra rows each)

   A primary key of (email, address, type) would reject the repeats, so I need a rule (D29).
3. **The same address in both To and Cc:** 179 emails. Fine if the recipient type is part of the key.
4. **The sender is in their own To list:** 738 emails. Nothing to fix; I mention it because "emails received by X" queries will count these.
5. **Dates** are all the same 25-character UTC ISO format (`2001-05-14T23:39:00+00:00`), from `1998-01-06` to `2002-03-12`. Stored as TEXT, they sort chronologically, and SQLite's date functions read them directly.
6. **Longest values:**

   | Field | Max length (chars) |
   | --- | --- |
   | `message_id` | 45 |
   | `subject` | 198 |
   | `from_address` | 53 |
   | `body` | 32,298 |
   | `quoted_content` | 40,444 |
   | `x_to` | 68,065 |

   SQLite TEXT has no length limit, so none of these is a problem.
7. **Re-running is risky for Task 4.** If a re-run resets `notification_sent`, a later live run could email the same people again. Re-run safety has to protect Task 3/4 state, not only avoid duplicate rows (D30).
8. **Tools:** Python's built-in `sqlite3` works (SQLite 3.51.2, which supports `INSERT … ON CONFLICT DO UPDATE`). **pandas is not installed.** CLAUDE.md says to prefer plain pandas, but adding it needs your approval (D32).
9. **`*.db` is already git-ignored**, so the database file won't be committed. `schema.sql` and `sample_queries.sql` will be.

### Noticed for Task 3 (not a Task 2 decision)

- **The same person sometimes has several addresses**, e.g. `john.lavorato@enron.com` (2,299 sent) and `lavorato@enron.com` (401). Task 3's duplicate rule requires the *same* `from_address`, so copies sent from different aliases won't group. Worth a decision in Task 3.
- 5,819 subjects start with `Re:`/`Fw:`/`Fwd:`. Task 3 must normalise these. That can be computed in Python, so the schema doesn't need a column for it.

---

## Decisions for me

### D25. Database engine
- (a) **SQLite** (spec's preference; one file; built into Python)
- (b) local PostgreSQL (needs a server, `psycopg`, and setup for reviewers)

**Recommendation: (a).**

### D26. How to normalise addresses
- (a) `emails` + `recipients(email_id, address, recipient_type)`: the address is stored as text in each recipient row.
- (b) `emails` + `addresses(id, address UNIQUE)` + `email_recipients(email_id, address_id, recipient_type)`: each address is stored once and recipients point to it. `from_address` stays as a text column on `emails`, because it's a spec field with a required index.
- (c) like (b), but `from_address` also becomes an `address_id` foreign key.

**Recommendation: (b).** It's the textbook normalised design (191,044 rows pointing at 13,390 addresses) and still simple to load: insert the address if new, then look up its id. (c) is the most normalised, but it changes the spec's `from_address` field into an id. Every sender query would then need a join, and the required index would sit on an id instead of the address.

### D27. Primary key for `emails`
- (a) an integer `id` primary key + `message_id TEXT UNIQUE NOT NULL`
- (b) `message_id` as the primary key

**Recommendation: (a).** Recipient rows reference a small integer instead of a 45-character string. The unique constraint on `message_id` is still there, as the spec requires.

### D28. Task 3/4 columns
- (a) on the `emails` table:
  - `is_duplicate INTEGER NOT NULL DEFAULT 0`
  - `duplicate_of TEXT REFERENCES emails(message_id)`
  - `similarity_score REAL`
  - `notification_sent INTEGER NOT NULL DEFAULT 0`
  - `notification_date TEXT`
- (b) separate `duplicates` and `notifications` tables

**Recommendation: (a).** The spec's `schema.sql` deliverable names these columns, and Task 3 says to set `is_duplicate` / `duplicate_of` *on the email*. `similarity_score` is the flagged email's score against its original (NULL otherwise). Booleans are stored as 0/1 because SQLite has no boolean type.

### D29. The same address repeated within one list (To: 185 emails / 426 rows; Cc and Bcc: 59 emails / 114 rows each)
- (a) keep one row per (email, address, type); the key is `PRIMARY KEY (email_id, address_id, recipient_type)`
- (b) keep every repeat, with a `position` column in the key

**Recommendation: (a).** Being listed twice in To doesn't make someone a recipient twice. I'll count and log the rows skipped.

### D30. Making the load safe to re-run
- (a) **Delete and rebuild** the database every run. Simple, but it **wipes Task 3/4 state** (`notification_sent`), so a later `--send-live` could re-send emails.
- (b) **`INSERT OR IGNORE`**: existing emails are skipped. Safe, but a parser fix would never reach rows already loaded.
- (c) **Upsert**: `INSERT … ON CONFLICT(message_id) DO UPDATE` refreshes the parsed fields but **never touches** the five Task 3/4 columns. Each email's recipient rows are deleted and re-inserted in the same transaction.

**Recommendation: (c),** plus an explicit `--rebuild` flag for a clean start. `--rebuild` would **refuse** if any `notification_sent = 1`, so state can't be wiped by accident. The loader reports how many emails were inserted vs updated, so a second run shows 0 inserted and 20,339 updated. If the database has emails that are no longer in the JSONL (for example, after a parser change made them fail), the loader reports the count but doesn't delete them, because they may carry Task 3/4 state.

### D31. Date storage
- (a) TEXT, ISO-8601 UTC, as the parser outputs it (`2001-05-14T23:39:00+00:00`)
- (b) INTEGER Unix seconds

**Recommendation: (a).** It's readable in query output, sorts correctly because every value has the same format and zone, works with SQLite date functions, and the `date` index serves range queries.

### D32. Loading library
- (a) Python's built-in **`sqlite3`** with plain SQL
- (b) pandas `to_sql`: not installed, so it would be a new library to approve, and it can't express the upsert or the address lookup table cleanly
- (c) SQLAlchemy: a new library, and more than this task needs

**Recommendation: (a).** There's no new dependency, and the SQL in the loader matches `schema.sql` line for line, which makes it easy to explain. CLAUDE.md's "prefer pandas" is about data manipulation; there's none here.

### D33. Store failed parses in the database?
- (a) No: `error_log.txt` is the spec's deliverable for failures.
- (b) Also add a `parse_failures(source_file, reason)` table.

**Recommendation: (a)** for now. (b) is a nice-to-have if you want failures queryable.

### D34. Sample queries (at least 3, with expected output descriptions)
Proposed set:
1. **Emails per sender**: top 10 senders by count (expected top row: `david.delainey@enron.com`, 2,961).
2. **Emails in a date range**: e.g. October 2001 (the month Enron's collapse began), as a count and a sample list.
3. **Emails with CC recipients**: count (expected 5,471) and a sample with their Cc lists, which shows the join through `email_recipients`.
4. **All recipients of one email, by type**: shows the normalised tables at work.
5. **The unique constraint**: a plain `INSERT` of an existing `message_id` fails with `UNIQUE constraint failed`.

**Recommendation:** all five. Queries 1–3 are the spec's own examples; 4–5 prove the normalisation and the constraint.

---

## Assumptions (tell me if any are wrong)

- **File layout:**
  - `schema.sql` and `sample_queries.sql` at the repo root (deliverables)
  - the loader in `src/load_db.py`
  - the database at `output/enron.db` (git-ignored via `*.db`)
- **Input:** the loader reads `output/parsed_emails.jsonl`. It doesn't re-parse the raw files.
- **Schema is applied with `CREATE TABLE IF NOT EXISTS`,** so applying it is also re-runnable.
- **Foreign keys are switched on** (`PRAGMA foreign_keys = ON`); SQLite leaves them off by default.
- **One transaction for the whole load,** so a crash leaves the database unchanged rather than half-loaded.
- **`recipient_type`** is one of `to`, `cc`, `bcc`, enforced with a `CHECK` constraint.
- **Indexes:**
  - the three the spec requires: `date`, `from_address`, `subject`
  - plus `email_recipients(address_id)` for "emails received by X"
  - plus `emails(is_duplicate)` for Tasks 3/4
- **Other fields:** `headings`, `forwarded_content` and `quoted_content` are TEXT columns on `emails`. Optional fields that are NULL in the JSONL stay NULL.
- **No `mailbox` column:** it can be derived from `source_file` in a query if needed.

## Proposed schema sketch (for discussion, not final)

```
emails ─────────────────────────────┐        addresses
  id INTEGER PK                     │          id INTEGER PK
  message_id TEXT UNIQUE NOT NULL   │          address TEXT UNIQUE NOT NULL
  date TEXT NOT NULL      [index]   │               ▲
  from_address TEXT NOT NULL [index]│               │
  subject TEXT NOT NULL   [index]   │        email_recipients
  body, forwarded_content,          └──────►   email_id    → emails.id
    quoted_content, headings TEXT              address_id  → addresses.id   [index]
  x_from … x_origin, content_type TEXT         recipient_type 'to'|'cc'|'bcc'
  source_file TEXT NOT NULL                    PK (email_id, address_id, recipient_type)
  has_attachment INTEGER (0/1)
  -- Task 3/4 state (never overwritten by a re-load):
  is_duplicate INTEGER DEFAULT 0
  duplicate_of TEXT → emails.message_id
  similarity_score REAL
  notification_sent INTEGER DEFAULT 0
  notification_date TEXT
```

---

## Steps 1–3: schema.sql + src/load_db.py

**What I did:**
- `schema.sql`: three tables, `IF NOT EXISTS` throughout, `CHECK` constraints on the 0/1 flags and `recipient_type`, and 6 indexes (3 required by the spec + 3 extra).
- `src/load_db.py`, in order:
  1. apply the schema
  2. upsert each email on `message_id`, updating only the parsed columns
  3. look up each address's id, inserting it if new
  4. replace each email's recipient rows (repeats skipped by the primary key)
  5. handle stale emails as D30 says
- Everything happens in one transaction. `--limit N` loads into `output/sample_run/enron.db`; `--rebuild` deletes the DB first unless a notification has been sent.

**Smoke test (200-record sample):**

| Run | Inserted | Updated | Recipient rows | Repeats skipped | emails / addresses / recipients |
| --- | --- | --- | --- | --- | --- |
| 1st (`--rebuild`) | 200 | 0 | 1,533 | 22 | 200 / 606 / 1,533 |
| 2nd (re-run) | 0 | 200 | 1,533 | 22 | 200 / 606 / 1,533 |

**D30 stale-email cases:** I planted Task 3/4 state in the sample DB, then loaded a 100-record sample, so 100 emails became stale.

| Case | Expected | Result |
| --- | --- | --- |
| 1. stale original, not notified (dup B points to it) | delete it; clear B's flags | deleted ✔; B = (0, NULL, NULL, 0) ✔ |
| 2. stale original; notified D points to it | keep it; D untouched | kept ✔; D = (1, set, 97.0, 1) ✔ |
| 3. stale, notified itself | keep it | kept ✔ |
| 4. live H is a duplicate of live F | flags survive the re-load | (1, set, 99.0, 0) ✔ |
| `--rebuild` with 2 notified rows | refused | "REFUSED…", exit code 1 ✔ |

Run report: 98 stale deleted, 1 duplicate flag cleared, 2 "stale, kept for notification history" (both listed by Message-ID). 0 orphan recipient rows; `PRAGMA foreign_key_check` is clean. The test DB was deleted afterwards.

**Unexpected / not sure:**
1. **`addresses` holds recipient addresses only** (`from_address` is a text column, D26). The full load has **11,146**; the 13,390 figure included senders. Corrected above.
2. **Unused addresses:** *fixed after review.* The cleanup now runs at the end of each load (see step 4).
3. **`duplicate_of` has no `ON DELETE` action, on purpose.** The loader clears pointing rows first; if it ever didn't, the foreign key would refuse the delete instead of silently leaving a dangling reference.

---

## Step 4: Sample load, then full load (run twice)

**Change first:** an unused-address cleanup at the end of every load (in the same transaction), with the count removed reported.

**Expected** (computed independently from the JSONL): 20,339 emails · 191,044 raw recipient rows → **190,390** after D29 (654 repeats) · **11,146** distinct recipient addresses.

| Run | DB | Before (emails / addresses / recipients) | Inserted | Updated | Recipient rows | Repeats skipped | Stale deleted | Unused addresses removed | After (emails / addresses / recipients) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sample `--limit 200 --rebuild` | sample | (none) | 200 | 0 | 1,533 | 22 | 0 | 0 | 200 / 606 / 1,533 |
| sample re-run | sample | 200 / 606 / 1,533 | 0 | 200 | 1,533 | 22 | 0 | 0 | 200 / 606 / 1,533 |
| sample `--limit 100` (cleanup test) | sample | 200 / 606 / 1,533 | 0 | 100 | 724 | 22 | 100 | **263** | 100 / 343 / 724 |
| **full, 1st load** | `output/enron.db` | (no DB) | **20,339** | 0 | **190,390** | **654** | 0 | 0 | **20,339 / 11,146 / 190,390** |
| **full, 2nd load (re-run)** | `output/enron.db` | 20,339 / 11,146 / 190,390 | **0** | **20,339** | 190,390 | 654 | 0 | 0 | 20,339 / 11,146 / 190,390 |

All counts match the expected values exactly. A full load takes about 2.5–2.8 s; the DB is 61 MB (git-ignored).

**Checks on the full DB:**
- `PRAGMA integrity_check` = ok; `PRAGMA foreign_key_check` = 0 rows
- all 6 indexes present; a date-range query uses `idx_emails_date` (`EXPLAIN QUERY PLAN`)
- recipients by type: to 131,392 · cc 29,499 · bcc 29,499 (Bcc = Cc, D7)
- Task 3/4 columns all at their defaults: 0 duplicates, 0 notified, 0 `duplicate_of`
- unused addresses: 0
- the sample DB used for the cleanup test was deleted afterwards

**Unexpected / not sure:** nothing. The one correction is the address count: 11,146 recipient addresses, not 13,390 (which included senders). Fixed in this file and in D26.

---

## Step 5: sample_queries.sql

**What I did:** wrote 6 queries (D34) and ran them on the full DB with the `sqlite3` CLI. Each query's real output is in its "Expected output" comment. Subjects are cut to 30–50 characters so the column display doesn't wrap.

| # | Query | Result on the full DB |
| --- | --- | --- |
| 1 | Emails per sender, top 10 | `david.delainey@enron.com` 2,961 · `john.lavorato@enron.com` 2,299 · `rosalee.fleming@enron.com` 904 · … · `leonardo.pacheco@enron.com` 177 |
| 2 | Emails in October 2001 | **650**, plus the first 5 by time (05:27 UTC Oct 1 "Internet", …) |
| 3 | Emails with Cc | **5,471** (= the parser's `cc_addresses` completeness), plus 5 samples with Cc lists |
| 4 | Recipients of `skilling-j/inbox/1533.` | 1 to (`jeff.skilling@`) · 4 cc · 4 bcc (same as cc, D7) |
| 5 | Insert an existing `message_id` | **`UNIQUE constraint failed: emails.message_id`**; count stays 1 |
| 6 | Duplicate groups | no rows yet (filled after Task 3) |

**Checks:** the DB's MD5 is the same before and after running the whole script, so Q5's failed insert wrote nothing.

**Unexpected / not sure:**
1. **The CLI exits with code 1** because Q5 fails on purpose. Documented at the top of the file. If a grader runs it in a script that stops on errors, Q6 is still reached, because the CLI continues past errors by default.
2. **Q3 shows a real duplicate:** its first three rows are one email (1998-01-06, "Education Survey") stored in three folders. That's a preview of Task 3.
3. **Q1 shows the alias issue:** `john.lavorato@` (2,299) and `lavorato@` (401) appear separately, which is the Task 3 limitation already noted in PLAN.md.
4. **Changed my Q4 example:** the first email I picked had only To recipients, so I switched to one with To, Cc and Bcc.
