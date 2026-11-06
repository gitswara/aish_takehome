# Decisions

Each decision or assumption, the options I considered, why I chose this one, and how many rows it affected.

---

## D1. How to pin dependencies

- **Options:**
  - (a) Direct deps only: `requirements.txt` with my 6 packages pinned
  - (b) Full freeze only: `requirements.txt` = `pip freeze` (38 packages)
  - (c) Both: short `requirements.txt` + full `requirements-lock.txt`
- **I chose (c).** `requirements.txt` stays short and readable (it shows what the project actually depends on), and `requirements-lock.txt` guarantees reproducibility by pinning all 38 packages, including transitive ones.
- **Rows affected:** none (environment setup, no data change).

## D2. Fixing the MCP server import failure (mcp 1.x vs 2.x)

- **Context:** `gmail_server.py` imports `mcp.server.fastmcp.FastMCP` (1.x API). The unpinned install pulled `mcp==2.3.0`, where it was renamed to `mcp.server.mcpserver.MCPServer`, so the server crashed on import.
- **Options:**
  - (a) Pin `mcp==1.30.0` (latest 1.x) and keep the code as written
  - (b) Port the server to the 2.x `MCPServer` API and keep `mcp==2.3.0`
  - (c) Use a version range instead of an exact pin
- **I chose (a).** The code is known to work on 1.x, porting would bring in 2.x API changes I'd have to explain, and the risk is lower under time pressure.
- **Why not (c):** a bare `>=` range (e.g. `mcp>=1.30`) would still allow 2.x and the same crash. A bounded `>=1.30,<2` would block 2.x, but it would still allow untested 1.x releases, so an exact pin is more reproducible.
- **Side effect:** downgrading left 5 orphan packages that only 2.x needed (`httpcore2`, `httpx2`, `mcp-types`, `opentelemetry-api`, `truststore`). I removed them so `requirements-lock.txt` (38 packages) exactly matches a fresh install of `requirements.txt`.
- **Verified:** the server imports, completes the MCP `initialize` handshake, and lists the `send_email` tool.
- **Rows affected:** none (environment setup, no data change).

## D3. Mailbox selection

- **Context:** the assignment needs at least 10k emails. I'm using a subset of the Enron maildir.
- **Options:**
  - (a) The largest mailboxes (20k+ emails each)
  - (b) Randomly picked mailboxes
  - (c) Senior executives who wrote to each other
- **I chose (c):** `lay-k`, `skilling-j`, `whalley-l`, `lavorato-j`, `delainey-d`. Because these people corresponded, the same message shows up in several of their mailboxes and folders (sent, inbox, `all_documents`, `discussion_threads`). That gives duplicate detection realistic cross-mailbox cases. At about 21.7k emails, it also keeps iteration fast while clearing the 10k minimum.
- **Why not (a):** each large mailbox alone is 20k+ emails, which slows iteration, and one person's mailbox has fewer cross-mailbox duplicates.
- **Why not (b):** random mailboxes may never have written to each other, so there would be few realistic cross-mailbox duplicates.
- **Rows affected:** 21,662 files in scope. I verified the count with `find -type f`: lay-k 5,937 · skilling-j 4,139 · whalley-l 3,335 · lavorato-j 4,685 · delainey-d 3,566.

---

# Task 1: Parser decisions

Counts come from a scan of all 21,662 files before I wrote the parser. Counts marked *(at run)* get filled in from the parser's real stats.

## D4. Emails with no `To` header

- **Context:** `To` is mandatory, but 1,298 emails (6%) have no `To` header. They are mostly calendar entries, announcements and mailing lists.
- **Options:** (a) fail them, as the spec says · (b) fill in from `X-To` where it holds an address, fail the rest · (c) keep them with an empty list.
- **I checked first:** `X-To` for those 1,298 is empty in 516, names only in 718, an Exchange ID only (no email address) in 4, and holds a real email address in just **60** (4.6%).
- **I chose (a), fail with reason "missing To".** Option (b) would recover only 60 emails, which isn't worth an extra rule I'd have to justify.
- **Rows affected:** 1,298 sent to `error_log.txt`.

## D5. Blank subject

- **Options:** (a) accept `""` as a valid subject · (b) fail them.
- **I chose (a).** The `Subject` header is present, so the field was extracted. Its value is just empty.
- **Rows affected:** 1,489 kept with `subject = ""`.

## D6. Placeholder dates (31 Dec 1979 16:00 PST)

- **Context:** that timestamp is **1 Jan 1980 00:00 UTC**, the "zero" date of old DOS/Windows file systems, so it's a placeholder, not a real send date. Every other date falls in 1998–2002. *(Correction: I first called it the Unix epoch, but that's 1 Jan 1970. I caught this when I wrote the UTC conversion in step 3. The decision is unchanged.)*
- **Options:** (a) fail with reason "placeholder date" · (b) keep and flag · (c) keep as-is.
- **I chose (a).** Left in, these would always count as the "earliest original" in a duplicate group (Task 3).
- **Rows affected:** 28 sent to `error_log.txt`. Verified in step 3: 28 dates convert to `1980-01-01T00:00:00+00:00` (`PLACEHOLDER_DATES_UTC` in the config).

## D7. Bcc is always a copy of Cc

- **Context:** in all 5,594 emails that have `Bcc`, it exactly equals `Cc`. This is a known flaw in how the Enron data was converted, not real blind copies.
- **Options:** (a) store Bcc as given · (b) clear Bcc when it equals Cc.
- **I chose (a).** I stay faithful to the source and document the flaw here, so anyone querying Bcc knows to treat it with care.
- **Supporting evidence (I checked this myself in step 9):** in `lavorato-j/all_documents/8.`, the `Bcc:` header lists `david.redmond@enron.com`, but `X-bcc:` is **empty** while `X-cc:` names `David Redmond`. The X- headers come from the original mail system, and they show him as a normal Cc with no blind copy. So the `Bcc:` header is a copy made during conversion, not a real Bcc.
- **Rows affected:** 5,594 (stored unchanged).

## D8. Splitting body / forwarded / quoted content

- **Options:** (a) cut at the first marker · (b) keep the full text in `body` and also extract copies · (c) parse nested forwards recursively.
- **I chose (a).** Text above the first marker is `body`. Everything from the first marker on goes to:
  - `forwarded_content` if the first marker is `----- Forwarded by …` (3,587 emails)
  - `quoted_content` if it is a reply marker: `-----Original Message-----` (1,786), a Lotus Notes `Name on MM/DD/YYYY HH:MM AM/PM` header (2,765), or `>`-quoted lines (609)
- **Amendment (step 4), approved by me after review:** Claude added a sixth marker, `notes_reply_from_line`: the mid-body Notes header `From:  Name @ X      MM/DD/YYYY HH:MM AM/PM`. It wasn't in my original list, so Claude flagged it in the step 4 report, and I approved it after review. It sends the rest to `quoted_content`, like the other reply markers. It is the first marker in 161 emails.
- **Why not (c):** forwards nest 3–4 levels deep. Recursive parsing is much more code to explain, and the spec only asks to separate content "where possible".
- **Rows affected (full run, first marker per email, after D19):** none 14,788 · notes_forward 3,353 · outlook_original 1,487 · notes_reply_one_line 1,153 · notes_reply_two_line 463 · gt_quoted 257 · notes_reply_from_line 161 (sum 21,662). Verified in step 9: no text is lost, because body + forwarded + quoted reproduces the original body in all 20,339 parsed records.

## D9. (For Task 3) Similarity compares the full original text

- **Context:** after D8, a short forward like "fyi" has a tiny `body`. Two "fyi" forwards of completely different content would look 100% similar.
- **I chose:** fuzzy similarity in Task 3 compares `body + forwarded_content + quoted_content` (the full original text), not just `body`.
- **Rows affected:** none yet. This applies in Task 3.

## D10. `has_attachment`

- **Context:** all 21,662 emails are single-part `text/plain`, so there are no real MIME attachments. Attachments can only be guessed from the body.
- **Options:** (a) filename patterns only · (b) also the word "attached".
- **I chose (a).** A ` - name.ext` line (869 emails) or `<<name.ext>>` (564 emails), where ext is a common document type. The word "attached" gives false positives ("I'm attaching later", quoted text).
- **Rows affected:** **1,336** emails `has_attachment = true` (step 5, with the D21 scope). The extension list is `ATTACHMENT_EXTENSIONS` in the config.

## D11. `headings`

