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
