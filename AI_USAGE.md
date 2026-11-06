# AI Usage

How I used an AI coding tool to build this pipeline: how I prompted it, where it went wrong, what I checked myself, and what I'd do differently.

## 1. Tools used

I used two AI tools, for different jobs:

- **Claude Code** (CLI), model **Claude Opus 5.5**, for **building**. One long session in this repository: data exploration, findings and options, all the pipeline code and tests, running everything, and drafting the design docs.
- **A separate Claude.ai chat** for **planning and review**. It produced:
  - the initial plan and stack
  - `SETUP.md`
  - `mcp_server/gmail_server.py`
  - my `CLAUDE.md` template adapted to this project
  - the assignment converted into `ASSIGNMENT.md`

  It also reviewed Claude Code's findings and recommendations before I answered them.
- **MCP:** a custom Gmail MCP server (`mcp_server/gmail_server.py`), used both by Claude Code (as a tool) and by my pipeline (as an MCP client). See section 3.

## 2. Prompting strategy

**Task by task, never the full spec at once.** My `CLAUDE.md` (my own template, adapted to this project in the planning chat) fixed the working method for every task:

1. **Findings first, no code.** Read the spec section and the data, then give me what you found, the decisions to make (2–3 options each, with a recommendation), and your assumptions. Wait for my answers.
2. **Plan.** Write numbered steps in `PLAN.md`, marked must-have or nice-to-have.
3. **One step at a time.** After each step, report what you did, the row counts before and after, and anything uncertain; then stop.
4. **Ask before deciding** anything that changes results (dropping rows, matching rules, thresholds).
5. **Update the design docs after every step:** `DECISIONS.md` (who decided what, options, rows affected), `ARCHITECTURE.md`, and a `docs/FINDINGS_taskN.md` step report.

**Why this structure:** I have to explain every decision and line to a panel. So the AI proposes and measures, I decide, and every decision is written down with its numbers. That's how `DECISIONS.md` grew to 58 decisions, each with the options, my choice, and the rows affected.

**A second opinion before each decision.** When Claude Code reported findings and recommendations, I pasted them into my planning chat and used it to check the recommendations. Then I made the call and answered Claude Code. Several of the changes I gave Claude Code came out of that review:
- **D4:** rejected the `X-To` fallback for missing `To`; I asked how many it would actually recover (60), then failed them per the spec
- **D16:** fixed only the provable apostrophe case (`\x01,` → `'`), not every garbled character
- **D30:** kept a stale original if a *notified* duplicate points to it, so a sent notice stays traceable
- **D44:** added the primary-body check, so different replies over the same quoted thread aren't duplicates
- **D45:** made the export-copy rule precise (score, whole-hour gap, Notes vs Outlook folders)
- **D46:** added the `recipient_overlap` column
- **D48:** committed the drafts only if under ~25 MB, otherwise as one zip
- **D55:** a ~1 s pause between live sends

### Example prompts I used (lightly cleaned up)

1. **Findings before code**
   > "Start step 1 of the workflow in CLAUDE.md for Task 1: read sections 3 and 4, sample about 50 emails across all five mailboxes and different folders, and walk me through what you found, the decisions we need to make with options and your recommendation, and your assumptions. Don't write any code yet."

   *Why:* it forced a look at real data before design. The 50-email sample plus a full-corpus scan surfaced mixed line endings, the Bcc = Cc artifact, placeholder dates and the fact that most "duplicates" are folder copies, all before a line of pipeline code.

2. **Measure before I decide**
   > "One more decision before building: measure how many of the 10,768 flagged emails pass on full text but would fail if the primary body alone also had to be ≥ 90. If both primary bodies are empty, the body check passes; make that explicit in code. Show me the count and 2–3 examples of emails it would un-flag, then I'll decide."

   *Why:* I wanted numbers and concrete examples, not opinions. Result: 244 emails, e.g. "Spring Business Meeting" at 97.6% on full text but 14.4% on body: different replies over the same quoted thread. That became D44.