- **Options:** (a) ALL-CAPS lines plus numbered or lettered section lines (`A. 2000 Key Facts`, `1. FERC CONTINUES…`) · (b) also short lines ending in `:` · (c) skip.
- **I chose (a), from the primary `body` only,** so the `To:` / `cc:` blocks inside forwards aren't picked up. This is a nice-to-have in PLAN.md.
- **Rules as built (step 10), with thresholds in the config block:**
  - **ALL-CAPS line:** at least `HEADING_MIN_LETTERS = 4` letters and `HEADING_MIN_DISTINCT_LETTERS = 3` different ones (rules out `AAAA…` dividers); at most `HEADING_MAX_WORDS = 10` words; doesn't end in `.`; no tab (table rows); doesn't start with `-` (attachment lines); fewer digits than letters (rules out addresses like `LA, CA 90036`); no `@ / \ < > = |`; not in `HEADING_IGNORE_WORDS` (`THANKS`, `FYI`, `ADVERTISEMENT`, …); `[IMAGE]` placeholders are removed first.
  - **Numbered/lettered line:** `1.`, `2)`, `A.`, `IV.` followed by text that starts with a capital letter or digit; at most 10 words; doesn't end like a sentence (`.`, `?`, `,`, `;`) unless ALL-CAPS; a letter label needs at least 2 words (rules out initials like `R. Causey`); not `Lastname, Firstname` (rules out `9.  Wingo, Angie`).
  - Stored as one heading per line (`\n`-joined), or `null` if none.
- **How I tuned it:** a first version caught 654 `[IMAGE]` placeholders, 513 `AAAA…` dividers and name lists (`R. Causey`, `A. Fastow`). It also *missed* `A. 2000 Key Facts --`, the example this decision was based on. I added one exclusion at a time and re-checked samples.
- **Rows affected:** **1,354** of 20,339 parsed emails (6.7%) have headings: 4,714 heading lines, median 2 per email. Before body-only filtering, the whole-text counts were 1,765 (ALL-CAPS) and 1,019 (numbered).
- **Precision (heuristic, from a hand check of 30 random heading lines):** about 17 clearly headings, 4 borderline (instruction steps, `PLEASE DO NOT REPLY TO THIS EMAIL`), 9 not (names like `WHALLEY, LAWRENCE G,`, street addresses, ranked list items like `3. Sony Corp 3.38%`). That's roughly 60–70%.
- **I accepted it as is.** Why I stopped tuning: the spec's definition of "headings" is vague and this is a nice-to-have field. The remaining noise is names, street addresses and ranked list items. Each needs its own rule, every rule risks dropping real headings, and each one is more code to explain for little gain. So I documented the noise instead.

## D12. Parser output format

- **Options:** (a) write straight into SQLite · (b) write `output/parsed_emails.jsonl`, loaded by Task 2.
- **I chose (b).** Task 1 can be run and checked on its own, and list fields (`to_addresses`, etc.) stay real lists instead of strings.
- **Rows affected:** none (format only).

## D13. When to decode quoted-printable

- **Options:** (a) decode only when `Content-Transfer-Encoding: quoted-printable` is declared · (b) also decode bodies that merely look encoded (`=20`, soft `=` line breaks, `=3D`).
- **I checked:** 924 emails declare quoted-printable, and all 924 show its artifacts. 193 undeclared emails match the look-alike patterns, but the ones I inspected are `====` and `+=+=` divider lines in newsletters (CNN QuickNews, Crossfire), not real encoding. Decoding those would mangle the text.
- **I chose (a), declared only.**
- **Rows affected:** 924 decoded; 193 left as-is.
- **Verified at run (step 2):** all 924 decoded. 23 of them still match `=\n`, but every case is a `====` divider line, not leftover encoding.

## D14. Sender with no real address

- **Context:** `From: pep <performance.>` has no `@`. Step 3 found a second one: `From: <"d@piassick".@enron@enron.com>` (`lay-k/deleted_items/532.`), a mangled address with no valid `name@domain` part.
- **I agreed to fail it.** This follows the spec's rule for mandatory fields: if `from_address` can't be extracted as a real address, the email is logged as a failed parse with the reason "invalid From address".
- **Rows affected:** 2 sent to `error_log.txt` (was 1 before step 3).

## Parser assumptions (approved by me)

- I use Python's built-in `email` module, so no new library. Dates convert to UTC with the standard library; I use `python-dateutil` (already installed) only for timezone abbreviations.
- Addresses are lowercased and kept as written, double dots included (`s..shively@enron.com`).
- `source_file` keeps the trailing dot (`maildir/lay-k/inbox/45.`) so the path opens.
- I normalise CRLF line endings to LF first, because headers use CRLF and bodies use LF (19,611 files).
- Non-ASCII bytes are read as Windows-1252, so decoding never fails (7 files have non-ASCII headers).
- Wrapped subjects (719) are unfolded onto one line. `Re:` / `Fwd:` prefixes are kept.
- "test" and "demo" emails (61) are real business email. I keep them, with no flag.
- **Finding:** all 21,662 Message-IDs are unique, yet 15,664 files are exact copies of another email (4,881 groups). The `message_id` unique constraint won't catch these copies; Task 3's fuzzy match will.
- **Expected failures:** **1,323** emails, leaving **20,339** parsed (✔ confirmed exactly by the step 6 run). I measured the overlap in step 3: 1,293 no `To` only, 23 placeholder date only, 5 with both, and 2 invalid senders (D14). Final numbers are confirmed in step 6.

## D15. How `--limit` picks its sample

- **Options:** (a) the first N files in sorted order · (b) a random N · (c) N files evenly spaced through the sorted list.
- **I chose (c).** Option (a) would give 200 files from a single folder of `delainey-d`. Option (b) changes on every run unless I fix a random seed. Evenly spaced is deterministic and covers every mailbox.
- **Rows affected:** test runs only; full runs use all files. The 200 sample has delainey-d 33 · lavorato-j 44 · lay-k 54 · skilling-j 39 · whalley-l 30, across 41 folders.

## D16. Garbled punctuation (`\x01` control characters)

- **Context:** after decoding, 612 bodies contain the control character `\x01` followed by another character, about 4,600 times. The most common is `\x01,` (2,222, e.g. `Enron\x01,s`), clearly a curly apostrophe garbled when the data was converted. Others: `\x018` (299), `\x01*` (126), `\x01(` (45), and 1,914 at the start of a word. These look like curly quotes and dashes, but I haven't confirmed the mapping.
- **Options:** (a) leave as-is · (b) replace only `\x01,` with `'` · (c) remove every `\x01` and keep the character after it.
- **I chose (b): replace only `\x01,` with `'`,** the case I can prove (`Enron\x01,s` → `Enron's`). The other forms stay as-is because I can't prove what they stand for.
- **Rows affected:** 2,231 replacements in 496 bodies. 2,387 other `\x01` characters remain in 290 bodies (documented, not changed). The setting is `GARBLED_APOSTROPHE` in the config.

## Step 2 notes (read + decode)

- 21,662 of 21,662 files read, 0 errors. No replacement characters (U+FFFD), no headers returned as `Header` objects, no parser defects, and no `\r` left in any body.
- 96 bodies begin with a header-like line, but only 12 are the Lotus Notes block (D17). The other 84 are memo-style headers that are part of the message (`To: All EES / From: EES Office of the Chairman`, meeting notices with `Subject:/Date:/Time:`, newsletters with `From: Pete / To: Ken`). They stay in `body` untouched.

## D17. Bodies that start with a Lotus Notes header block

- **Context:** 12 bodies start with `From:  David W Delainey   MM/DD/YYYY HH:MM AM/PM`, then `Sent by: Kay Chapman`, `To:`, `cc:`, `Subject:`. These are 3 distinct messages, each copied into 4 Delainey folders (`sent`, `_sent_mail`, `all_documents`, `discussion_threads`). The header `From` is `kay.chapman@enron.com`: his assistant sent them on his behalf.
- **Options:** (a) strip the leading block and keep the rest as `body` · (b) treat it as a forward.
- **I chose (a).** I checked before/after for `delainey-d/sent/224.` and `sent/333.`. The text under the block is Kay's own message ("Dave would like to have a strategy meeting…"), not a forward.
- **Rule (step 4):** applies only when the body *starts with* `From:  Name   MM/DD/YYYY HH:MM AM/PM`. The block ends at its `Subject:` line. Memo-style starts (`To: All EES`, etc.) are not touched.
- **Found while checking:** `sent/333.` also contains a **two-line** Notes reply header (`David W Delainey` / `08/15/2000 02:05 PM` / `To: …`) with no "on". Step 4's quoted-content marker must handle this form too, not only `Name on MM/DD/YYYY`.
- **Rows affected:** 12 (applied in step 4).

## D18. Lenient address parsing

- **Context:** Python 3.13's `getaddresses` runs in strict mode by default. If any address in a header is malformed, it returns nothing for the *whole* header. For example, `<"barbara"@mailman.enron.com@enron.com>, skeeper@enron.com` lost `skeeper@enron.com`.
- **Options:** (a) strict (default) · (b) lenient (`strict=False`), keeping only tokens that look like `name@domain`.
- **I chose (b).** Confirmed by me after step 3.
- **Rows affected:**
  - Recovered: 2 `Cc` and 2 `Bcc` lists (`lay-k/inbox/573.`, `577.`).
  - Junk tokens dropped: 6 (`enron.com` ×5, `bailey` ×1).
  - **Known loss (documented, accepted):** one real recipient is dropped. `'"kristina_mourdaunt@enron.net"@enron.com` in the `To` of `skilling-j/sent_items/106.` has two `@` (a quoted address with `@enron.com` added on the end), so it fails the `name@domain` check. The intended address was probably `kristina_mourdaunt@enron.net`. I didn't add a special-case repair for a single address. The email keeps its other `To` recipients and still parses.
  - No email went from having `To` addresses to having none.

