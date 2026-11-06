# Task 4 findings: Notification emails via MCP

Workflow step 1: findings, decisions and assumptions. No code yet. Measured on `output/enron.db` + `duplicates_report.csv` after Task 3.

**Spec (ASSIGNMENT.md §4 Task 4, §5, §7):**
- **§4.2:** "**For each duplicate group**, send a notification email to the sender of the **latest** (duplicate) email". There's a fixed template: To, `Subject: [Duplicate Notice] Re: <original_subject>`, `Date: <current_timestamp>`, `References: <message_id_of_latest_duplicate>`, plus a body with both Message-IDs, both dates, the subject and the similarity %.
- **§5:** a single command runs the pipeline end to end, and **"Email sending requires --send-live flag"**.
- **§7 deliverables:**
  - `output/replies/`: "draft reply .eml files for **all flagged duplicates** (dry-run output)"
  - `output/send_log.csv`: "all emails sent in live mode: timestamp, recipient, subject, status, error"
- **§4.3:** an MCP integration section in AI_USAGE.md, with a screenshot or log of at least one live send.
- **CLAUDE.md:** handle auth errors and rate limits; keep keys in environment variables.

---

## What I found

### 1. One notice per group vs one per flagged email: the spec conflicts with itself

| Source | Unit | Count |
| --- | --- | --- |
| §4.2 notification logic | one per **group** (to the latest duplicate's sender) | **4,558** |
| §7 deliverable `output/replies/` | one draft per **flagged duplicate** | **10,675** |

Both can be met: drafts for every flagged email, live sends for one target per group (D47).

### 2. Who the targets are

The target is the latest duplicate of each group, by (date, source_file) (D39).

| Targets (4,558) | Count |
| --- | --- |
| Same timestamp as the original (folder copies) | 4,169 |
| Later than the original | 389 |
| … of which likely export copies (D45) | 248 |
| … **real re-sends** (later, not an export copy) | **141** (from 86 distinct senders) |

The 141 real re-send targets by recipient overlap (D46): 100 → 70 · 50–<100 → 27 · >0–<50 → 10 · 0 → 34.

Top real re-send targets (overlap 100, score ~100), e.g.:
- `ypoforumsurvey@…` "Your online YPO forum survey"
- `ccox@businesscouncil.com` "October 01 Meeting Minutes" (Nov 5 → Nov 6, 2001)
- `ipayit@enron.com` "Action Requested: Past Due Invoice" (Mar 7 → Mar 8, 2002)
- `steven.kean@enron.com` "California's dim bulbs"

These look like genuine repeats sent to the same people.

### 3. Gmail limits make "send all 4,558" impossible

- Gmail personal accounts can send roughly **500 emails a day** over SMTP. New or low-reputation accounts can be throttled earlier.
- Exceeding the limit gives `550 5.4.5 Daily user sending quota exceeded`, and the account can be locked for up to 24 h.
- All live sends go to **one inbox** (`NOTIFY_TO`), so even 500 would flood it and look like spam.
- **So the live run needs a small cap and a selection rule** (D49, D50). The dry run still produces every draft.

### 4. The Enron addresses are dead

All targets are `@enron.com` or 2000–2002 external addresses. The spec itself says to send "to an email address (preferably your own gmail account)". `.env` already has `NOTIFY_TO` (I checked only the variable **names**, not values). The live run must **always** send to `NOTIFY_TO`, never to the original sender (D51).

### 5. The MCP server's `send_email` tool (`mcp_server/gmail_server.py`)

- **Arguments:** `to`, `subject`, `body`, `references` (optional). Sends via Gmail SMTP_SSL :465 with `GMAIL_USER` / `GMAIL_APP_PASSWORD` from `.env`.
- **It sets these headers itself:** `From` = `GMAIL_USER`, `Date` = now (UTC), `Message-ID` = `<…@dedup.local>`. When `references` is given, it sets **both** `References` and `In-Reply-To` to it.
- **It has no error handling:**
  - a wrong password raises `SMTPAuthenticationError (535)`
  - the quota raises `SMTPDataError/SMTPSenderRefused (550 5.4.5)`
  - network problems raise timeouts

  The MCP client sees each of these as a **tool error** (`result.isError = True`, with the exception text). The **pipeline** must classify them and react (D55).
- **It can't add custom headers,** so an "originally to" note can only go in the body or the send log.

### 6. The template, applied to real data

- **Doubled prefixes:** **1,456 of 4,558** target subjects already start with `Re:`/`Fw:`, so `[Duplicate Notice] Re: <original_subject>` would give `Re: Re: …` or `Re: FW: …`.
- **Blank subjects:** **321** targets have a blank subject, giving `[Duplicate Notice] Re: ` with nothing after it (D52).
- **"Date Sent" format:** the stored dates are UTC ISO (`2001-05-01T00:11:00+00:00`); the template doesn't say which format to use (D53).
- **Score:** "Similarity Score: <similarity_percentage>%" uses `similarity_score`, which is the **full-text** score (D41), e.g. `100.00%`.

### 7. How the pipeline can call MCP

The installed `mcp==1.30.0` has the client side: `mcp.ClientSession`, `mcp.StdioServerParameters`, `mcp.client.stdio.stdio_client`. A Python script can **start `gmail_server.py` as a subprocess over stdio** (the same way Claude Code does via `.mcp.json`) and call `send_email` with `session.call_tool(...)`. It's async (`asyncio`). The live test send at setup was made *by Claude Code*; the pipeline needs its own client so that `--send-live` works without Claude.

### 8. Re-run safety needs care

- Task 2/3 already protect rows with `notification_sent = 1` (D30, D40). Task 4 is what *sets* `notification_sent` and `notification_date`.
- A re-run must **never send a second notice** for the same target.
- The send log must keep history (append, not overwrite).

### 9. Out of scope (known limitation)
The template asks the recipient to "reply with CONFIRM to restore it to active status". Reading replies and restoring rows isn't in the deliverables. I'll document it, not build it.

---

## Decisions for me

### D47. Drafts vs live sends (the spec conflict)
- (a) Drafts **and** live sends per group only (4,558)
- (b) **Drafts for every flagged duplicate** (10,675, as §7 says), each filled with *that* email's own fields (its sender, Message-ID, date, score, original). Live sends only for **one target per group** (§4.2), and only the selected ones (D50).
- (c) Drafts per group + a separate per-duplicate listing

**Recommendation: (b).** It meets both parts of the spec literally, and the draft for each group's target is exactly what would be sent live.

### D48. Committing 10,675 `.eml` files
- (a) Commit them all (it's a named deliverable): about 10,675 files, ~12–15 MB
- (b) Git-ignore `output/replies/`, commit a small sample folder (as D23), and regenerate with one command
- (c) Commit them as one zip

**Recommendation: (a)**, because the deliverables list names `output/replies/` explicitly. If the size worries you, (b) with the regenerate command in the README.

### D49. Live-send cap
- (a) `--max-sends N`, **default 10**, hard maximum 100 per run (config); refuse more without editing the config
- (b) Default 50
- (c) No cap

**Recommendation: (a).** 10 is enough to prove live sends work and fill `send_log.csv`. It stays far below Gmail's ~500/day, and it won't flood my inbox. Re-runs continue from where the last run stopped, because sent targets are skipped (D54).

### D50. Which targets are sent live, in what order
- (a) **Real re-sends only** (141): later than the original, not `likely_export_copy`. Ordered by `recipient_overlap` ↓, then `similarity_score` ↓, then duplicate date ↑. A high overlap means the same people got it twice: the clearest accidental repeat.
- (b) All 4,558 targets in group order
- (c) (a), then fall back to export copies and folder copies once the 141 are used up

**Recommendation: (a).** Live sends should demonstrate the most meaningful notices. Folder copies aren't re-sends (D39, D45). All targets still get a draft (D47).

### D51. Recipient override
- (a) **Live: `To` is always `NOTIFY_TO`**; the run **refuses** if it's unset. Drafts (`.eml`): `To` = the real sender (the template is followed exactly). `send_log.csv` adds an `intended_recipient` column.
- (b) As (a), plus a first body line "Originally addressed to: <sender>"
- (c) Send to the real sender (dead addresses; could reach real people today)

**Recommendation: (a).** The template body stays exact, and the log records who it was meant for. (c) is ruled out.

### D52. Subject line
- (a) Literal: `[Duplicate Notice] Re: <original_subject>` (gives `Re: Re: …` in 1,456 targets, and `Re: ` alone for 321 blank subjects)
- (b) **Strip existing reply prefixes from the original subject first** (the D35 regex), then add one `Re: `. Blank subject → `[Duplicate Notice] Re: (no subject)`.

**Recommendation: (b).** It reads correctly and is still recognisably the template. The body's `Subject:` line keeps the original subject exactly as it was.

### D53. Draft `.eml` format
- **Built with** Python's `email.message.EmailMessage`. Headers:
  - `From: Email Deduplication System <dedup@localhost>` (config; drafts aren't sent)
  - `To:` the sender (D51)
  - `Subject:` per D52
  - `Date:` current time in RFC 2822, UTC
  - `Message-ID:` new, `@dedup.local`
  - **`References:` and `In-Reply-To:`** = the flagged email's Message-ID, so a mail client threads it under that email (matching what the server does for live sends)
  - `Content-Type: text/plain; charset=utf-8`
- **Body:** the §4.2 template exactly. "Date Sent" uses the stored UTC value, written as `2001-05-01 00:11:00 UTC`; the score as `100.00%`.
- **File name:** the Message-ID without `<>`, plus `.eml` (e.g. `12846475.1075854481614.JavaMail.evans@thyme.eml`). It's unique, and it's easy to find the draft for any report row.

**Recommendation:** as stated. Alternatives: a numeric file name (`00001.eml`), or ISO dates in the body.

### D54. Re-run safety
- Drafts are rebuilt on every run: the folder is cleared first, so drafts for un-flagged emails don't linger. Only the `Date:`/`Message-ID:` headers change between runs.
- Live:
  - only targets with `notification_sent = 0` are eligible
  - after a **confirmed** send, set `notification_sent = 1` and `notification_date` (UTC now) in the same step as the log row
  - a failed send changes nothing in the DB and logs `status = failed` with the error
- `send_log.csv` is **append-only**, with columns `timestamp, recipient, subject, status, error` (spec) + `intended_recipient, duplicate_message_id`.
- Combined with D30/D40, a notified row is never wiped by the loader or Task 3, and `--rebuild` is refused.

**Recommendation:** as stated.

### D55. How the pipeline calls MCP, and error handling
- (a) **A Python MCP client over stdio:** `src/notify.py` starts `mcp_server/gmail_server.py` with the project's Python (the same command as `.mcp.json`), opens **one** `ClientSession` per run, and calls `send_email` once per selected target, sequentially, with a pause between sends (`SEND_DELAY_SECONDS = 2`, config). Error handling:
  - **auth failure** (`535` / `SMTPAuthenticationError`) → **stop the run**
  - **quota / rate limit** (`5.4.5`, `421`, "quota") → **stop**; the remaining targets stay unsent
  - **transient** (timeout, connection) → **retry up to 3 times** with backoff (2, 4, 8 s)
  - anything else → log `failed`, continue

  Every outcome goes in `send_log.csv`.
- (b) Have Claude Code send each notice as a tool call (not reproducible; no `--send-live` flag)
- (c) Call SMTP directly from Python (bypasses MCP, which defeats Task 4)

**Recommendation: (a).** The same server Claude Code uses, called by the pipeline. The Claude Code test send from setup stays as the §4.3 "via the AI tool" evidence.

### D56. Commands
- (a) `src/notify.py`: **dry run by default** (drafts only, no network, no DB writes); `--send-live [--max-sends N]` sends. Plus a top-level `main.py` that runs parse → load → dedup → notify (dry run unless `--send-live`), for the §5 "single command".
- (b) Only `main.py`

**Recommendation: (a).** Each step can be run and explained on its own, and `main.py` is a thin wrapper.

---

## Assumptions
- **Target** = the latest duplicate of each group, by (date, source_file) (D39). `notification_sent` and `notification_date` are set on **that** row.
- **`.env` access:** `NOTIFY_TO`, `GMAIL_USER` and `GMAIL_APP_PASSWORD` are read from the environment (loaded by `python-dotenv`, already pinned). The pipeline never prints them.
- **Dry runs** make no network calls and don't touch the DB.
- **CONFIRM replies** are out of scope (a known limitation).
- **D43** (sender-alias report) comes after Task 4 works.
- **One live send already exists** (the setup test, Claude Code → Gmail, screenshot in `docs/mcp_test_send.png`). The pipeline's first live run adds `send_log.csv` evidence.

---

## Steps 1–3: targets, notice builder, dry run

**What I did:** `src/notify.py`.
- `read_notices()` reads every flagged duplicate (reusing `detect_duplicates.read_flagged_pairs()`, which already computes `same_timestamp`, `likely_export_copy` and `recipient_overlap`) and marks each group's **target**: the latest by (date, source_file), D39.
- `notice_subject()` (D52), `build_body()` (the §4.2 template) and `build_message()` (D53 headers) build each notice.
- `safe_filename()` turns a Message-ID into a file name; `write_drafts()` clears `output/replies/*.eml`, checks the names are unique, and writes each draft.
- The dry run is the default: no network, no DB writes. `--send-live` refuses ("not built yet").

**Counts:**

| | Count |
| --- | --- |
| Flagged duplicates → drafts written | **10,675** |
| Groups (targets) | 4,558 |
| Live-eligible real re-send targets (D50) | **141** |
| Already notified | 0 |
| **Total draft size** (content bytes) | **11.7 MB** (42 MB on disk) → **D48: commit all** |
| Run time | about 12 s |

**Checks on all 10,675 drafts:**
- every draft parses with Python's `email` parser
- `References` = `In-Reply-To` = a `duplicate_message_id` in the report
- file name = `safe_filename(References)`, with no collisions
- every subject starts `[Duplicate Notice] Re: `, with 0 doubled prefixes; 1,070 use `(no subject)`
- all `text/plain; charset=utf-8`
- the DB MD5 is unchanged

**Three drafts read by eye:**

| Case | File (`output/replies/…`) | To | Subject | Score |
| --- | --- | --- | --- | --- |
| A. folder copy | `23185873.1075840090105.JavaMail.evans_at_thyme.eml` | `jan_levine@travisintl.com` | `[Duplicate Notice] Re: Education Survey` | 100.00% (both dates 1998-01-06 01:32:00 UTC) |
| B. real re-send target | `18685648.1075861576356.JavaMail.evans_at_thyme.eml` | `ccox@businesscouncil.com` | `[Duplicate Notice] Re: October 01 Meeting Minutes` | 100.00% (Nov 5 18:16 → Nov 6 15:58 UTC) |
| C. blank subject, later | `19095595.1075857757440.JavaMail.evans_at_thyme.eml` | `john.lavorato@enron.com` | `[Duplicate Notice] Re: (no subject)` | 99.84% (2000-01-03 → 2000-01-17) |

Full draft B:

```
From: Email Deduplication System <dedup@localhost>
To: ccox@businesscouncil.com
Subject: [Duplicate Notice] Re: October 01 Meeting Minutes
Date: Fri, 06 Nov 2026 02:35:07 +0000
Message-ID: <179393250735.16659.15327528686534525734@dedup.local>
References: <18685648.1075861576356.JavaMail.evans@thyme>
In-Reply-To: <18685648.1075861576356.JavaMail.evans@thyme>
Content-Type: text/plain; charset="utf-8"

This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  <18685648.1075861576356.JavaMail.evans@thyme>
    Date Sent:   2001-11-06 15:58:24 UTC
    Subject:     October 01 Meeting Minutes

  Original Email on Record:
    Message-ID:  <31820720.1075862884882.JavaMail.evans@thyme>
    Date Sent:   2001-11-05 18:16:04 UTC

  Similarity Score: 100.00%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
```

**Unexpected / not sure:**
1. **Template spacing:** ASSIGNMENT.md shows a blank line after every template line (an artifact of document conversion). I used the evident structure: blank lines between sections, none within.
2. **A blank subject in the body:** the body's `Subject:` line keeps the original exactly (empty), and only the header uses `(no subject)` (D52). Draft C shows this.
3. **Drafts change on every run:** `Date:` is "current timestamp" per the spec, and `Message-ID:` is new each time, so a re-run modifies all 10,675 files in git. Plan: commit the drafts **once, from the final run**.
4. **`Date:` reads 2026-11-06,** because it's the current time in UTC. Locally it's still Nov 5 evening.

---

## Steps 4–6: selection, MCP client, send log (built); live preview, **no sends yet**

**What I did:** added `select_live_targets()` + `--preview`, the MCP client (`send_live()`, `call_send_email()` with retries, `classify_error()`), `append_send_log()` and `mark_notified()` to `src/notify.py`. `NOTIFY_TO` is read by the program at run time and never printed. The live path stays unexercised until the D45 amendment is decided.

**Checks:** `--preview` leaves the DB unchanged (MD5) and creates no `send_log.csv`; `--max-sends 500` → refused (D49).

**Preview as built (D45 = exact 100), top 10 of 141:** three entries are probable export copies (#7 +5 h + 1 s, #9 +9 h, #10 +12 h; all Notes/Outlook pairs scoring 99.8–99.98). D45 misses them because it requires exactly 100.

**D45 amendment options** (measured):

| Rule | Export copies (of 696 later) | Real re-sends | Live-eligible targets |
| --- | --- | --- | --- |
| (a) score = 100, exact whole hours (as built) | 254 | 442 | 141 |
| (b) score ≥ 99, exact whole hours | 265 | 431 | 131 |
| (c) score ≥ 99, within 60 s of whole hours (1–24 h) | 280 | 416 | **118** |

**Preview under (c), top 10** (overlap, score, sender, original → duplicate):

| # | Overlap | Score | Sender | Original → duplicate | Subject |
| --- | --- | --- | --- | --- | --- |
| 1 | 100 | 100.00 | ypoforumsurvey@ypoforumdiagnosticsurvey.com | 2001-08-20 15:29:43 → 15:29:51 | Your online YPO forum survey |
| 2 | 100 | 100.00 | john@pgsenergy.com | 2001-09-23 17:45:07 → 17:45:08 | Last PGS Seminars Until October |
| 3 | 100 | 100.00 | georgette@hawkespeers.com | 2001-07-18 → 2001-10-17 | Hawkes Peers & Co. |
| 4 | 100 | 100.00 | fatimapr@softcom.ca | 2001-10-26 21:56 → 22:28 | RALLY AGAINT TERRORISM |
| 5 | 100 | 100.00 | ccox@businesscouncil.com | 2001-11-05 18:16 → 11-06 15:58 | October 01 Meeting Minutes |
| 6 | 100 | 100.00 | ipayit@enron.com | 2002-03-07 08:05:07 → 03-08 08:05:02 | Action Requested: Past Due Invoice |
| 7 | 100 | 99.96 | public.relations@enron.com | 2000-10-05 18:11 → 18:32 | Enron Image 2000 Video is Here |
| 8 | 100 | 99.77 | doctorbonner@altavista.com | 2002-01-30 17:51:16 → 17:51:18 | Demand Ken Lay Donate Proceeds… |
| 9 | 100 | 99.71 | kenneth.thibodeaux@enron.com | 2001-05-21 17:57 → 18:07 | RE: 5/18/01 Gas Violations FINAL |
| 10 | 100 | 99.65 | skinnerj@central.edu | 2002-01-30 17:45:01 → 17:45:03 | Demand Ken Lay Donate Proceeds… |

**Decision pending.** The first live send uses `--max-sends 1` (target #1 of whichever list is chosen), so you can check your inbox before the rest.

---

## Step 7: Live run

**Send 1:** `python src/notify.py --send-live --max-sends 1` → the YPO forum survey notice (8-second double delivery). **Verified by me in Gmail** (`docs/live_send_proof.png`): subject, body and score 100.00% correct; `send_log.csv` and the DB agree to the second (03:33:39 UTC).

**Changes before the rest:**
- **D57:** live `From` = "Email Deduplication System <my Gmail>" (the screenshot showed only the bare address).
- **D58:** a total live budget of 10, counted from the DB, so a re-run can send 0.

**Sends 2–10:** 9 sent, 0 failed, about 1 s apart, all to `NOTIFY_TO`.

| # | Intended sender | Subject |
| --- | --- | --- |
| 1 | ypoforumsurvey@ypoforumdiagnosticsurvey.com | Your online YPO forum survey -- complete in 3 easy steps! |
| 2 | john@pgsenergy.com | Last PGS Seminars Until October |
| 3 | georgette@hawkespeers.com | Hawkes Peers & Co. |
| 4 | fatimapr@softcom.ca | RALLY AGAINT TERRORISM |
| 5 | ccox@businesscouncil.com | October 01 Meeting Minutes |
| 6 | ipayit@enron.com | Action Requested: Past Due Invoice for User: |
| 7 | public.relations@enron.com | Enron Image 2000 Video is Here |
| 8 | doctorbonner@altavista.com | Demand Ken Lay Donate Proceeds from Enron Stock Sales |
| 9 | kenneth.thibodeaux@enron.com | RE: 5/18/01 Gas Violations FINAL |
| 10 | skinnerj@central.edu | Demand Ken Lay Donate Proceeds from Enron Stock Sales |

**Proof of re-run safety:**

| Check | Result |
| --- | --- |
| Re-run `--send-live` | "10 of 10 already sent; 0 left … **0 emails sent**" ✔ |
| `send_log.csv` | 10 rows, all `sent`, 10 distinct targets; each matches its DB `notification_date` to the second ✔ |
| `python src/load_db.py` | 0 inserted / 0 stale; the 10 notified rows byte-identical ✔ |
| `python src/detect_duplicates.py` | 0 conflicts; notified rows byte-identical ✔ |
| `python src/load_db.py --rebuild` | **REFUSED** (10 emails have `notification_sent = 1`) ✔ |

**Unexpected / not sure:**
1. **The cap was per run** (D49), so "re-run sends 0" needed a total budget (D58). Added and flagged before any further sends.
2. **Server log lines:** the MCP server prints "Processing request of type CallToolRequest" to stderr for each call. That's harmless; it comes from the `mcp` library.