3. **Tests that can actually fail**
   > "Add tests/test_detect_duplicates.py with small cases: subject normalisation, the body gate, a chain A≈B, B≈C where A and C are below 90… As in Task 1, break a rule on purpose to show the matching test fails."

   *Why:* tests written by the same AI that wrote the code can pass for the wrong reason. Asking for deliberate breakage proved they test something (section 6).

4. **A safe outward-facing action**
   > "Show me the preview list of live targets before any send, and start the live run with exactly 1 email so I can check my inbox before sending the rest."

   *Why:* sending email can't be undone. The preview caught a rule gap before anything was sent (section 4, story 4).

5. **Prove it's reproducible**
   > "Move the existing database and generated outputs aside (don't delete them), run python main.py from scratch, and compare the counts against the documented ones. Restore the original database afterwards so the notification history isn't lost."

   *Why:* a clean run proves the single command works, and comparing to documented numbers proves the docs are true. Everything matched; the only difference was the one explained by the 10 notified rows.

## 3. MCP integration

### Which server and why

I used a **custom FastMCP server** (`mcp_server/gmail_server.py`, about 50 lines) with one tool: `send_email(to, subject, body, references)`. It sends through Gmail SMTP using an **App Password**. I chose this over an existing Gmail MCP server because:
- **Simple setup:** just a Gmail App Password, with no Google Cloud project, OAuth consent screen or token refresh.
- **Control over headers:** `references` sets both `References` and `In-Reply-To` to the flagged email's Message-ID, as the notice template requires. `From` shows "Email Deduplication System" (D57).
- **Small enough to read and explain** line by line.

### Setup, step by step (full details in [SETUP.md](SETUP.md) §5–8)

1. **Credentials:** turn on Gmail 2-Step Verification, create an App Password, and put it in `.env` (git-ignored, never read by the AI):
   ```
   GMAIL_USER=you@gmail.com
   GMAIL_APP_PASSWORD=<16 characters, no spaces>
   NOTIFY_TO=you@gmail.com
   ```
2. **Dependencies:** `mcp==1.30.0` (pinned; see story 1), `python-dotenv`.
3. **Check the server starts:** `python mcp_server/gmail_server.py` (it waits silently on stdio).
4. **Register it with Claude Code, project scope** (I ran this myself):
   ```bash
   claude mcp add gmail --scope project -- "$(pwd)/.venv/bin/python" "$(pwd)/mcp_server/gmail_server.py"
   claude mcp get gmail     # Scope: Project · Type: stdio · Status: ✔ Connected
   ```
   This writes `.mcp.json` (git-ignored). **Restart `claude`** afterwards, because servers load at session start.
5. **Config template:** [`mcp_config.json.example`](mcp_config.json.example) has the same structure as `.mcp.json`, with placeholder paths and no credentials.

### How I prompted the AI tool to use `send_email`

> "Use the gmail send_email tool to send a test email to swara.awsm@gmail.com with subject 'MCP test' and body 'hello from Claude Code'."

Claude called `mcp__gmail__send_email` and the tool returned `sent to swara.awsm@gmail.com (Message-ID <179390911815.21710.5710468976951489097@dedup.local>)`. I confirmed it arrived: [docs/mcp_test_send.png](docs/mcp_test_send.png).

### How the pipeline uses it (live mode)

For `--send-live` to work without Claude, `src/notify.py` is an **MCP client over stdio**:
- It starts `gmail_server.py` as a subprocess (the same way `.mcp.json` does), opens one `ClientSession`, and calls `send_email` once per notice, about 1 s apart.
- **Errors:** an auth error or quota/rate limit stops the run; transient errors are retried 3 times (2/4/8 s); every outcome is logged.
- **Safety rules:**
  - always sends to `NOTIFY_TO`, never to the original Enron addresses (D51)
  - max 10 per run and **10 in total** (D49, D58)
  - marks an email notified only after a confirmed send

I prompted the build step by step (preview first, then exactly 1 send, then the rest):
> "Go for steps 4–7. Show me the preview list of live targets before any send, and start the live run with exactly 1 email so I can check my inbox before sending the rest."

### Issues during MCP setup and sending, and how I resolved them

