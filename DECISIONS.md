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
