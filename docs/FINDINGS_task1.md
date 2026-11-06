# Task 1 findings: step reports

One section per parser step, appended as I go. Each records what I did, the counts, and what was unexpected. Decisions are in DECISIONS.md.

---

## Step 1: Discover files

- Walked the 5 mailboxes (`discover_files`). Found **21,662** files: lay-k 5,937 · skilling-j 4,139 · whalley-l 3,335 · lavorato-j 4,685 · delainey-d 3,566.
- `--limit N` picks N files evenly spaced through the sorted list (D15). The 200-file sample covers all 5 mailboxes and 41 folders.
- Unexpected: nothing.

## Step 2: Read each file safely

- Bytes → CRLF to LF → Windows-1252 decode (`errors="replace"`) → `email.message_from_string`. Quoted-printable is decoded only when declared (D13).
- **21,662 of 21,662 read, 0 errors.** 924 QP bodies decoded. 0 replacement characters, 0 parser defects.
- Unexpected:
  - `\x01` garbled punctuation in 612 bodies. Fixed only `\x01,` → `'` (D16): 2,231 replacements in 496 bodies. 2,387 other `\x01` remain in 290 bodies.
  - 96 bodies start with a header-like line, but only 12 are a real Notes block (D17).

## Step 3: Header fields

- `extract_header_fields`: all spec header fields; dates in UTC ISO; lowercased address lists; subjects unfolded onto one line.
- **21,662 processed, 0 errors.** `from_address` 21,660 (2 invalid, D14) · `to_addresses` 20,364 (1,298 without, D4) · `cc_addresses` 5,594 · subject non-blank 20,173 (1,489 blank, D5) · 28 placeholder dates (D6).
- Unexpected:
  - D6 correction: the placeholder is 1 Jan 1980 UTC, not the Unix epoch.
  - Python 3.13 strict `getaddresses` was dropping whole address lists. Switched to lenient mode (D18): 2 Cc + 2 Bcc lists recovered, 6 junk tokens dropped, 1 double-`@` address lost (documented).
- Expected failures for step 6: **1,323** (1,293 no `To` only · 23 placeholder only · 5 both · 2 invalid `From`).

---

## Step 4: Body split (body / forwarded / quoted)

**What I did:** `split_body()` in `src/parse_emails.py`:

1. If the body *starts with* a Lotus Notes header block (`From:  Name   date` … `Subject:`), it strips the block (D17).
2. It looks for six marker types and cuts at the **earliest** one found (D8).
3. Text above the cut is `body`. Everything from the cut on goes to `forwarded_content` (Notes forward) or `quoted_content` (any reply marker).

**Counts: emails by the marker the split was made at** (each email is counted once):

| First marker | Sends rest to | Emails | Example cut line |
| --- | --- | --- | --- |
| none (whole text is `body`) | — | 14,752 | |
| `notes_forward` | forwarded | 3,353 | `---------- Forwarded by Steven J Kean/HOU/EES on 10/18/99 08:46 AM` |
| `outlook_original` | quoted | 1,487 | `-----Original Message-----` |
| `notes_reply_one_line` | quoted | 1,153 | `"Gene Vaughan" <EHVaughan@vnsm.com> on 03/23/2001 05:32:28 PM` (+ `To:` within 3 lines) |
| `notes_reply_two_line` | quoted | 463 | `Vince J Kaminski@ECT` / `MM/DD/YYYY HH:MM AM` / `To:` (**the new two-line form**) |
| `gt_quoted` | quoted | 293 | `> The editing process has been completed…` |
| `notes_reply_from_line` | quoted | 161 | `From:  Tina Rode @ ECT      09/25/2000 09:38 AM` (mid-body) |
| **Total** | | **21,662** | |

- D17 leading Notes blocks stripped: **12** (exactly the 12 expected).
- `body` is empty after the split in **1,101** emails. These are pure forwards or replies with no text of the sender's own. D9 (similarity on the full text) covers them in Task 3.
- 200-file sample first: no marker 139 · notes_forward 30 · outlook_original 14 · one-line 9 · two-line 4 · `>` 3 · from-line 1 · 0 errors.
- Full run: 21,662 processed, 0 errors, about 11 seconds.

**Unexpected / not sure:**