| Issue | Resolution |
| --- | --- |
| Server crashed on import: `No module named 'mcp.server.fastmcp'` | The `mcp` 2.x release renamed the API; I pinned `mcp==1.30.0` (story 1, D2) |
| First test send: the tool wasn't available in the running Claude session | Servers load at session start; I restarted `claude`. Claude deliberately didn't fall back to calling SMTP directly, because the proof had to go *through MCP* |
| First live notice showed only my bare address as sender | Added the "Email Deduplication System" display name in the server (D57) |
| The preview's top 10 contained 3 probable export copies | Amended the export-copy rule before any send (story 4, D45 amendment) |
| The send cap was per run, so a "re-run sends 0" check would have sent 10 more | Added a total budget counted from the DB (D58) |

### Proof of live sends

- **Screenshot of the first pipeline notice** in my Gmail: [docs/live_send_proof.png](docs/live_send_proof.png). It's the YPO forum survey, delivered twice 8 seconds apart; score 100.00%.
- **`output/send_log.csv`:** 10 rows, all `sent`, all to my Gmail, each with the intended (original) recipient. Excerpt:
  ```
  timestamp,recipient,subject,status,error,intended_recipient,duplicate_message_id
  2026-11-06T03:33:39+00:00,swara.awsm@gmail.com,[Duplicate Notice] Re: Your online YPO forum survey -- complete in 3 easy steps!,sent,,ypoforumsurvey@ypoforumdiagnosticsurvey.com,<17712798.1075852646824.JavaMail.evans@thyme>
  ```
- A re-run of `--send-live` printed "10 of 10 already sent; 0 left … 0 emails sent".

## 4. Iterations and debugging

Cases where the AI's first attempt didn't work, and how they were fixed.