## Step 3 notes (header fields)

- All 21,662 processed, 0 errors. Completeness: `message_id` and `date` 100%, `from_address` 21,660 (2 invalid → D14), `to_addresses` 20,364 (1,298 without → D4), `cc_addresses` 5,594, `subject` 20,173 non-blank (1,489 blank, kept → D5).
- Dates are converted to UTC ISO strings, e.g. `Wed, 16 Jan 2002 11:47:35 -0800 (PST)` → `2002-01-16T19:47:35+00:00`.
- The timezone-name fallback works (`… 16:39:00 PST` → `2001-05-15T00:39:00+00:00`), though no email in our data needs it. Unparseable dates return `None` (failed in step 6).
- Wrapped subjects are unfolded, e.g. `lay-k/calendar/4.` → one line.
- `x_bcc` is non-empty in only 13 emails.

## Step 4 notes (body split)

- Implemented D8 with 6 marker types: `notes_forward` → forwarded; `outlook_original`, `notes_reply_one_line`, `notes_reply_two_line`, `notes_reply_from_line`, `gt_quoted` → quoted. The earliest marker wins. Full per-marker counts and samples are in `docs/FINDINGS_task1.md`.
- `notes_reply_from_line` (161 emails) is the mid-body form of the Notes `From:  Name   date` header. I treat it as a reply marker under D8.
- D17 applied: 12 leading Notes blocks stripped.
- 1,101 emails had an empty `body` after the first split; **1,092** after D19 (9 of the 36 `>` emails got their text back). These are pure forwards or replies, and D9 covers them in Task 3.

## D19. What counts as `>` quoting

- **Context:** 293 emails are cut at a `>` line. In 36 of them it's a single `>` line that isn't a quote: `  >40 GW   $250/MWh` (table), `>>>  Town Hall Meeting <<<` (heading), `>$60 to $80M…` (ambiguous).
- **Options:** (a) any line starting with `>` (current) · (b) at least 2 consecutive `>` lines.
- **I chose (b): at least 2 consecutive `>` lines.**
- **Rows affected:** `gt_quoted` splits went from 293 to **257** (−36). Those 36 now have no marker (`no_marker` 14,752 → 14,788) and keep their full text in `body`. All marker counts still sum to 21,662.

## D20. Notes reply headers with a 24-hour time

- **Context:** `From: John J Lavorato on 23/01/2001 15:19 CST` uses a 24-hour time and a zone name instead of AM/PM, so no marker catches it.
- **Options:** (a) leave it (the text stays in `body`) · (b) extend the Notes date pattern to also accept `HH:MM ZZZ`.
- **I chose (a): leave it.** Known miss, documented. 5 emails keep their reply text inside `body`: `lavorato-j/all_documents/798.`, `lavorato-j/notes_inbox/35.`, `lavorato-j/offsite/11.`, `lay-k/all_documents/566.`, `lay-k/notes_inbox/355.`. Widening the date pattern for 5 emails isn't worth the extra regex to explain.
- **Also a known miss (agreed):** about 50 emails contain raw message headers pasted inline (`From: "Joseph G.Galea" <…>` / `Date: …`, inline MIME attachments). These have no Notes or Outlook marker and stay in `body`.

## D21. Which text to search for attachment filenames

- **Context:** D10 fixed *how* to detect attachments (filename patterns) but not *where* to look. The count depends on it.
- **Options (counts from the full run):**
  - (a) primary `body` only: **1,146**
  - (b) `body` + `forwarded_content`: **1,336** (+190)
  - (c) full text, including `quoted_content`: **1,870** (+534 more)
- **I chose (b): `body` + `forwarded_content`.** A Lotus Notes forward carries the original's attachment along, so a filename in the forwarded part usually means the file is attached to *this* email. A reply's quoted part names the *original's* attachment, which Outlook and Notes replies normally don't re-send. Example: `lavorato-j/sent_items/501.` names `<< File: NW Update.xls >>` only in the quoted part.
- **Rows affected:** 1,336 emails `has_attachment = true` across all 21,662 processed files: 190 more than (a), 534 fewer than (c). Among the **20,339 parsed** emails it's **1,149** (187 of the 1,336 failed, mostly for missing `To`).

## Step 5 notes (has_attachment)

- Notes-style ` - name.ext` lines appear in 1,738 emails and Outlook `<<name.ext>>` in 660 (full text, overlapping).
- Top extensions: doc 1,915 · pdf 579 · jpg 242 · xls 211 · ppt 120 · gif 97 · htm 81.
- No hit is a web link. The `htm`/`jpg`/`gif` hits are real attachment files (`att1.htm` ×40, an Outlook HTML copy of the message; `image001.jpg`; `crest.gif`).
- Not counted: 7 bodies contain an embedded MIME message (`Content-Disposition: attachment` / "multi-part message in MIME format"). D10 is filename patterns only; these 7 are documented, not detected.

## D22. When is the mandatory `body` "missing"?

- **Context:** `body` is mandatory. After the D8 split, 1,092 emails have an empty *primary* body because they are pure forwards or replies. All 1,092 still have `forwarded_content` or `quoted_content`; no email has no text at all.
- **Options:** (a) strict: fail when the primary `body` is empty · (b) fail only when `body`, `forwarded_content` and `quoted_content` are *all* empty.
- **I chose (b): fail only when `body`, `forwarded_content` and `quoted_content` are all empty.**
- **Why:** an empty primary body is a *result of my D8 split*, not missing content. The text is there, just moved into `forwarded_content` or `quoted_content`. Option (a) would also remove every pure forward *before* duplicate detection, and forwarded copies are exactly what Task 3 needs to compare.
- **Rows affected:** (a) would fail **1,058** more emails (34 of the 1,092 already fail for other reasons). (b) fails **0** for "missing body".

## Step 6 notes (mandatory-field check)

- `find_failure_reasons()` lists *every* reason an email fails. Failed emails go to `error_log.txt` (a header line, then `source_file<TAB>reason`, with multiple reasons joined by `; `) and are left out of the parsed records.
- **Full run: 20,339 parsed, 1,323 failed**, exactly the prediction from step 3. Breakdown:
  - missing To: 1,293
  - placeholder date: 23
  - placeholder date + missing To: 5
  - invalid From address: 2
- No "missing Message-ID", "unparseable Date", "missing Subject header" or "unexpected error" failures occurred.
- **Predictions confirmed exactly:** the failure counts I predicted from the initial whole-corpus scan (before any parser code) and the step 3 overlap check matched the real run exactly: 1,323 failed, 20,339 parsed. Per decision: D4 1,298 (1,293 + 5) ✔ · D6 28 (23 + 5) ✔ · D14 2 ✔.

## Step 7 notes (JSONL output)

- `write_jsonl()` writes `output/parsed_emails.jsonl`: one JSON object per parsed email, UTF-8, with `ensure_ascii=False` so names like `François` stay readable.
- **20,339 records** (= the parsed count), all with the same 19 fields in spec order. `headings` is added in step 10.
- Types are consistent: address fields are always lists (`[]` when empty), optional strings are `null` when absent, and `has_attachment` is a bool.
- `message_id` is unique across all 20,339, and so is `source_file`. No source file appears in both the JSONL and `error_log.txt`; together they cover all 21,662 files.
- The file is **51 MB** (see D23).

## D23. Don't commit the 51 MB JSONL; commit a small sample instead

- **Context:** `output/parsed_emails.jsonl` is 51 MB. GitHub warns above 50 MB and rejects files above 100 MB. It isn't in the assignment's deliverables list and can be rebuilt in about 11 seconds.
- **Options:** (a) git-ignore it · (b) commit it.
- **I chose (a),** plus a small committed sample, so reviewers can see the output format without running the parser.
- **The sample:** `output/sample_parsed_emails.jsonl`, written by the parser on every full run (`pick_sample()`; `SAMPLE_PER_CATEGORY = 3` in the config).
  - It has **18 records**: 3 each of plain, nested forward, Outlook reply, Notes reply, attachment, and blank subject.
  - Within a category it takes a different mailbox each time. Sorted order fills the categories from delainey-d, lavorato-j and lay-k first.
  - It is deterministic: the same data always gives the same sample.
- **Regenerate:** `python src/parse_emails.py` (documented in ARCHITECTURE.md; to go in README.md).
- **Rows affected:** none (output files only).

## Step 8 notes (stats)

- `build_stats()` collects every number into one dict. `print_stats()` prints it, and the same dict is saved as `output/extraction_stats.json` (3.4 KB, committed).
- **Completeness is reported twice:**
  - over *all processed files*: shows the gaps in the raw data, e.g. `to_addresses` 94.0%
  - over *parsed OK* only: what goes into the DB; mandatory fields are 100% by construction
- In completeness, a blank subject `""` and `has_attachment = false` count as "not filled". So `subject` is 92.8% filled among parsed records even though every parsed record has the header (D5).
- Checks: parsed + failed = processed (20,339 + 1,323 = 21,662); body-split markers sum to 21,662.
- ~~A `--limit` run overwrites the real outputs~~: fixed by D24.
- Subject is now shown two ways: `subject` (non-blank) 92.8% and `subject_header_present` 100% among parsed records.