1. **`>` false positives (36 emails).** Some single lines start with `>` but aren't quotes: `  >40 GW   $250/MWh` (a table meaning "greater than"), `>>>  Town Hall Meeting <<<` (a decorative heading), and `>$60 to $80M…` (ambiguous). Requiring at least **2 consecutive** `>` lines would stop these 36 from splitting; the other 257 `>` splits are unchanged. → D19, open.
2. **A Notes date variant I don't catch (5 emails):** 24-hour time with a zone name, e.g. `From: John J Lavorato on 23/01/2001 15:19 CST`. Today these stay entirely in `body`. → D20, open.
3. **Other known misses (about 50 emails):** embedded raw message headers inside a body (`From: "Joseph G.Galea" <…>` / `Date: Thu, 31 May 2001 …`, inline MIME attachments). These have no Notes/Outlook marker and stay in `body`. I'm not adding a rule for them.
4. The `notes_reply_from_line` marker (161) wasn't in my original D8 list. It's the mid-body form of the Notes `From:  Name   date` header, so I treat it as a reply marker like the others.

**Before/after samples** (to check by eye):

### Nested forward (Notes, 4 levels)

`maildir/lay-k/elizabeth/23.`: first marker = `notes_forward`, D17 block stripped = False

**Before (raw body, first 14 lines):**

```
---------------------- Forwarded by Steven J Kean/HOU/EES on 10/18/99 08:46 
AM ---------------------------


Karen Denne@ENRON
10/18/99 07:08 AM
To: Steven J Kean/HOU/EES@EES
cc:  
Subject: Translation of articles


---------------------- Forwarded by Karen Denne/Corp/Enron on 10/18/99 07:07 
AM ---------------------------

… (37 more lines)
```

**After: `body`:**

```

```

**After: `forwarded_content`:**

```
---------------------- Forwarded by Steven J Kean/HOU/EES on 10/18/99 08:46 
AM ---------------------------


Karen Denne@ENRON
10/18/99 07:08 AM
… (45 more lines)
```

**After: `quoted_content`:**

```
(none)
```

### D17 email (leading Notes block stripped, then two-line Notes reply header)

`maildir/delainey-d/sent/333.`: first marker = `notes_reply_two_line`, D17 block stripped = True

**Before (raw body, first 14 lines):**

```
From:  David W Delainey                           08/22/2000 10:02 AM
	

Sent by: Kay Chapman
To: Ina Rangel/HOU/ECT@ECT
cc:  
Subject: Re: ENA Management Committee  

This is the original memo sent to all the committee members from Dave.  I 
then sent out another one cancelling the Staff Meeting for all those not 
included in this memo. I also sent out a memo regarding the newly formed ENA 
Management Committee,  including the assistants,  so everyone would be on 
board.

… (42 more lines)
```

**After: `body`:**

```
This is the original memo sent to all the committee members from Dave.  I 
then sent out another one cancelling the Staff Meeting for all those not 
included in this memo. I also sent out a memo regarding the newly formed ENA 
Management Committee,  including the assistants,  so everyone would be on 
board.

Let me know if this isn't what you needed.

Thanks,

Kay
```

**After: `forwarded_content`:**

```
(none)
```

**After: `quoted_content`:**

```
David W Delainey
08/15/2000 02:05 PM
To: Tim Belden/HOU/ECT@ECT, Kevin M Presto/HOU/ECT@ECT, John 
Arnold/HOU/ECT@ECT, Scott Neal/HOU/ECT@ECT, Hunter S Shively/HOU/ECT@ECT, 
Phillip K Allen/HOU/ECT@ECT, Janet R Dietrich/HOU/ECT@ECT, Christopher F 
Calger/PDX/ECT@ECT, W David Duran/HOU/ECT@ECT, Raymond Bowen/HOU/ECT@ECT, 
… (28 more lines)
```

### Outlook reply (-----Original Message-----)

`maildir/lay-k/sent_items/2.`: first marker = `outlook_original`, D17 block stripped = False

**Before (raw body, first 14 lines):**