### Story 1: AI-generated code vs an unpinned dependency (MCP server)
- **Symptom:** the Gmail MCP server crashed on import with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`.
- **Cause:** `gmail_server.py` was AI-generated against the **mcp 1.x** API (`FastMCP`). My first `requirements.txt` was unpinned, so `pip` installed **mcp 2.3.0**, where `FastMCP` was renamed. Pinning *after* the install only froze the broken version.
- **Fix:** I pinned `mcp==1.30.0` and reinstalled. Claude noticed the downgrade had left 5 orphan 2.x-only packages, compared against a fresh install in a temporary venv, removed the orphans, and regenerated `requirements-lock.txt` (38 packages).
- **Lesson:** pin fast-moving libraries up front, and check AI-generated code against the *installed* library version. Regenerate lock files from a clean install.

### Story 2: a silent data loss in Python's address parser (Task 1)
- **Symptom:** a verification script that compared parsed counts with the raw scan found 2 Cc headers that produced no addresses at all.
- **Cause:** Python 3.13's `getaddresses` runs in strict mode by default. **One** malformed address (`<"barbara"@mailman.enron.com@enron.com>`) makes it return nothing for the **whole** header, silently dropping valid recipients like `skeeper@enron.com`.
- **Fix:** lenient mode, keeping only tokens that look like `name@domain` (D18). 4 lists recovered, 6 junk tokens dropped, and one double-`@` address knowingly lost.
- **Lesson:** don't trust "no error" from a parser. Compare its output with an independent count.

### Story 3: a suspiciously perfect number (Task 1)
- **Symptom:** the completeness report showed `has_attachment` **100%** filled.
- **Cause:** the check treated anything not `None`/`""`/`[]` as filled, and `False` passed.
- **Fix:** count only `True`. The real figure was 1,336 (6.2%).
- **Lesson:** a perfect number is a bug until proven otherwise.

### Story 4: the preview caught a rule gap before any live send (Task 4)
- **Symptom:** the `--preview` list (which sends nothing) showed 3 of its top 10 "real re-sends" were probably the same email from two exports: +12 h (99.81%), +9 h (99.85%), +5 h + 1 s (99.98%).
- **Cause:** my export-copy rule (D45) required a score of *exactly* 100 and *exact* whole hours.
- **Fix:** Claude stopped before sending and measured three variants (141 / 131 / 118 eligible targets). I chose ≥ 99 within 60 s. Duplicate flags didn't change; only the report column and stats did.
- **Lesson:** preview any outward-facing action. A rule that looks right in aggregate stats can still be wrong for the specific items you're about to act on.

### Story 5: a shell quirk during the clean run (Task 4)
- **Symptom:** a loop meant to move the outputs aside didn't move them, and created a stray empty folder.
- **Cause:** zsh doesn't split `$FILES` into words (bash does). The same quirk had earlier broken a print command.
- **Fix:** Claude first verified every original was intact (sizes, and the 10 notifications in the DB), removed only the empty folder it had created, and redid the move in Python with MD5 checksums. After the clean run the restored files matched those checksums exactly.
- **Lesson:** before retrying after a failed file operation, check what state you're actually in.

## 5. Self-corrections and flagged deviations

**Claude corrected its own statements:**
1. **The D6 date fact:** it first called `31 Dec 1979 16:00 PST` "the Unix epoch". While writing the UTC conversion it noticed this is **1 Jan 1980 00:00 UTC** (the Unix epoch is 1 Jan 1970). The decision stood, but the stated reason was wrong, and both docs were fixed.
2. **The D17 count, 96 → 12:** it reported 96 bodies starting with a Lotus Notes header block. When I asked for examples, it re-counted: only **12** were real Notes blocks. The other 84 were memo-style headers that belong to the message. Applying the rule to all 96 would have deleted real content.
3. **The completeness bug** (story 3).
4. **The address count, 13,390 → 11,146:** the Task 2 findings counted senders as addresses, but senders are a text column, not rows in the `addresses` table.

**Changes Claude made beyond my instructions, each flagged in its report for me to accept or reverse:**
1. An extra body-split marker for a mid-body Notes header (161 emails); I approved it (D8 amendment).
2. `--limit` in dedupe became a print-only preview, because writing flags from a sample would half-flag the DB; I approved it (D42 amendment).
3. A **total** live-send budget, flagged *before* acting (D58). Without it, "a re-run sends 0" would have sent 10 more emails.

## 6. How we validated the tests

All three test suites passed on their first run. A test that has never failed might not test anything, so each time Claude **broke the rule in memory** (never in the source file) and re-ran the matching test:

| Suite | Rules broken | Caught? |
| --- | --- | --- |
| Parser (8 tests) | D19 single `>` = quote · D6 placeholder list emptied · D17 strip disabled | all ✔ |
| Database (7 tests) | upsert → `INSERT OR REPLACE` (silently wipes notification state) · no recipient delete · stale-original guard removed | all ✔ |
| Dedupe (8 tests) | chaining instead of anchoring · no tie-break · notified rows wiped · no Notes/Outlook condition · D44 both-empty → fail / one-empty → pass / no body gate | all ✔ |
| Dedupe | D44's explicit empty-body rule replaced by rapidfuzz's built-in behaviour | ✘ **not caught, honestly reported:** rapidfuzz 3.14.6 already scores `('', '')` = 100 and `('x', '')` = 0, so the outcomes are identical. The explicit rule guards against a future library change |

## 7. What I verified myself

I didn't take the AI's word for the key results. I opened raw files and outputs myself:

- **Parser (4 records):**
  - `lay-k/inbox/1082.`: 11:47 PST → 19:47 UTC; attachment found from ` - file.xls`
  - `lay-k/elizabeth/23.`: a wrapped `To` unfolded into 6 addresses; empty body, full forward chain, `.DOC` attachment found in the forwarded part
  - `lay-k/sent/71.`: split at the Notes reply header; the body is Ken's letter, the quoted part is Loyal's original
  - `lavorato-j/all_documents/8.`: blank subject stored as `""`; Cc = Bcc. Here I also found evidence for D7: `X-bcc` is empty while `X-cc` names the recipient.
- **Duplicate case B (OWA notice):** same sender, subject and text, Jan 19 vs Apr 30 2001, cross-mailbox (Lavorato → Skilling). The copies are wrapped differently, so it scores 100 only because of whitespace collapsing (D36). The recipients are completely different (15 vs ~90): a batch mailing, not an accidental re-send. This led to the `recipient_overlap` column (D46).
- **A draft in Apple Mail** ([docs/draft_headers.png](docs/draft_headers.png)): display name, a single `Re:`, `To` = the real sender, template body, UTC dates, 100.00%. Both dates were identical, so it's a folder copy, which confirmed why live sends target only real re-sends (D50).
- **The first live send:** arrived in Gmail as expected ([docs/live_send_proof.png](docs/live_send_proof.png)). `send_log.csv` and the DB's `notification_date` agreed to the second.

## 8. Boundary notes (self-reported by Claude)

1. **`.env` names:** to check that `NOTIFY_TO` was configured, Claude listed the *variable names* in `.env` (no values) and told me in the same message. **My rule:** never read `.env` in any form, not even names; ask me.
2. **Outside the project folder:** when a screenshot I mentioned wasn't in `docs/`, Claude found it on my Desktop, checked it, and copied it in (leaving the original), and told me. **My rule:** don't access anything outside the project folder without asking first.

Both rules are now in `CLAUDE.md` ("Boundaries") and in Claude's persistent memory for this project. Throwaway scripts now go in a git-ignored `scratch/` folder inside the project.

## 9. What I wrote vs what the AI wrote

| Part | Who |
| --- | --- |
| **Design decisions** (58 in DECISIONS.md) | **I made the final call on all of them.** I reviewed each one and checked real emails before deciding. Claude Code proposed and measured the options; my planning chat helped me evaluate them and suggested several changes I adopted (section 2). |
| **Python code** (`src/`, `tests/`, `main.py`, `schema.sql`, `sample_queries.sql`) | **~100% written by Claude Code.** I reviewed it, requested changes, and spot-checked outputs by hand (section 7). |
| **MCP server** (`mcp_server/gmail_server.py`) | Written by my **planning chat**. The `mcp` version pin fix (story 1) and the display-name change (D57) were done by Claude Code. |
| **`CLAUDE.md`** (the working method) | **My original template**, adapted to this project by the planning chat, then edited by Claude Code (time checkpoints, boundaries). |
| **`SETUP.md`** | Written by my **planning chat**. I followed it and hit the real-world issues (e.g. the `mcp` 2.x crash, the tool missing until a restart). |
| **Design docs** (DECISIONS, ARCHITECTURE, PLAN, FINDINGS, README, this file) | **Drafted by Claude Code in my voice.** I directed the content and reviewed it. |
| **Hands-on, done by me** | Environment setup, mailbox extraction, the Gmail App Password and `.env`, MCP registration (`claude mcp add`), all the manual verifications in section 7, the screenshots, and approving every command Claude Code ran. |

## 10. Lessons learned

**What worked well**
- **Findings → decisions → plan → one step at a time.** Slower per step, but every number in the docs is measured, and I can explain every choice.
- **Asking for examples before approving a rule.** It caught the 96 → 12 overcount and the export-copy gap.
- **"Show me the numbers for each option."** Decisions like D44 and the D45 amendment were made on counts, not guesses.
- **Making outward actions previewable and incremental** (`--preview`, then exactly 1 send, then the rest).
- **Requiring the AI to flag its own deviations.** It kept me in control without slowing things down.

**What was harder than expected**
- **The data, not the code.** Most "duplicates" were folder copies, export copies had shifted clocks, and templates passed 90%. The spec's rule is clear, but applying it to real data needed many judgement calls.
- **Plausible-looking AI output can be wrong in quiet ways:** a wrong "fact" (the epoch), a too-broad count, a perfect 100%, a library silently dropping data, tests that pass for the wrong reason. Each was caught by asking for evidence, not by reading the code.
- **Keeping the docs in sync with a changing pipeline** took real effort. Writing step reports into files as we went (instead of relying on terminal output) made it manageable.
- **Boundaries need to be explicit.** The AI acted reasonably both times (`.env` names, the Desktop screenshot), but "reasonable" isn't the same as "what I agreed to". Writing the rules into `CLAUDE.md` fixed that.