## D24. `--limit` runs write to `output/sample_run/`

- **Risk:** a `--limit 200` run used to overwrite `error_log.txt`, `output/parsed_emails.jsonl` and `output/extraction_stats.json` with sample results. If I forgot the final full run, I could commit **sample results as the final output**: a 12-line error log instead of 1,323 failures.
- **Options:** (a) keep overwriting and rely on remembering · (b) send `--limit` outputs to a separate folder.
- **I chose (b).** `--limit` runs write `error_log.txt`, `parsed_emails.jsonl` and `extraction_stats.json` to `output/sample_run/` (`SAMPLE_RUN_DIR` in the config), which is git-ignored. The committed `output/sample_parsed_emails.jsonl` is still refreshed only on a full run.
- **Verified:** the MD5 checksums of the four real output files were identical before and after a `--limit 200` run.
- **Rows affected:** none (output locations only).

## Step 9 notes (full-run verification)

- **17 of 17 count checks match** the numbers in this file (table in FINDINGS step 9).
- **No text lost:** for all 20,339 parsed records, `body + forwarded_content + quoted_content` equals the original decoded body, ignoring whitespace and minus the 12 stripped D17 blocks. 0 mismatches.
- **10 spot-checked records**, chosen to cover plain, Cc, attachment, nested forward, Outlook reply, Notes reply, D17, quoted-printable, non-ASCII and blank subject. All 10 pass automated checks against the raw headers (Message-ID, From, To count, Cc count, Subject), and I read every field by eye. Paths are listed in FINDINGS step 9.

## Step 10–11 notes

- **Step 10 (headings):** see D11 for the rules, tuning history, counts (1,354 parsed emails) and the ~60–70% precision estimate.
- **Step 11 (tests):** to test whole emails, I moved the per-file work from `main()` into `parse_file(path)` (steps 2–6 for one file). `main()` and the tests both call it. The full-run outputs were byte-identical (MD5) before and after this refactor.
- 8 pytest cases in `tests/test_parse_emails.py`; all pass in about 0.1 s:
  - nested forward (D8, D22)
  - D17 block + two-line Notes reply
  - D19 single `>`
  - D19 two `>` lines
  - missing To (D4)
  - placeholder date (D6)
  - folded To + UTC date
  - quoted-printable + D16
- **The tests can fail:** I broke D19, D6 and D17 in memory one at a time, and each matching test failed as it should.

---

# Task 2: Database decisions

The facts behind these are in `docs/FINDINGS_task2.md` (measured on the 20,339 parsed records). I accepted all the recommendations, with my own changes to D30 and D34.

## D25. Database engine

- **Options:** (a) SQLite · (b) local PostgreSQL.
- **I chose (a), SQLite.** It's the spec's preference, a single file, and built into Python. PostgreSQL would need a server, a driver and setup for reviewers.
- **Rows affected:** none (design).

## D26. How to normalise addresses

- **Options:**
  - (a) `recipients(email_id, address, type)` with the address as text in every row
  - (b) an `addresses(id, address UNIQUE)` lookup table + `email_recipients(email_id, address_id, recipient_type)`; `from_address` stays as text on `emails`
  - (c) like (b), but `from_address` also becomes an `address_id`
- **I chose (b).** 190,390 recipient rows (after D29) point to only **11,146** distinct recipient addresses, so each address is stored once. *(My findings first said 13,390; that number included senders, who are a text column on `emails`, not rows in `addresses`.)* I kept `from_address` as text because it's a spec field with a required index; making it an id (c) would put a join in every sender query.
- **Rows affected (full load):** **11,146** address rows; **190,390** recipient rows (to 131,392 · cc 29,499 · bcc 29,499).

## D27. Primary key for `emails`

- **Options:** (a) an integer `id` primary key + `message_id TEXT UNIQUE NOT NULL` · (b) `message_id` as the primary key.
- **I chose (a).** Recipient rows reference a small integer instead of a 45-character string. The unique constraint on `message_id` that the spec requires is still there.
- **Rows affected:** none (design).

## D28. Where the Task 3/4 columns live

- **Options:** (a) columns on `emails` · (b) separate `duplicates` / `notifications` tables.
- **I chose (a).** The spec's `schema.sql` deliverable names these columns, and Task 3 says to flag *the email itself*. The columns:
  - `is_duplicate INTEGER NOT NULL DEFAULT 0`
  - `duplicate_of TEXT REFERENCES emails(message_id)`
  - `similarity_score REAL` (the flagged email's score against its original; NULL otherwise)
  - `notification_sent INTEGER NOT NULL DEFAULT 0`
  - `notification_date TEXT`

  Booleans are 0/1, because SQLite has no boolean type.
- **Rows affected:** none (design).

## D29. The same address repeated within one list

- **Context:** in 185 emails the same address appears twice in `To` (426 extra rows). In 59 emails the same happens in `Cc`, and in `Bcc` too (114 extra rows each).
- **Options:** (a) one row per (email, address, type) · (b) keep every repeat, with a `position` column.
- **I chose (a),** with `PRIMARY KEY (email_id, address_id, recipient_type)`. Being listed twice doesn't make someone a recipient twice. The loader counts and reports the rows it skips.
- **Rows affected (full load):** **654** repeat rows skipped (426 + 114 + 114), exactly as predicted. 191,044 raw → 190,390 stored.

## D30. Making the load safe to re-run

- **Options:**
  - (a) delete and rebuild every run (wipes `notification_sent`, so it risks re-sending emails)
  - (b) `INSERT OR IGNORE` (parser fixes never reach rows already loaded)
  - (c) upsert
- **I chose (c), with my own additions:**
  1. **Upsert:** `INSERT … ON CONFLICT(message_id) DO UPDATE` refreshes all parsed fields and **never touches** `is_duplicate`, `duplicate_of`, `similarity_score`, `notification_sent` or `notification_date`.
  2. **Replace recipients:** for every email loaded, its `email_recipients` rows are deleted and re-inserted. This way a parser change can't leave stale recipients behind.
  3. **Emails no longer in the JSONL** (e.g. a parser change made them fail): the loader reports them. It **deletes** them **unless `notification_sent = 1`**; those it **keeps and reports**, because a notification has already gone out for them.
  4. **`--rebuild` flag** for a clean start. It **refuses** to run if any row has `notification_sent = 1`.
  5. **Report on every run:** emails inserted, updated, deleted, and kept because they were notified; recipient rows written; repeats skipped (D29).
  6. **One transaction:** a crash leaves the database as it was.
- **Stale originals (decided before coding):** what if a stale email is the *original* that other emails point to in `duplicate_of`?
  - Options: (a) delete it and clear the flags of the duplicates pointing to it, so Task 3 regroups them · (b) keep any stale email that is referenced.
  - **I chose (a) with one guard taken from (b):**
    - **Normal case:** delete the stale email. Every email pointing to it gets `is_duplicate = 0`, `duplicate_of = NULL` and `similarity_score = NULL`, so Task 3's next scan regroups them.
    - **Guard:** if the stale email **was notified itself**, or **any email with `notification_sent = 1` points to it**, keep it. Nothing pointing to it is changed, and it's reported as **"stale, kept for notification history"**.
  - **Why the guard:** a notification that has been sent quotes its original's Message-ID and date. That original must stay traceable in the database, or the sent notice would refer to a record that no longer exists.
  - **When this can happen:** only if the parser changes *after* live sends. On a normal run (same JSONL), nothing is stale.
- **Rows affected:** first load: 20,339 inserted, 0 updated, 0 deleted. Second load: 0 inserted, 20,339 updated.

## D31. Date storage

- **Options:** (a) TEXT, ISO-8601 UTC as parsed · (b) INTEGER Unix seconds.
- **I chose (a).** All 20,339 dates have the same 25-character UTC format, so text sorts chronologically. It's readable in query output, works with SQLite's date functions, and the `date` index serves range queries.
- **Rows affected:** none (design).

## D32. Loading library

- **Options:** (a) Python's built-in `sqlite3` with plain SQL · (b) pandas `to_sql` (not installed; can't express the upsert or the address lookup) · (c) SQLAlchemy.
- **I chose (a).** No new dependency, and the loader's SQL matches `schema.sql` line for line. CLAUDE.md's "prefer pandas" is about data manipulation, and this is loading.
- **Rows affected:** none (tooling).

## D33. Failed parses in the database?

- **Options:** (a) no; `error_log.txt` is the deliverable · (b) add a `parse_failures` table.
- **I chose (a).** (b) stays a possible nice-to-have.
- **Rows affected:** none; the 1,323 failures stay in `error_log.txt` only.

## D34. Sample queries

- **I chose six queries** for `sample_queries.sql`, each with an expected-output description:
  1. emails per sender (top 10; expected top: `david.delainey@enron.com`, 2,961)
  2. emails in a date range (October 2001)
  3. emails with Cc recipients (expected 5,471) plus a sample list
  4. all recipients of one email, by type (shows the normalised tables). I used `skilling-j/inbox/1533.` because it has To, Cc and Bcc; my first pick had only To.
  5. the unique constraint: inserting an existing `message_id` fails with `UNIQUE constraint failed`
  6. **(my addition, for later)** duplicate groups: each original with its flagged duplicates and similarity scores, which only returns rows **after Task 3 has run**