```
Hasan:

I fully understand and agree with your comments.  Unfortunately, I did not see the "Travel Secruity Update" e-mail before it was sent out.  We will do better.

Ken

 -----Original Message-----
From: 	Kedwaii, Hasan  
Sent:	Friday, September 21, 2001 11:59 AM
To:	Lay, Kenneth
Subject:	RE: Media Reports

Sir,
I read your note with great deal of interest and care.  I was pleasantly surprised to see that this email was devoid of any stereotypical remarks that are so prevalent in the mass media today.
… (20 more lines)
```

**After: `body`:**

```
Hasan:

I fully understand and agree with your comments.  Unfortunately, I did not see the "Travel Secruity Update" e-mail before it was sent out.  We will do better.

Ken
```

**After: `forwarded_content`:**

```
(none)
```

**After: `quoted_content`:**

```
-----Original Message-----
From: 	Kedwaii, Hasan  
Sent:	Friday, September 21, 2001 11:59 AM
To:	Lay, Kenneth
Subject:	RE: Media Reports

… (22 more lines)
```


### Step 4 rerun after review

- **D19 applied** (at least 2 consecutive `>` lines): `gt_quoted` 293 → **257**, `no_marker` 14,752 → **14,788**. The other counts are unchanged: notes_forward 3,353 · outlook_original 1,487 · notes_reply_one_line 1,153 · notes_reply_two_line 463 · notes_reply_from_line 161. **Sum = 21,662** ✔.
- **D20, known miss** (24-hour Notes date, kept in `body`): `lavorato-j/all_documents/798.`, `lavorato-j/notes_inbox/35.`, `lavorato-j/offsite/11.`, `lay-k/all_documents/566.`, `lay-k/notes_inbox/355.`
- `notes_reply_from_line` approved as a D8 amendment. The ~50 inline raw headers stay in `body` (agreed, documented).

---

## Step 5: has_attachment

**What I did:** `has_attachment()` returns true if the text names an attached file in either style:
- Lotus Notes: a line ` - name.ext`
- Outlook: `<<name.ext>>` or `<< File: name.ext >>`

The file types are in `ATTACHMENT_EXTENSIONS` (21 common types) in the config. The code searches `body` + `forwarded_content` (D21 default, pending your answer).

**Counts:**

| Scope (D21 option) | Emails with `has_attachment = true` |
| --- | --- |
| (a) `body` only | 1,146 |
| **(b) `body` + `forwarded_content` (default)** | **1,336** (6.2%) |
| (c) full text incl. `quoted_content` | 1,870 |

- 200-file sample: 13 true (6.5%), 0 errors. Full run: 21,662 processed, 0 errors.
- By style (full text, overlapping): Notes ` - name.ext` 1,738 · Outlook `<<…>>` 660.
- Top extensions: doc 1,915 · pdf 579 · jpg 242 · xls 211 · ppt 120 · gif 97 · htm 81.
- Examples:
  - body: `lay-k/inbox/88.` → `- Gros2001ANN.TIF`, `- Gros2001ANN.doc`
  - forwarded only: `delainey-d/all_documents/58.` → `- GT Lttr HC4-2A E Mail.doc`
  - quoted only (excluded under (b)): `lavorato-j/sent_items/501.` → `<< File: NW Update.xls >>`
- Cross-checks: `quoted_content` is filled in 3,521 emails, equal to the five reply-marker counts summed (1,487 + 1,153 + 463 + 257 + 161). `forwarded_content` is 3,353, equal to `notes_forward`. Empty `body`: 1,092 (was 1,101 before D19).

**Unexpected / not sure:**

1. **Scope matters** (D21, open): which text to search moves the count between 1,146 and 1,870.
2. **A bug in my own completeness check, fixed:** it counted `False` as "filled", so `has_attachment` showed 100%. It now counts only `True`.
3. **No web-link false positives.** `htm`/`jpg`/`gif` hits are real attachment files (`att1.htm` ×40 is the HTML copy Outlook attaches; `image001.jpg`; `crest.gif`).
4. **Not detected:** 7 bodies with an embedded MIME message ("multi-part message in MIME format"). D10 is filename patterns only, so these are documented, not counted.

---

## Step 6: Mandatory-field check → error_log.txt

**What I did:** `find_failure_reasons()` checks the spec's mandatory fields and returns every reason an email fails:

| Rule | Reason text | Decision |
| --- | --- | --- |
| no Message-ID | `missing Message-ID` | spec |
| no or unparseable Date | `missing or unparseable Date` | spec |
| Date = 1980-01-01 UTC | `placeholder date` | D6 |
| From not `name@domain` | `invalid From address` | D14 |
| no To address | `missing To` | D4 |
| no Subject header (blank is OK) | `missing Subject header` | D5 |
| body, forwarded and quoted all empty | `missing body` | D22 (pending) |

Failed emails are written to `error_log.txt` (a header line, then `source_file<TAB>reason`, multiple reasons joined by `; `) and left out of the parsed records. Any unexpected exception is also logged, as `unexpected error: …`, and that file is skipped.

**Counts:**

| | Emails |
| --- | --- |
| Files processed | 21,662 |
| **Parsed OK** | **20,339** |
| **Failed** | **1,323** |
| … missing To | 1,293 |
| … placeholder date | 23 |
| … placeholder date; missing To | 5 |
| … invalid From address | 2 (`lay-k/deleted_items/532.`, `skilling-j/inbox/223.`) |

- 200-file sample: 188 parsed, 12 failed (all "missing To"), 0 unexpected errors.
- `error_log.txt` has 1,324 lines: the header + 1,323 failures.
- Matches the step 3 prediction exactly (1,323 / 20,339). Per decision: D4 1,298 ✔ · D6 28 ✔ · D14 2 ✔.
- No failures for a missing Message-ID, an unparseable Date, a missing Subject header, or an unexpected error.

**Unexpected / not sure:**

1. **D22, decided (b):** 1,092 emails have an empty *primary* body (pure forwards or replies), but all of them have forwarded or quoted text. With the default rule (b) none of them fail. Strict rule (a) would fail 1,058 more emails.

---

## Step 7: Write output/parsed_emails.jsonl

**What I did:** `write_jsonl()` writes every parsed (non-failed) email as one JSON object per line, in UTF-8, keeping non-ASCII characters readable (D12).

**Counts and checks:**

| Check | Result |
| --- | --- |
| Records written | **20,339** (200-file sample: 188) |
| Lines in file | 20,339 |
| Field layout | 1 layout, 19 fields in spec order (`headings` comes in step 10) |
| Unique `message_id` | 20,339 |
| Unique `source_file` | 20,339 |
| In both the JSONL and `error_log.txt` | 0 |
| JSONL + error_log | 21,662 ✔ |
| File size | 51 MB |

Types are consistent across all records:
- address fields are always lists
- `forwarded_content` is a string in 3,310 records and `null` in the rest; `quoted_content` is a string in 3,450 (lower than the step 4 marker counts because failed emails are excluded)
- `x_cc` is a string in 5,492; `x_bcc` in 13
- `has_attachment` is always a bool

**Sample record** (`maildir/lay-k/inbox/1082.`, long strings cut to 80 characters):

```json
{
 "message_id": "<10903186.1075860846311.JavaMail.evans@thyme>",
 "date": "2002-01-16T19:47:35+00:00",
 "from_address": "barblpl@yahoo.com",
 "to_addresses": ["skeeper@enron.com", "klay@enron.com", "mrslinda@lplpi.com"],
 "cc_addresses": [],
 "bcc_addresses": [],
 "subject": "Electronics bill",
 "x_from": "Barbara VanDerVliet <barblpl@yahoo.com>@ENRON",
 "x_to": "sally keepers <skeeper@enron.com>, Kenneth Lay <klay@enron.com>, Linda Lay <mrsl",
 "x_cc": null,
 "x_bcc": null,
 "x_folder": "\\Kenneth_Lay_Mar2002\\Lay, Kenneth\\Inbox",
 "x_origin": "Lay-K",
 "content_type": "text/plain; charset=us-ascii",
 "source_file": "maildir/lay-k/inbox/1082.",
 "body": "Here is the update for the Architectural electronic bill.  Mrs Lay and I have di",
 "forwarded_content": null,
 "quoted_content": null,
 "has_attachment": true
}
```

(`has_attachment` is true because the body ends with ` - Architectural Electronics-Huntingdon.xls`.)

**Unexpected / not sure:**

1. **Committing a 51 MB file:** GitHub warns above 50 MB and rejects files above 100 MB. The JSONL isn't in the deliverables list and can be regenerated in ~11 s. Options: (a) git-ignore it · (b) commit it.

### Step 7 follow-up (D23)

- `output/parsed_emails.jsonl` (51 MB) is git-ignored. Rebuild it with `python src/parse_emails.py` (~11 s).
- Committed instead: `output/sample_parsed_emails.jsonl` (71 KB), 18 records, 3 per category:

| Category | Records |
| --- | --- |
| plain | `delainey-d/_sent_mail/102.`, `lavorato-j/_hedgefunds/2.`, `lay-k/_sent/1.` |
| nested_forward | `delainey-d/_sent_mail/107.`, `lavorato-j/_sent_mail/125.`, `lay-k/all_documents/1037.` |
| outlook_reply | `delainey-d/deleted_items/1.`, `lavorato-j/all_documents/17.`, `lay-k/all_documents/1002.` |
| notes_reply | `delainey-d/_sent_mail/101.`, `lavorato-j/_sent_mail/173.`, `lay-k/_sent/10.` |
| attachment | `delainey-d/_sent_mail/113.`, `lavorato-j/_sent_mail/110.`, `lay-k/all_documents/100.` |
| blank_subject | `delainey-d/_sent_mail/10.`, `lavorato-j/_sent_mail/11.`, `lay-k/_sent/97.` |

- Only 3 of the 5 mailboxes appear, because sorted order fills each category before reaching skilling-j and whalley-l.

---

## Step 8: Extraction statistics

**What I did:** I replaced the scattered prints with `build_stats()`, which collects every number into one dict. `print_stats()` prints it, and the same dict is saved as `output/extraction_stats.json`. Completeness is reported over **all processed files** (gaps in the raw data) and over **parsed OK** (what goes into the DB).

**Full-run output** (exact copy):

```
Files found: 21662   processed: 21662
  lay-k          5937
  lavorato-j     4685
  skilling-j     4139
  delainey-d     3566
  whalley-l      3335
Parsed OK: 20339   Failed: 1323
    1293  missing To
      23  placeholder date
       5  placeholder date; missing To
       2  invalid From address
Body split, by first marker found:
  no_marker               14788
  notes_forward            3353
  outlook_original         1487
  notes_reply_one_line     1153
  notes_reply_two_line      463
  gt_quoted                 257
  notes_reply_from_line     161
Leading Notes header blocks stripped (D17): 12
Field completeness:        all processed      parsed OK
  message_id           21662 100.0%     20339 100.0%
  date                 21662 100.0%     20339 100.0%
  from_address         21660 100.0%     20339 100.0%
  to_addresses         20364  94.0%     20339 100.0%
  cc_addresses          5594  25.8%      5471  26.9%
  bcc_addresses         5594  25.8%      5471  26.9%
  subject              20173  93.1%     18873  92.8%
  x_from               21662 100.0%     20339 100.0%
  x_to                 21146  97.6%     20339 100.0%
  x_cc                  5628  26.0%      5492  27.0%
  x_bcc                   13   0.1%        13   0.1%
  x_folder             21662 100.0%     20339 100.0%
  x_origin             21662 100.0%     20339 100.0%
  content_type         21662 100.0%     20339 100.0%
  source_file          21662 100.0%     20339 100.0%
  body                 20570  95.0%     19281  94.8%
  forwarded_content     3353  15.5%      3310  16.3%
  quoted_content        3521  16.3%      3450  17.0%
  has_attachment        1336   6.2%      1149   5.6%

Wrote: output/parsed_emails.jsonl, error_log.txt, output/extraction_stats.json, output/sample_parsed_emails.jsonl
```

**Checks:** parsed + failed = processed (20,339 + 1,323 = 21,662 ✔) · body-split markers sum to 21,662 ✔ · `extraction_stats.json` is valid JSON (3.4 KB) ✔. The 200-file sample run first: 188 parsed, 12 failed.

**Unexpected / not sure:**

1. **`has_attachment` 1,336 vs 1,149:** D21's 1,336 counts all processed files. Among parsed emails it's 1,149, because 187 emails with attachments failed (mostly no `To`). D21 now states both.
2. **What "filled" means:** a blank subject `""` and `has_attachment = false` count as not filled. So `subject` shows 92.8% among parsed records even though every one has a Subject header (D5).
3. **`--limit` overwrites the outputs** with sample results. The stats record `"limit"`, so a sample run is identifiable. Always finish with a full run before committing.