- **Rows affected:** none (queries).

## Task 2, steps 1–3 notes (schema + loader)

- `schema.sql`: `emails`, `addresses`, `email_recipients`; all `IF NOT EXISTS`. Booleans have `CHECK (x IN (0,1))`, and `recipient_type` has `CHECK IN ('to','cc','bcc')`. Indexes: the 3 the spec requires, plus `email_recipients(address_id)`, `emails(is_duplicate)` and `emails(duplicate_of)`.
- **`duplicate_of` has no `ON DELETE` action, on purpose.** The loader clears pointing rows *before* deleting an original (D30). If the code ever got this wrong, the foreign key would reject the delete instead of silently leaving a dangling reference.
- `email_recipients.email_id` is `ON DELETE CASCADE`: deleting an email removes its recipient rows.
- **The upsert only lists the parsed columns** (`EMAIL_COLUMNS`). The five Task 3/4 columns aren't in its `SET` clause, so a re-load can't change them.
- **Repeats (D29)** are skipped with `INSERT OR IGNORE` against the primary key and counted. 200-record sample: 22 skipped.
- **The `addresses` table holds recipient addresses only.** `from_address` is a text column (D26), so senders who never *received* mail aren't in `addresses`. The full load has **11,146**; the 13,390 in FINDINGS included senders.
- **Unused-address cleanup (I approved):** at the end of every load, inside the same transaction, `DELETE FROM addresses WHERE id NOT IN (SELECT address_id FROM email_recipients)`. The count removed is reported. Tested: after 100 sample emails went stale, **263** unused addresses were removed and 0 remained.
- **Tests on the sample DB** (planted Task 3/4 state, then a smaller load so 100 of 200 emails went stale):
  - case 1: stale original, no notice → deleted, its duplicate's flags cleared ✔
  - case 2: stale original of a notified duplicate → kept, duplicate untouched ✔
  - case 3: stale and notified itself → kept ✔
  - case 4: live duplicate → flags survive the re-load ✔
  - `--rebuild` refused (exit 1) ✔
  - 0 orphan recipients, 0 foreign-key violations
- The test DB was deleted afterwards (its planted notifications would block `--rebuild`).

## Task 2, step 5 notes (sample queries)

- `sample_queries.sql` runs with `sqlite3 output/enron.db < sample_queries.sql`. Each query has an "Expected output" comment recorded from the full load.
- Results:
  - Q1: top sender `david.delainey@enron.com` (2,961)
  - Q2: 650 emails in October 2001
  - Q3: 5,471 emails with Cc
  - Q4: 1 to / 4 cc / 4 bcc
  - Q5: the INSERT fails with `UNIQUE constraint failed: emails.message_id`
  - Q6: no rows until Task 3 has run
- Q5 fails on purpose, so the CLI exits with code 1; this is documented at the top of the file. The DB file's MD5 is identical before and after running the script, so nothing was written.
- Q3's sample shows the same "Education Survey" email three times (three folders), a live example of the cross-folder copies Task 3 targets.

## Task 2, step 7 notes (DB tests)

- `tests/test_load_db.py`: 7 tests, each on a temporary DB built from synthetic records (`make_record()`). The real `output/enron.db` is never touched.
  1. a re-run updates parsed fields but keeps Task 3/4 state (D30)
  2. recipients are replaced on reload, and unused addresses are cleaned up (D30)
  3. a repeated address in one list is stored once (D29)
  4. a stale original is deleted, and the duplicates pointing to it are cleared; recipients cascade (D30)
  5. a stale original is kept when a notified duplicate points to it (D30 guard)
  6. a plain duplicate INSERT raises `UNIQUE constraint failed` (spec)
  7. `--rebuild` is refused once a notification was sent (D30)
- `pytest -q`: **15 passed** (8 parser + 7 DB) in 0.13 s.
- **Mutation check** (proof the tests can fail): `INSERT OR REPLACE` instead of the upsert → test 1 fails; no recipient `DELETE` → test 2 fails; guard removed → test 5 fails.
- **Why `INSERT OR REPLACE` matters:** it looks like an upsert, but it *deletes* the old row and inserts a new one. That resets every column not supplied, including `notification_sent`, and gives the email a new `id`. Test 1 would catch anyone "simplifying" the loader this way.

---

# Task 3: Duplicate detection decisions

Findings in `docs/FINDINGS_task3.md`. I accepted all the recommendations for D35–D42. D43 waits until Task 4 works. D44 is open.

## D35. Subject normalisation
- **I chose:** strip any chain of `Re:` / `Fw:` / `Fwd:` prefixes (any case, optional `[n]` counter, any spacing), then collapse whitespace and lowercase. Other prefixes (`Mtg:`, `FYI:`, `URG:`) stay as part of the subject.
- **Why:** `RE: Budget` and `Re: budget` are the same thread. Prefix forms seen: `Re:` 3,973 · `RE:` 860 · `FW:` 670 · chains like `Re: FW:` 75.

## D36. Text compared
- **I chose:** the full text (D9) = `body + forwarded_content + quoted_content`, with all whitespace collapsed to single spaces and case kept.
- **Why:** line-wrapping differs between copies; the spec is about content.

## D37. Similarity scorer
- **Options:** `fuzz.ratio` · `fuzz.token_sort_ratio` · `fuzz.partial_ratio` (all from `rapidfuzz` 3.14.6, already pinned).
- **I chose `fuzz.ratio`:** order-sensitive edit similarity, the most literal reading of "body content ≥ 90% similar". `partial_ratio` would score "fyi" against any email containing it at 100. `token_sort_ratio` disagrees with `ratio` on 2,107 of 431,906 block pairs.

## D38. Forming groups
- **Options:** (a) anchor to the original · (b) connected components · (c) complete linkage.
- **I chose (a):** within each (sender, normalised subject) block, go oldest first. Each email is compared to the *original* of each existing group and joins the first group it matches; otherwise it starts a new group.
- **Why:** every flagged email is then ≥ 90 against the original it's linked to, so the report's `similarity_score` is never below the threshold. (b) produced 18 flagged emails scoring below 90 vs their own original. Estimated run time: about 1.5 s.

## D39. Same timestamps: folder copies vs re-sends
- **Tie-break:** order by (date, source_file). When the earliest timestamp is shared, the original is the alphabetically first `source_file`.
- **Options:** (a) flag every copy, as the spec says · (b) collapse same-timestamp copies first (477 groups / 580 flagged) · (c) (a) plus a `same_timestamp` report column and a stats split.
- **I chose (c).** Estimated **4,537 groups / 10,768 flagged**, of which 9,835 are folder copies (same timestamp as the original) and 933 are later repeats (pre-D44 estimates; **final after D44: 4,558 groups / 10,675 flagged; 9,979 folder copies / 696 later**). The extra column follows the 7 spec columns, so it doesn't break them.

## D40. Re-running Task 3
- **I chose:** clear `is_duplicate`, `duplicate_of` and `similarity_score` on all rows with `notification_sent = 0`, then recompute. Notified rows are never changed; if the new grouping disagrees with one, it's reported as a conflict. One transaction.

## D41. Threshold and score format
- **I chose:** `SIMILARITY_THRESHOLD = 90` (inclusive) in the config block. Scores are on a 0–100 scale, rounded to 2 decimals.
- **Which score is stored and reported:** `similarity_score` (DB column and report) is the **full-text** score vs the original (D9, D36). The D44 body check is only a pass/fail gate; its score is **not** stored or reported.

## D42. Outputs
- **I chose:**
  - `src/detect_duplicates.py`
  - `duplicates_report.csv` at the repo root (7 spec columns + `same_timestamp`; one row per flagged email, sorted by original date, then duplicate date). Its `similarity_score` is the full-text score (D41); the D44 body gate isn't reported.
  - stats printed and saved to `output/dedup_stats.json`
  - ~~`--limit` writes to `output/sample_run/`~~ **Amended in step 3 (Claude changed it, flagged it, I approved after review):** `--limit` is a **print-only preview** (no DB writes, no files), because flags written from a block sample would leave the DB half-flagged. Full runs write the flags, the report and the stats.

## D43. Sender-alias report (nice-to-have)
- **Deferred until Task 4 works.** Count the groups that would merge if aliases (`lavorato@` ↔ `john.lavorato@`) were combined, without changing any flags.