### Step 8 follow-up

- Subject completeness is now reported two ways: `subject` (non-blank) 18,873 = 92.8%, and `subject_header_present` 20,339 = 100% (parsed OK).
- **D24:** `--limit` runs now write to `output/sample_run/` (git-ignored). Verified: the real `error_log.txt`, `parsed_emails.jsonl`, `extraction_stats.json` and `sample_parsed_emails.jsonl` were byte-identical (MD5) before and after a `--limit 200` run.
- The README will quote the **parsed** attachment count: **1,149**.

---

## Step 9: Full-run verification and spot-check

**What I did:** (1) checked every count in DECISIONS.md against `output/extraction_stats.json` from the full run; (2) a no-text-lost check over all 20,339 records; (3) a spot-check of 10 records against their raw files, automated and by eye.

### 1. Counts vs DECISIONS.md

| Check | Expected | Actual | |
| --- | --- | --- | --- |
| Files found (D3) | 21,662 | 21,662 | ✔ |
| Parsed OK (prediction) | 20,339 | 20,339 | ✔ |
| Failed (prediction) | 1,323 | 1,323 | ✔ |
| D4 missing To | 1,298 | 1,298 | ✔ |
| D6 placeholder date | 28 | 28 | ✔ |
| D14 invalid From | 2 | 2 | ✔ |
| D22 missing body | 0 | 0 | ✔ |
| D5 blank subjects (all processed) | 1,489 | 1,489 | ✔ |
| D7 Cc lists (all processed) | 5,594 | 5,594 | ✔ |
| D17 Notes blocks stripped | 12 | 12 | ✔ |
| D8 notes_forward | 3,353 | 3,353 | ✔ |
| D19 gt_quoted | 257 | 257 | ✔ |
| D8 amendment notes_reply_from_line | 161 | 161 | ✔ |
| Markers sum | 21,662 | 21,662 | ✔ |
| D21 has_attachment (all processed) | 1,336 | 1,336 | ✔ |
| D21 has_attachment (parsed) | 1,149 | 1,149 | ✔ |
| JSONL lines | 20,339 | 20,339 | ✔ |

No-text-lost check: 20,339 of 20,339 records: body + forwarded + quoted == original body (ignoring whitespace; minus the D17 block). Mismatches: 0 []

### 2. Spot-check: the 10 files

Open these yourself (paths are relative to `data/`):

1. `maildir/whalley-l/_sent_mail/212.`: plain email, no markers
2. `maildir/skilling-j/inbox/1533.`: **with Cc** (4 recipients; Bcc is a copy, D7)
3. `maildir/lay-k/inbox/1082.`: **with attachment** (` - Architectural Electronics-Huntingdon.xls`)
4. `maildir/lay-k/elizabeth/23.`: **nested forward** (4 levels; forwards ` - ENRON.DOC`)
5. `maildir/lay-k/sent_items/2.`: **reply with quoted text** (Outlook `-----Original Message-----`)
6. `maildir/lay-k/sent/71.`: reply with quoted text (Notes one-line header)
7. `maildir/delainey-d/sent/333.`: D17 block stripped, then a two-line Notes reply
8. `maildir/whalley-l/connect_deletes/113.`: quoted-printable decoded, D16 apostrophes (`Enron's`)
9. `maildir/lay-k/inbox/15.`: non-ASCII X-From (`François`, Windows-1252)
10. `maildir/lavorato-j/all_documents/8.`: blank subject (D5), with Cc

**Result: 10 of 10 pass.** Every record passes automated checks against its raw headers (Message-ID, From, To count, Cc count, Subject). I also read every field by eye:
- Dates are correct in UTC: −0800 (PST) adds 8 hours, −0700 (PDT) adds 7.
- Nothing is truncated, and non-ASCII characters are intact.
- #4: body is empty and all 4 forward levels are in `forwarded_content`.
- #8: no `=20`, no soft line breaks and no `\x01,` left.

Things that look odd but are faithful to the source:
- #7's `To` is `kay.chapman@enron.com`, the sender herself. That's what the raw `To:` header says.
- #9's X-From keeps a literal `\"` around the name, exactly as in the raw header.
- #6's body begins `Ken Lay wrote:`. Rosalee is passing on Ken's letter as her own text, and the real quote starts at the Notes header `Loyal Lay … on 08/05/2000 06:25:04 PM`.

### 3. Full spot-check tables

### 1. Plain email, no markers

`maildir/whalley-l/_sent_mail/212.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Tue, 27 Feb 2001 02:17:00 -0800 (PST)` | `2001-02-27T10:17:00+00:00` |
| From | `greg.whalley@enron.com` | `greg.whalley@enron.com` |
| To | 1 address(es) | 1: `jeffrey.mcmahon@enron.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Re: FW: Enron & FairAir - Mike Kirksey suggested I contact you` | `Re: FW: Enron & FairAir - Mike Kirksey suggested I contact you` |
| X-From | `Greg Whalley` | `Greg Whalley` |
| has_attachment | | `False` |
| body | | 270 chars: _I have actually talked with these guys before.  More than a year ago I / think.  I may have an old copy of their business plan.  The guy I talk_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 2. With Cc (4 recipients); Bcc copies Cc (D7)

`maildir/skilling-j/inbox/1533.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Thu, 12 Jul 2001 15:43:41 -0700 (PDT)` | `2001-07-12T22:43:41+00:00` |
| From | `karen.denne@enron.com` | `karen.denne@enron.com` |
| To | 1 address(es) | 1: `jeff.skilling@enron.com` |
| Cc / Bcc | 4 / 4 | 4 / 4 |
| Subject | `Business 2.0 Interview` | `Business 2.0 Interview` |
| X-From | `Denne, Karen </O=ENRON/OU=NA/CN=RECIPIENTS/CN=KDENNE>` | `Denne, Karen </O=ENRON/OU=NA/CN=RECIPIENTS/CN=KDENNE>` |
| has_attachment | | `False` |
| body | | 1484 chars: _Jeff -- You are scheduled to do a telephone interview with Erick Schon / 1.  There's been a lot written about the New Economy, and in the past _ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 3. With attachment (Notes ` - file.xls`)

`maildir/lay-k/inbox/1082.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Wed, 16 Jan 2002 11:47:35 -0800 (PST)` | `2002-01-16T19:47:35+00:00` |
| From | `barblpl@yahoo.com` | `barblpl@yahoo.com` |
| To | 3 address(es) | 3: `skeeper@enron.com, klay@enron.com, mrslinda@lplpi.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Electronics bill` | `Electronics bill` |
| X-From | `Barbara VanDerVliet <barblpl@yahoo.com>@ENRON` | `Barbara VanDerVliet <barblpl@yahoo.com>@ENRON` |
| has_attachment | | `True` |
| body | | 450 chars: _Here is the update for the Architectural electronic bill.  Mrs Lay and / Barb_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 4. Nested forward (4 levels)

`maildir/lay-k/elizabeth/23.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Mon, 18 Oct 1999 01:47:00 -0700 (PDT)` | `1999-10-18T08:47:00+00:00` |
| From | `steven.kean@enron.com` | `steven.kean@enron.com` |
| To | 6 address(es) | 6: `mark.schroeder@enron.com, kenneth.lay@enron.com, joseph.sutton@enron.com …` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Translation of articles` | `Translation of articles` |
| X-From | `Steven J Kean` | `Steven J Kean` |
| has_attachment | | `True` |
| body | | 0 chars: _(none)_ |
| forwarded_content | | 1096 chars: _---------------------- Forwarded by Steven J Kean/HOU/EES on 10/18/99 _ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 5. Outlook reply with quoted text

`maildir/lay-k/sent_items/2.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Tue, 25 Sep 2001 11:39:46 -0700 (PDT)` | `2001-09-25T18:39:46+00:00` |
| From | `kenneth.lay@enron.com` | `kenneth.lay@enron.com` |
| To | 1 address(es) | 1: `hasan.kedwaii@enron.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `RE: Media Reports` | `RE: Media Reports` |
| X-From | `Lay, Kenneth </O=ENRON/OU=NA/CN=RECIPIENTS/CN=KLAY>` | `Lay, Kenneth </O=ENRON/OU=NA/CN=RECIPIENTS/CN=KLAY>` |
| has_attachment | | `False` |
| body | | 171 chars: _Hasan: / I fully understand and agree with your comments.  Unfortunately, I did_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 2852 chars: _-----Original Message-----_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 6. Notes one-line reply with quoted text