## D44. Also require the primary body to be ≥ 90 similar
- **Context (my D9 revisit):** full-text similarity can pass two *different replies* because they quote the same long thread. Should the primary `body` also have to be ≥ 90?
- **Rule for empty bodies (decided, must be explicit in code, not left to rapidfuzz's behaviour with empty strings):** if **both** primary bodies are empty (pure forwards), the body check **passes** and full text alone decides.
- **Measured** (anchor grouping, D35–D38):
  - Current rule: 4,537 groups / 10,768 flagged. 684 flagged pairs have both bodies empty (pass).
  - **244 flagged emails would fail** the extra check. **240 have a later timestamp** than their original; 4 share it. Body scores: <50: 154 · 50–80: 45 · 0 (one body empty or no overlap): 45, of which 35 have exactly one empty body.
  - Recomputed with both checks: **4,558 groups / 10,675 flagged (net −93)**. Un-flagged emails start their own group (+21) or match a different original.
- **Examples it would un-flag** (all Delainey, different replies over the same quoted thread):
  - "Great words": full text 94.4, body 48.0 ("Mike Moulton has been pursuing an idea…" vs "Mike, I forwarded your interest to Whalley, McConnel and McMahon…")
  - "Re: Spring Business Meeting": full text 97.6, body 14.4 ("John, what do you want to do with this?…" vs "fyi, action")
  - "Re: GE Plastics Facts": full text 90.6, body 50.5 ("…GE is willing to play on the Selkirk asset…" vs "…if this deal is such a long put why did you push me into this process?…")
- **I chose: yes, add the body check as a pass/fail gate.** An email is a duplicate only if its full text is ≥ 90 **and** the body gate passes:
  - **both** primary bodies empty → **pass** (full text decides)
  - **exactly one** empty → **fail** (one message has the sender's own words, the other doesn't; 35 cases)
  - otherwise the body `fuzz.ratio` must be ≥ 90

  The empty cases are coded explicitly, not left to rapidfuzz's behaviour with empty strings.
- **Why:** it catches different replies over the same quoted thread. Example: Delainey, **"Re: Spring Business Meeting"**: the original "John, what do you want to do with this?…" vs the later "fyi, action" scores **97.6% on full text but 14.4% on body**. They are different messages.
- **Rows affected (confirmed by the step 2 run):** 4,537 groups / 10,768 flagged → **4,558 / 10,675**. **244 emails** un-flagged (**253 comparisons** rejected), **240** of them with a later timestamp than their original. Later-timestamp flagged emails after D44: **696** (was 933).

## Task 3, steps 1–2 notes (blocks + grouping)

- `src/detect_duplicates.py` steps 1–2 read the DB, build blocks, and group in memory. **No DB writes yet** (MD5 of `enron.db` unchanged).
- **Full run (2.6 s):**
  - 20,339 emails · 8,227 blocks · 3,907 candidate blocks
  - **4,558 groups · 10,675 flagged** · average group size 3.34
  - exactly the D44 estimate
- **Split (D39), final:** 9,979 flagged emails share their original's timestamp (folder copies); **696** are later (re-send candidates). Before D44 the split was 9,835 / 933. Un-flagged emails re-group, so both numbers move. **696 is the final later-timestamp count used in all docs.**
- **D44 body gate:** **253 comparisons** rejected, affecting **244 emails** (the estimate's count). One email can be rejected against more than one group's original.
- **Lowest flagged full-text score: 90.08** ≥ 90 ✔ (D38: no flagged email scores below the threshold against its original).
- **`--limit N` samples whole blocks (sender + normalised subject), not emails.** I agreed this after review. Why: sampling emails would split a group's members between the sample and the rest, and **undercount duplicates** (an email whose original wasn't sampled would look unique). Sampling whole blocks keeps every group intact. 300 blocks → 324 groups / 766 flagged. A `--limit` run only prints; it never writes to the DB.

## Task 3, steps 3–5 notes (flags, report, stats)

- **`write_flags()`** (one transaction, D40):
  - clears `is_duplicate` / `duplicate_of` / `similarity_score` on every row with `notification_sent = 0`
  - sets them for each flagged email
  - leaves notified rows alone, and lists any whose new result differs (conflicts: **0**)
- **The report and stats are built from the DB *after* writing,** not from memory, so they show exactly what's stored (including any notified rows kept unchanged).
- **Full run:**
  - **4,558 groups · 10,675 flagged · average group size 3.34 · largest group 68**
  - same timestamp **9,979** · later **696**
  - scores: 100 → 10,293 · 95–<100 → 231 · 90–<95 → 151 · lowest **90.08**
  - D44 body gate: 253 comparisons rejected (244 emails)
- **Task 4 targets** (the latest duplicate of each group, by date then source_file): **4,558**, of which **389** are later than their original. The rest are same-timestamp folder copies.
- **Checks on the DB:**
  - 10,675 flagged, pointing at 4,558 distinct originals
  - 0 chains (no original is itself flagged)
  - 0 flagged rows missing `duplicate_of` or a score; 0 leftovers on non-flagged rows
  - 0 duplicates earlier than their original; 0 with a different sender
  - integrity and foreign-key checks clean
- **Re-run:** flags (hash of every row's Task 3 columns) and `duplicates_report.csv` are **byte-identical** on a second run.
- `duplicates_report.csv`: 10,675 rows + header; `same_timestamp` True 9,979 / False 696.

## Task 3, steps 6–7 notes (spot-check, query 6)

- **Spot-check:** 6 groups. Every flagged row shown was **re-scored from the raw email file** with the Task 1 parser (`parse_file()`), not from the DB text. Sender and normalised subject were re-checked too. **11 of 11 scores match** the stored ones. Tables are in `docs/FINDINGS_task3.md`.
  - A. folder copies (same timestamp): "Education Survey", 3 copies, 100 ✔
  - B. genuine later re-send: outlook.team "4-URGENT - OWA Please print this now.", Jan 19 → May 1 2001, 100 ✔
  - C. a "later" copy exactly **+12 h** after its original: Lavorato "Re: Canada Positions by Trader", `_sent_mail` → `sent_items`. See D45.
  - D. **template false positive (confirmed):** Delainey "Approval for reviewer", 68 emails. A word diff of original vs a 91.19 member shows the only changes are the date and the employee (`MAYS,WAYNE E` → `DEFFNER,JOSEPH M`). The same review form about different people. Flagged per the spec's 90% rule; documented, not changed.
  - E. near match 90.08: Kay Chapman "Staff Meeting". The June 30 "NO STAFF MEETING TODAY… HAPPY HOLIDAY" notice matched the June 2 meeting reminder (a reminder template), so it's also a template false positive.
  - F. blank subject: Delainey "Chris, I need your 2000 accomplishments…" vs "Barry need your 2000 accomplishment…" (91.01), the same request to **different people**. The spec's rule doesn't look at recipients.
- **Query 6** filled with real output: 4,558 groups; the largest is "Approval for reviewer" (67 duplicates, min 91.2).

## D45. "Later" duplicates that are exact whole-hour shifts (export clock errors)

- **Finding (step 6):** of the **696** flagged emails that are later than their original, **254** have a 100% full-text match and a gap of an **exact whole number of hours ≤ 14**: +12 h: 212 · +10 h: 34 · +9 h: 4 · others: 4. All have `:00` seconds. Folder pairs:
  - Lavorato `_sent_mail` → `sent_items`: 109
  - Lavorato `all_documents` → `sent_items`: 94
  - Skilling `all_documents` → `inbox`: 26
  - Skilling `all_documents` → `deleted_items`: 10
- **Interpretation:** the same email exported twice, once from Lotus Notes (`.nsf` folders) and once from Outlook (`.pst` folders), with one export's clock shifted (AM/PM or time zone). Probably not a re-send. Example: "Re: Canada Positions by Trader", body "Thanks", 20:11 → 08:11 the next day.
- **Why it matters:** the spec says the latest email "is likely a re-send". For these 254, the "later" one is just the other export's copy. This also affects Task 4's 389 "real re-send" targets.
- **Options:** (a) keep the dates as given and follow the spec (no change) · (b) treat these as folder copies in the re-send counts, flags unchanged · (c) (a) plus an extra report column `likely_export_copy` and a stats line.
- **I chose (c).** Flags don't change. The report gets a `likely_export_copy` column, and the stats count real re-sends separately.
- **Rule (exact):** `likely_export_copy = true` when **all** of these hold:
  1. `similarity_score` is **100**
  2. the duplicate is later than its original by an **exact whole number of hours, more than 0 and at most 24** (`EXPORT_COPY_MAX_HOURS = 24` in the config)
  3. **one copy is in a Lotus Notes folder and the other in an Outlook folder.** Notes vs Outlook is judged per email from its `X-Folder`: Notes exports contain `\Notes Folders\` (e.g. `\John_Lavorato_Dec2000\Notes Folders\'sent mail`), Outlook `.pst` exports don't (e.g. `\jlavora\Sent Items`). It's judged per email, not per folder name, because some folders (`personal`, `mark`, `jean`, …) hold both kinds.
- **Evidence:**
  - Counts: **254** later duplicates match the rule: **212 at +12 h**, **34 at +10 h**, 4 at +9 h, and 1 each at +4, +5, +13 and +14 h. All have `:00` seconds.
  - Folder pairs: Lavorato `_sent_mail`/`all_documents` (Notes) → `sent_items` (Outlook): 203; Skilling `all_documents` → `inbox`/`deleted_items`: 36.
  - Example: "Re: Canada Positions by Trader", body "Thanks", Notes copy 20:11 vs Outlook copy 08:11 the next day.
  - Widening the gap limit from 14 h to 24 h added no cases (still 254).
- **Rows affected:** 0 flags changed. As first built (score = 100, exact hours): 254 export copies, 442 real re-sends, 141 real re-send targets. **After the amendment below** (score ≥ 99, within 60 s): **280 / 416 / 118**.

## D46. Recipient overlap column

- **Context:** the spec's duplicate rule ignores recipients. In case B (the OWA notice, which I checked against the raw files myself), the original went to 15 people and the "duplicate" to 88, with none in common: a mass announcement sent in batches, not an accidental re-send.
- **I chose:** add `recipient_overlap` to `duplicates_report.csv`. Flags don't change (same approach as `same_timestamp` and `likely_export_copy`).
- **Definition:** share of **To + Cc** recipients the duplicate and its original have in common, 0–100: |A ∩ B| / |A ∪ B| × 100 (Jaccard), rounded to 1 decimal. Bcc is ignored because it copies Cc (D7). Both empty → 100 (can't happen: To is mandatory, D4).
- **Distribution** (stats):

  | Band | All 10,675 flagged | The 442 real re-sends |
  | --- | --- | --- |
  | 100 | 10,404 | 246 |
  | 50–<100 | 74 | 67 |
  | >0–<50 | 29 | 20 |
  | 0 | 168 | 109 |

- **Sanity check, case B:** `recipient_overlap = 0.0` (15 vs 88 To recipients, disjoint). Matches my manual check.
- **Rows affected:** 0 flags changed; one new report column.

## Task 3, step 8 notes (tests)

- `tests/test_detect_duplicates.py`, 8 tests:
  - subject normalisation (D35)
  - different replies over the same quoted thread → not duplicates (D44)
  - empty-body gate rules (D44)
  - anchor grouping: chain A≈B≈C with A vs C < 90 → C not in A's group (D38)
  - tie-break on identical timestamps, either input order (D39)
  - a notified row keeps its flags on a re-run that finds nothing, and is reported as a conflict (D40)
  - `likely_export_copy` (+12 h Notes/Outlook → true; 3 days, same kind, 99.5 or 12.5 h → false) (D45)
  - `recipient_overlap` (identical 100, disjoint 0, partial 33.3) (D46)
- `pytest -q`: **23 passed** (8 parser + 7 DB + 8 dedup).
- **Mutation check:** chaining instead of anchoring → caught; no tie-break → caught; notified rows wiped → caught; no Notes/Outlook condition → caught. For D44: both-empty → fail, one-empty → pass, and no body gate → all caught.
- **One mutation was not caught, and why that's fine:** replacing the explicit D44 empty-body rule with rapidfuzz's built-in behaviour. In rapidfuzz 3.14.6, `ratio('', '') = 100` and `ratio('text', '') = 0`, which happens to be exactly our rule, so the outcomes are identical. The tests check outcomes. The explicit rule protects us if a library update or a different scorer changed how empty strings score; the tests would then fail.

---

# Task 4: Notification decisions

Findings in `docs/FINDINGS_task4.md`. I accepted the recommendations for D47, D49, D50, D51, D52, D54 and D56. D48, D53 and D55 have my changes below.

## D47. Drafts vs live sends (the spec conflicts with itself)
- **Conflict:** §4.2 says one notification **per duplicate group** (4,558). §7 says draft `.eml` files for **all flagged duplicates** (10,675).
- **I chose:** drafts for **every flagged duplicate** (10,675), each filled with that email's own fields. **Live sends only for one target per group** (the latest duplicate), and only the selected ones (D50).

## D48. Committing the drafts (my rule)
- **I chose:** after generating, **measure the total size** of the 10,675 drafts. Use content bytes, which is what git stores; disk usage overstates small files because of block size.
  - **≤ ~25 MB:** commit them all as plain files (`output/replies/` is a named deliverable).
  - **> ~25 MB:** zip into one archive (`output/replies.zip`), commit that, and git-ignore the loose files.
- **Rows affected:** none (output files). The measured size and the outcome get recorded at build time.

## D49. Live-send cap
- **I chose:** `--max-sends N`, **default 10**, hard maximum **100** per run (`MAX_SENDS_DEFAULT`, `MAX_SENDS_LIMIT` in the config). Gmail allows about 500/day, and all sends go to one inbox.

## D50. Which targets go live
- **I chose: real re-sends only** (later than the original, not `likely_export_copy`): **118** targets after the D45 amendment (141 before). Ordered by `recipient_overlap` ↓, then `similarity_score` ↓, then duplicate date ↑. Folder and export copies get drafts only.

## D51. Recipient override
- **I chose:** live `To` is **always `NOTIFY_TO`**, and the run **refuses** if it's unset. Drafts use the real sender (the template exactly). `send_log.csv` adds `intended_recipient`. The Enron addresses are never contacted.

## D52. Subject line
- **I chose:** strip existing reply/forward prefixes from the original subject (the D35 regex), then `[Duplicate Notice] Re: <subject>`. A blank subject becomes `[Duplicate Notice] Re: (no subject)`. **Amended after the dry run (my decision):** the body's `Subject:` line also shows `(no subject)` for blank subjects, so it's consistent with the header. Otherwise the body keeps the original subject exactly.
- **Rows affected:** 1,456 targets avoid `Re: Re:`; 321 blank subjects get `(no subject)`.

## D53. Draft `.eml` format (with my checks)
- **What the spec says (§4.2, exact wording):** the header is `References: <message_id_of_latest_duplicate>`. It names only **References**, and its value is the Message-ID of the **latest duplicate** (the group's target), not the original.
- **I chose:**
  - **`References:` = the flagged email's own Message-ID.** For the group's target draft (and every live send), that *is* `message_id_of_latest_duplicate`, exactly as the spec says. For the other drafts in a group (D47), each draft is about its own flagged email, so it references that email.
  - **`In-Reply-To:` = the same value.** The spec doesn't list it. I add it so mail clients thread the notice, and because the MCP server sets both for live sends; drafts and sends should match. Documented as a small addition.
  - Other headers: `From: Email Deduplication System <dedup@localhost>` (config), `To:` (D51), `Subject:` (D52), `Date:` (current UTC, RFC 2822), `Message-ID:` (new, `@dedup.local`), `Content-Type: text/plain; charset=utf-8`.
  - Body: the §4.2 template exactly. Dates appear as `2001-05-01 00:11:00 UTC`; the score as `100.00%` (full-text score, D41).
- **Safe file names:** Message-IDs contain `<`, `>` and `@`. File name = the Message-ID with `<` and `>` removed, `@` replaced by `_at_`, and any other character outside `A–Z a–z 0–9 . _ -` replaced by `_`, plus `.eml` (e.g. `12846475.1075854481614.JavaMail.evans_at_thyme.eml`). The generator **checks the names are unique** after this cleanup and stops if two collide.

## D54. Re-run safety
- **I chose:**
  - The drafts folder is cleared and rebuilt on every run.
  - Live: only targets with `notification_sent = 0` are eligible. `notification_sent = 1` and `notification_date` are set **only after a confirmed send**; a failed send leaves the DB unchanged.
  - `send_log.csv` is append-only, with columns `timestamp, recipient, subject, status, error` (spec) + `intended_recipient, duplicate_message_id`.
  - With D30/D40, notified rows are never wiped.

## D55. How the pipeline calls MCP (with my change)
- **I chose:** a Python MCP client over stdio. `src/notify.py` starts `mcp_server/gmail_server.py` with the project's Python, opens one `ClientSession` per run, and calls `send_email` once per selected target, sequentially.
- **Pause of about 1 second between live sends** (`SEND_DELAY_SECONDS = 1`; my change from the proposed 2 s).
- **Errors:**
  - auth (`535`) → stop the run
  - quota / rate limit (`5.4.5`, `421`, "quota") → stop; the remaining targets stay unsent
  - transient (timeout, connection) → retry up to 3 times with backoff (2, 4, 8 s)
  - anything else → log `failed`, continue

  Every outcome is logged.

## D56. Commands
- **I chose:** `src/notify.py`, **dry run by default** (drafts only, no network, no DB writes); `--send-live [--max-sends N]` sends. Plus a top-level `main.py` that runs parse → load → dedup → notify (dry run unless `--send-live`), for the §5 single command.

## Task 4, steps 1–3 notes (targets, notice builder, dry run)

- `src/notify.py` (dry run only so far; `--send-live` refuses with "not built yet"):
  - `read_notices()` reuses `detect_duplicates.read_flagged_pairs()`, which already computes `same_timestamp`, `likely_export_copy` and `recipient_overlap`
  - it marks each group's target (latest by date, then source_file)
  - `build_message()` builds the D53 notice; `write_drafts()` clears and rewrites `output/replies/`
- **Counts:** 10,675 flagged → **10,675 drafts** · 4,558 targets · **141** live-eligible real re-send targets · 0 already notified.
- **D48 outcome:** total draft size **11.7 MB** (content bytes; 42 MB on disk because each small file takes a full disk block) → **≤ 25 MB → commit all** as plain files.
- **Checks:**
  - all 10,675 drafts parse with Python's `email` parser
  - every `References` matches a row in `duplicates_report.csv`, and `In-Reply-To` = `References`
  - every file name = `safe_filename(References)`; no collisions
  - every subject starts `[Duplicate Notice] Re: `; 0 doubled `Re: Re:` / `Re: FW:`; 1,070 drafts use `(no subject)`
  - all `text/plain; charset=utf-8`
  - DB MD5 unchanged (the dry run writes nothing to the DB)
  - run time about 12 s
- **The template's spacing:** ASSIGNMENT.md's text (converted from a document) puts a blank line after every template line. I used the template's evident structure (blank lines between the sections, none inside a section).
- **A blank subject in the body:** first left empty; **changed after review:** it now also shows `(no subject)`, like the header (D52 amended).
- **Drafts change on every run:** `Date:` (current time, per the spec) and `Message-ID:` differ on each run, so all 10,675 files show as modified in git after any re-run. **I decided:** commit code and docs now; commit `output/replies/` **once, from the final run**.
- **`Date:` header:** current time in **UTC with the `+0000` offset**, e.g. `Date: Fri, 06 Nov 2026 02:35:07 +0000` (`email.utils.format_datetime` on a UTC datetime). Verified in the drafts.

## Task 4, steps 4–6 notes (selection, MCP client, send log), built; no sends yet

- **Added to `src/notify.py`:**
  - `select_live_targets()` (D50 order, D49 cap); `--preview` lists the selection and stops
  - `send_live()`: one MCP `ClientSession` over stdio to `mcp_server/gmail_server.py`; `call_send_email()` retries transient errors (2/4/8 s); `classify_error()` sorts errors into auth / quota / transient / other; auth or quota stops the run; ~1 s pause between sends
  - `append_send_log()` (append-only `output/send_log.csv`); `mark_notified()` sets `notification_sent` / `notification_date` only after a confirmed send
  - `NOTIFY_TO` is read by the program via `python-dotenv` at run time, never printed; the run refuses if it's unset
- **Checks so far:** `--preview` changes nothing (DB MD5 unchanged; no `send_log.csv` created); `--max-sends 500` is refused (D49).

## D45 amendment: near-100 export copies (found in the live preview)

- **Finding:** the `--preview` top 10 included probable export copies that D45 misses only because it requires a score of **exactly 100**:
  - #10 Lavorato "2001 ENA/EGM/EIM CUSTOMER SKI PROGRAM": 10:18 → 22:18, +12 h, Notes/Outlook, 99.81
  - #9 "Clinton Energy Vacation Policy": +9 h, Notes/Outlook, 99.85
  - #7 Kean "California's dim bulbs": 14:00:00 → 19:00:01, +5 h **plus 1 s**, Notes/Outlook, 99.98
- **Options measured** (696 later duplicates):

  | Rule | Export copies | Real re-sends | Live-eligible targets |
  | --- | --- | --- | --- |
  | (a) as built: score = 100, exact whole hours | 254 | 442 | 141 |
  | (b) score ≥ 99, exact whole hours | 265 | 431 | 131 |
  | (c) score ≥ 99, within **60 s** of a whole number of hours (1–24 h) | 280 | 416 | **118** |

- Under (c) the top 10 has no whole-hour Notes/Outlook pairs: double deliveries seconds apart (YPO survey +8 s, PGS +1 s), a 3-month re-send (Hawkes Peers), next-day minutes and invoice reminders, and a campaign mass-mail with identical recipients.
- **I chose (c): amend D45.** `likely_export_copy = true` when **all** of these hold:
  1. `similarity_score` **≥ 99** (`EXPORT_COPY_MIN_SCORE`; was exactly 100)
  2. the gap is **within 60 s** (`EXPORT_COPY_TOLERANCE_SECONDS`) of a whole number of hours **between 1 and 24**
  3. one copy is in a Notes folder and the other in an Outlook folder (unchanged)
- **The three examples that prompted it** (all now `likely_export_copy = true`): #10 "2001 ENA/EGM/EIM CUSTOMER SKI PROGRAM" (+12 h, 99.81), #9 "Clinton Energy Vacation Policy" (+9 h, 99.85), #7 "California's dim bulbs" (+5 h + 1 s, 99.98).
- **Re-run of Task 3 confirms (c):** 280 export copies / **416 real re-sends** / **118 live-eligible targets**.
- **Flags don't change:** the duplicate flags (`is_duplicate`, `duplicate_of`, `similarity_score`) are byte-identical before and after (hash of every row). Only the report column `likely_export_copy` and the stats change.
- Tests updated: +12 h at 99.81 → true; +12 h + 1 s → true; +12 h + 61 s → false; score 98.9 → false. 23 pass.

## D57. "Email Deduplication System" display name on live sends

- **Context:** my first live send arrived with `From: swara.awsm@gmail.com` only (see `docs/live_send_proof.png`), while the drafts show "Email Deduplication System".
- **I chose:** in `mcp_server/gmail_server.py`, `From` = `formataddr(("Email Deduplication System", GMAIL_USER))` → `Email Deduplication System <my Gmail>`, so live sends match the drafts. The sending account is unchanged. `FROM_DISPLAY_NAME` is a constant at the top of the server.
- **Applies to:** sends 2–10 (the pipeline starts a fresh server process per run); send 1 went out before the change.

## D58. Total live-send budget across runs (Claude added this, flagged it, I approved by asking for 0 on a re-run)

- **Context:** D49 caps sends **per run**. After 10 sends, a further `--send-live` would pick the next 10 new targets (108 eligible), not send 0. It would never send anything *twice*, but it would keep sending.
- **Change:** `TOTAL_SEND_BUDGET = 10` in `notify.py`, counted from the DB (`notification_sent = 1`). Each run sends at most `min(--max-sends, budget left)`; when the budget is used up, it prints "0 emails sent" and exits.
- **Why from the DB:** the budget survives restarts and can't drift from what was actually sent.

## Task 4, step 7 notes (live run)

- **Send 1** (`--max-sends 1`): YPO forum survey (the 8-second double delivery). **I checked it myself** in Gmail (subject, body and score correct; `docs/live_send_proof.png`), in `send_log.csv`, and in the DB (`notification_sent = 1`, `notification_date` 03:33:39, the same second as the log row).
- **Sends 2–10:** PGS Seminars · Hawkes Peers · Rally against terrorism · October 01 Meeting Minutes · Past Due Invoice · Enron Image 2000 Video · Demand Ken Lay Donate Proceeds (×2, different senders) · 5/18/01 Gas Violations FINAL. **9 sent, 0 failed**, about 1 s apart, all to `NOTIFY_TO`.
- **Proof of no double sends:** a further `--send-live` → "10 of 10 already sent; 0 left … **0 emails sent**". `send_log.csv` has 10 rows, all `sent`, with 10 distinct `duplicate_message_id`s, each matching its DB `notification_date` to the second.
- **D30/D40 proven on real data:** `python src/load_db.py` (0 inserted, 0 stale) and `python src/detect_duplicates.py` (0 conflicts) left the 10 notified rows byte-identical; `load_db.py --rebuild` was **refused** (10 notified).

## Task 4, step 8 notes (`main.py` + clean end-to-end run)

- **`main.py`** runs the four scripts as subprocesses with the same Python: `src/parse_emails.py` → `src/load_db.py` → `src/detect_duplicates.py` → `src/notify.py`. `--send-live`, `--preview` and `--max-sends` are passed to `notify.py`. A failing step stops the pipeline (its exit code is passed on). Dry run by default.
- **Why subprocesses, not imports:** each script stays exactly as tested and runnable on its own, and `main.py` has no logic of its own to explain.
- **Clean run:**
  1. moved the generated outputs aside into `output/backup_before_clean_run/` (git-ignored) with MD5 checksums
  2. ran `python main.py` from scratch
  3. compared the fresh outputs with the originals
  4. restored the originals

| Documented | Fresh run |
| --- | --- |
| 20,339 parsed / 1,323 failed | 20,339 / 1,323 ✔ |
| DB: 20,339 emails / 11,146 addresses / 190,390 recipients | same ✔ |
| 4,558 groups / 10,675 flagged | 4,558 / 10,675 ✔ |
| 280 export copies / 416 real re-sends / 118 live targets | same ✔ |
| 10,675 drafts, 11.7 MB | 10,675, 11.7 MB ✔ |

- **Byte-identical to the originals:** `parsed_emails.jsonl`, `sample_parsed_emails.jsonl`, `error_log.txt`, `duplicates_report.csv`; `extraction_stats.json` (ignoring the run timestamp); the DB's emails, dedup flags and recipients (row hash, excluding the notification columns). The drafts have the same 10,675 names and are identical apart from `Date:`/`Message-ID:`.
- **The one expected difference:** `dedup_stats.json` `rows_flagged_this_run` is 10,675 fresh vs 10,665 originally, because in the original DB, Task 3 skipped rewriting the 10 notified rows (D40).
- **Runtime:** parse 17.3 s · load 3.0 s · dedupe 4.6 s · notify (dry run) 12.8 s · **total 37.7 s**.
- **Restore:** the originals (DB with **10 notifications**, the outputs, the 10,675 drafts, `send_log.csv`) were moved back and **all checksums match**. The fresh copies were replaced. The backup folder was then empty and removed.