`maildir/lay-k/sent/71.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Tue, 8 Aug 2000 06:33:00 -0700 (PDT)` | `2000-08-08T13:33:00+00:00` |
| From | `rosalee.fleming@enron.com` | `rosalee.fleming@enron.com` |
| To | 1 address(es) | 1: `loyal_lay@yahoo.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Re: Your E-mail address` | `Re: Your E-mail address` |
| X-From | `Rosalee Fleming` | `Rosalee Fleming` |
| has_attachment | | `False` |
| body | | 520 chars: _Ken Lay wrote: / "Loyal -_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 952 chars: _Loyal Lay <loyal_lay@yahoo.com> on 08/05/2000 06:25:04 PM_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 7. D17 block stripped + two-line Notes reply

`maildir/delainey-d/sent/333.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Mon, 28 Aug 2000 10:17:00 -0700 (PDT)` | `2000-08-28T17:17:00+00:00` |
| From | `kay.chapman@enron.com` | `kay.chapman@enron.com` |
| To | 1 address(es) | 1: `kay.chapman@enron.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Re: ENA Management Committee` | `Re: ENA Management Committee` |
| X-From | `Kay Chapman` | `Kay Chapman` |
| has_attachment | | `False` |
| body | | 366 chars: _This is the original memo sent to all the committee members from Dave. / then sent out another one cancelling the Staff Meeting for all those n_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 1836 chars: _David W Delainey_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 8. Quoted-printable decoded + D16 apostrophes

`maildir/whalley-l/connect_deletes/113.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Tue, 12 Dec 2000 10:50:00 -0800 (PST)` | `2000-12-12T18:50:00+00:00` |
| From | `enron.announcements@enron.com` | `enron.announcements@enron.com` |
| To | 1 address(es) | 1: `all.states@enron.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Improved Process for Engaging Temporary Workers` | `Improved Process for Engaging Temporary Workers` |
| X-From | `Enron Announcements` | `Enron Announcements` |
| has_attachment | | `False` |
| body | | 4438 chars: _As you are aware, Enron utilizes temporary staffing services to satisf / staffing requirements throughout the company.  For the past several mo_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 9. Non-ASCII X-From (Windows-1252)

`maildir/lay-k/inbox/15.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Tue, 22 May 2001 09:56:24 -0700 (PDT)` | `2001-05-22T16:56:24+00:00` |
| From | `amepya2@hotmail.com` | `amepya2@hotmail.com` |
| To | 1 address(es) | 1: `kenneth.lay@enron.com` |
| Cc / Bcc | 0 / 0 | 0 / 0 |
| Subject | `Three proposals, following up our recent meeting.` | `Three proposals, following up our recent meeting.` |
| X-From | `\"François Ndengwe\" <amepya2@hotmail.com>@ENRON <IMCEANOTES` | `\"François Ndengwe\" <amepya2@hotmail.com>@ENRON <IMCEANOTES` |
| has_attachment | | `True` |
| body | | 10587 chars: _Dr. Kenneth L. Lay / Chairman of the Board_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

### 10. Blank subject (D5), Cc

`maildir/lavorato-j/all_documents/8.`

| Field | Raw header | Parsed |
| --- | --- | --- |
| Date | `Mon, 17 Jan 2000 12:35:00 -0800 (PST)` | `2000-01-17T20:35:00+00:00` |
| From | `john.lavorato@enron.com` | `john.lavorato@enron.com` |
| To | 1 address(es) | 1: `john.sherriff@enron.com` |
| Cc / Bcc | 1 / 1 | 1 / 1 |
| Subject | `` | `` |
| X-From | `John J Lavorato` | `John J Lavorato` |
| has_attachment | | `False` |
| body | | 326 chars: _John, I thought I would send you a note to outline our conversation re / Redmond.  Dave will return to the London office in late May.  In late_ |
| forwarded_content | | 0 chars: _(none)_ |
| quoted_content | | 0 chars: _(none)_ |

Auto-checks vs raw: Message-ID ✔ · From ✔ · To count ✔ · Cc count ✔ · Subject ✔

