# Task 3 findings: Duplicate detection & flagging

Workflow step 1: findings, decisions and assumptions. No code yet. Measured on `output/enron.db` (20,339 emails) with throwaway scripts.

**Spec (ASSIGNMENT.md §4 Task 3):**
- **Duplicates:** emails with the same `from_address`, the same subject after normalising `Re:`/`Fwd:` prefixes, and body similarity of at least 90% (fuzzy).
- **Original vs duplicate:** the **earliest** email in a group is the original. All the others get `is_duplicate = 1` and `duplicate_of = <original message_id>`. The **latest** is the primary notification target (Task 4).
- **Outputs:** `duplicates_report.csv` (duplicate_message_id, original_message_id, subject, from_address, duplicate_date, original_date, similarity_score), plus stats: groups found, emails flagged, average group size.
- **Already decided:** D9 says similarity compares the **full text** (body + forwarded + quoted). §5 requires a recognised fuzzy library, documented.

---

## What I found

### 1. Candidate blocks are small, so comparing every pair is affordable

Grouping by (sender, normalised subject) gives **8,227 blocks**. **3,907** of them have 2+ emails, covering 16,019 emails.

- Comparing all pairs inside blocks is **450,489 pairs**, which `rapidfuzz` scores in about **10 s**.
- Most blocks are tiny (sizes 2–4 cover 3,415 of 3,907).
- **The largest blocks are blank subjects:** `john.lavorato@` 865, `david.delainey@` 222, `lavorato@` 137. They're big but harmless, because the body must still match.

### 2. Most "duplicates" are folder copies, not re-sends (the biggest finding)

The same email is filed in several folders (`sent`, `_sent_mail`, `all_documents`, `discussion_threads`) with the **same timestamp** and the same text. **14,776 emails** fall in such identical-copy sets.

My estimate with the grouping I recommend below (D38):

| | Count |
| --- | --- |
| Duplicate groups | **4,537** |
| Emails flagged | **10,768** (average group size 3.37) |
| … flagged with the **same timestamp** as their original (folder copies) | **9,835** (91%) |
| … flagged with a **later** timestamp (true re-sends or repeats) | **933** (pre-D44 estimate; **final: 696**) |
| Groups with at least one later-timestamp member | 474 |
| Similarity of flagged emails | 100: 10,145 · 95–<100: 360 · 90–<95: 263 |

**Why it matters:**
- **The spec's "latest = re-send" idea doesn't fit 91% of flagged emails:** they have no "latest", because original and copy share a timestamp. That forces a **tie-break rule** (D39).
- **Task 4 notifies one sender per group, so 4,537 emails.** Gmail limits personal accounts to about 500 sends a day, so the live run will need a cap. That's a Task 4 decision; I'm flagging it now.
- If folder copies were collapsed first, there would be only **477 groups / 580 flagged** (D39 option b).

### 3. How to form groups matters (transitivity)

A ≈ B and B ≈ C doesn't mean A ≈ C.
- **"Connected components"** (any pair ≥ 90 links emails into one group) produced **18 flagged emails scoring below 90% against their own original**. The report would then show a similarity score under the threshold, contradicting the definition.
- **Comparing each email to its group's original** (D38) can't produce that: every flagged email is ≥ 90 against the original it's linked to.

### 4. Choice of scorer changes about 2,100 decisions

Over the 431,906 non-identical pairs in blocks, `fuzz.ratio` and `fuzz.token_sort_ratio` disagree on the ≥ 90 test for **2,107 pairs**.
- `token_sort_ratio` ignores word order, so it rates reworded or reordered text as more similar.
- `ratio` is order-sensitive edit similarity, the closer match to "the same body content".

### 5. Template emails can pass 90% (known false positives)

`david.delainey@enron.com`, "Approval for reviewer" (72 emails): approval notices that differ only in the reviewer's name score **91–92%**. By the spec's rule these are duplicates, though a human wouldn't call them re-sends. Automated reminders behave the same way, e.g. `perfmgmt@enron.com` "Year End 2000 Performance Feedback" at 89.8–92.2%. I propose to follow the spec and document this.

### 6. Subject prefixes vary

- **Prefix forms seen:** `Re:` 3,973 · `RE:` 860 · `FW:` 670 · `Re: FW:` 75 · `Fw:` 72 · `RE: FW:` 68 · `Fwd:` 33 · `FW: FW:` 21 · `re:` 16 · `FWD:` 4 · chains like `Re: Fwd: FW:`.
- **Not reply prefixes, so left alone:** `Mtg:`, `URG:`, `FYI:`, `h:`.

### 7. Already in PLAN.md
- **Sender aliases** (`john.lavorato@` vs `lavorato@`, the 2nd and 6th biggest senders) won't group under the spec's same-`from_address` rule. Follow the spec, document it; nice-to-have: count how many groups would merge.
- **Library:** `rapidfuzz` 3.14.6 is already installed and pinned. No new library is needed.

---

## Decisions for me

### D35. Subject normalisation
- (a) Strip any chain of `Re:` / `Fw:` / `Fwd:` prefixes (any case, optional `[2]`-style counters, any spacing), then collapse whitespace and **lowercase**.
- (b) The same, but case-sensitive.

**Recommendation: (a).** `RE: Budget` and `Re: budget` are the same thread. Other prefixes (`Mtg:`, `FYI:`) are part of the subject and stay.

### D36. Text compared
Following D9, the text is `body + forwarded_content + quoted_content`.
- (a) **Collapse all whitespace** (spaces, tabs, line breaks → one space) before scoring, keeping case.
- (b) Compare as stored.

**Recommendation: (a).** Line-wrapping differs between copies of the same message, and the spec is about content, not layout.

### D37. Similarity scorer (`rapidfuzz`)
- (a) `fuzz.ratio`: order-sensitive edit similarity, 0–100
- (b) `fuzz.token_sort_ratio`: ignores word order
- (c) `fuzz.partial_ratio`: best-matching substring, which would score a short email inside a long one at 100

**Recommendation: (a).** It's the most literal reading of "body content ≥ 90% similar". (c) would wrongly match "fyi" against any long email that contains "fyi".

### D38. Forming groups
- (a) **Anchor to the original:** go through each block **oldest first**. Each email is compared to the *original* of each existing group and joins the first group it matches at ≥ 90; otherwise it starts a new group.
- (b) Connected components (any pair ≥ 90 links).
- (c) Complete linkage (every pair in a group ≥ 90).

**Recommendation: (a).**
- Every flagged email is ≥ 90 against the original it's linked to, so `similarity_score` in the report always means "vs the original" and is never below the threshold.
- It's deterministic and fast (about 1.5 s).
- (b) gave 18 flagged emails below 90. (c) is slower and harder to explain.

### D39. Same timestamps: folder copies vs re-sends
First, the tie-break: when the earliest timestamp is shared, the original is the one with the **alphabetically first `source_file`**. Ordering by (date, source_file) makes every run give the same result.

Then, what to flag:
- (a) **Follow the spec literally:** flag every copy (**4,537 groups / 10,768 flagged**).
- (b) **Collapse folder copies first** (same timestamp + same text = one email), then dedup only distinct sends (**477 groups / 580 flagged**). Closer to "re-send", but it departs from the spec's definition.
- (c) **(a), plus an extra report column `same_timestamp` (true/false)** and a stats line splitting folder copies (9,835) from later repeats (933; pre-D44; final 696). Task 4 can then prioritise real re-sends.

**Recommendation: (c).** It follows the spec's definition exactly, and an extra column at the end doesn't break the required ones. It also makes the folder-copy issue visible instead of hiding it.

### D40. Re-running Task 3
- (a) Clear `is_duplicate`, `duplicate_of` and `similarity_score` on all rows with `notification_sent = 0`, then recompute everything. **Rows already notified are never changed.** If the new grouping disagrees with a notified row, report it as a conflict.
- (b) Clear everything, notified rows included.

**Recommendation: (a).** It matches the D30 principle: notification history is never rewritten. The whole run is one transaction.

### D41. Threshold and score format
- **Threshold:** similarity ≥ **90** (inclusive), set as `SIMILARITY_THRESHOLD = 90` in the config block.
- **Score format:** `similarity_score` stored and reported on a **0–100 scale, rounded to 2 decimals** (Task 4's template shows a percentage).

**Recommendation:** as stated.

### D42. Outputs
- `duplicates_report.csv` at the **repo root** (next to `error_log.txt`, as in the deliverables list): the 7 spec columns + `same_timestamp` (D39c). Every flagged email gets one row, sorted by original date, then duplicate date.
- **Stats:**
  - groups
  - emails flagged
  - average group size
  - the folder-copy vs later-repeat split
  - the score bands

  Printed and saved to `output/dedup_stats.json`.
- **Script:** `src/detect_duplicates.py`. `--limit` writes to `output/sample_run/` (as D24).

**Recommendation:** as stated.

### D43 (nice-to-have). Sender-alias report
Count how many groups would merge if obvious aliases were combined (`lavorato@` ↔ `john.lavorato@`), **without changing any flags**.

**Recommendation:** only after Task 4 works (time).

---

## Assumptions
- **Blocking is exact:** only emails with the same sender and the same normalised subject are compared. Fuzziness applies to the body only, as the spec says.
- **Blank subjects** normalise to `""` and form a block per sender like any other subject.
- **No email has an empty full text** (D22), so there are no empty-vs-empty 100% matches.
- **Notification target (Task 4):** the latest flagged email of each group. With D39's tie-break, "latest" is the last by (date, source_file).
- **Query 6** in `sample_queries.sql` gets its real output after this task runs.
- **Template false positives** (finding 5) are accepted under the spec's rule and documented.

---

## D44 measurement: also require the primary body to be ≥ 90?

**Rule tested:** a flagged email must pass on full text (as now) **and** its primary `body` must be ≥ 90 similar to its original's. Empty bodies are handled explicitly: **both empty → pass** (full text decides); **exactly one empty → fail** (my assumption, open).

| | Groups | Flagged |
| --- | --- | --- |
| Full text only (current) | 4,537 | 10,768 |
| Full text + body check | 4,558 | 10,675 (net −93) |

- **244** currently-flagged emails fail the body check; **240** of them are *later* than their original (re-send candidates), 4 share its timestamp.
- Their body scores: <50: 154 · 50–80: 45 · 0: 45 (35 with exactly one empty body).
- Net change is −93, not −244, because un-flagged emails start their own group (+21) or match another original.
- 684 flagged pairs have **both** bodies empty and pass under the explicit rule.

**Examples it would un-flag:**

| From / subject | Original body (start) | "Duplicate" body (start) | Full | Body |
| --- | --- | --- | --- | --- |
| Delainey, "Great words" (May 15 → May 17, 2000) | "Mike Moulton has been pursuing an idea in the technology area…" | "Mike, I forwarded your interest to Whalley, McConnel and McMahon…" | 94.4 | 48.0 |
| Delainey, "Re: Spring Business Meeting" (Jan 29 → Feb 2, 2001) | "John, what do you want to do with this? We had discussed…" | "fyi, action" | 97.6 | 14.4 |
| Delainey, "Re: GE Plastics Facts" (Oct 16 → Oct 18, 2000) | "Rodney, from what you told me it sounds like GE is willing to play on the Selkirk asset…" | "Rodney, if this deal is such a long put why did you push me into this process?…" | 90.6 | 50.5 |
| Delainey, "An Associate who loves EA so much" (*one body empty*) | "Would this guy be a candidate for the LTP?" | *(empty: pure forward)* | 98.1 | 0 |

In each case the quoted or forwarded thread (1.8–5.9k characters) is identical and drowns out a short, different message from the sender. **Decided (D44):** add the body gate; both empty → pass, exactly one empty → fail. `similarity_score` stays the full-text score; the gate isn't reported.

---

## Steps 1–2: blocks + grouping (no DB writes yet)

**What I did:** `src/detect_duplicates.py`:
- `load_emails()` reads all emails and builds `full_text` (body + forwarded + quoted) and `body_text`, both with whitespace collapsed (D9, D36).
- `build_blocks()` keys on (`from_address`, `normalize_subject()`) (D35) and sorts each block by (date, source_file) (D39).
- `group_block()` compares each email with each group's **original** (D38): full text `fuzz.ratio` ≥ 90 **and** `body_gate_passes()` (D44, with explicit empty-body rules).

Config at the top: `SIMILARITY_THRESHOLD = 90`, `SCORE_DECIMALS = 2`, `REPLY_PREFIXES`.

| Run | Candidate blocks | Groups | Flagged | Avg size | Same timestamp | Later | Body-gate rejections | Lowest score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `--limit 300` | 300 | 324 | 766 | 3.36 | 727 | 39 | 21 comparisons | 91.19 |
| **full** | 3,907 | **4,558** | **10,675** | 3.34 | **9,979** | **696** | 253 comparisons (244 emails) | **90.08** |

- Matches the D44 estimate exactly (4,558 / 10,675) ✔. Run time 2.6 s.
- No flagged email scores below 90 against its original ✔ (lowest 90.08).
- `output/enron.db` MD5 unchanged ✔ (steps 1–2 don't write).

**Unexpected / not sure:**
1. **The split moved:** folder copies 9,835 → 9,979; later re-sends 933 → **696** (the final figure). D44 removed 240 of the "later" emails, and some of those then joined another group as same-timestamp copies.
2. **Body gate: 253 comparisons rejected, affecting 244 emails.** One email can fail against more than one group's original.
3. **`--limit` samples whole blocks, not emails** (agreed): sampling emails would split groups and undercount duplicates. It's print-only.

---

## Steps 3–5: write flags, duplicates_report.csv, stats

**What I did:**
- `write_flags()`: one transaction. It clears the Task 3 columns on non-notified rows, sets `is_duplicate = 1`, `duplicate_of` and `similarity_score` (full-text score, D41) on every flagged email, never changes a notified row, and reports conflicts (D40).
- `read_flagged_pairs()` → `write_report()`: the CSV is built **from the DB after writing**, sorted by original date, then duplicate date.
- `build_stats()` → printed + `output/dedup_stats.json`.
- `--limit` became a print-only preview: writing flags from a block sample would leave the DB half-flagged. D42 amended.

**Full run (about 4 s):**

| Stat | Value |
| --- | --- |
| Duplicate groups | **4,558** |
| Emails flagged | **10,675** |
| Average group size | **3.34** (largest 68) |
| Same timestamp as original (folder copies) | 9,979 |
| Later than original (re-sends) | **696** |
| Scores 100 / 95–<100 / 90–<95 | 10,293 / 231 / 151 (lowest 90.08) |
| D44 body gate | 253 comparisons rejected (244 emails) |
| Notified-row conflicts | 0 |
| **Task 4 targets** (latest duplicate per group) | **4,558**, of which **389** later than their original |

**Checks:**

| Check | Result |
| --- | --- |
| `is_duplicate = 1` rows / distinct originals | 10,675 / 4,558 ✔ |
| Chains (an original that is itself flagged) | 0 ✔ |
| Flagged rows missing `duplicate_of` or score | 0 ✔ |
| Non-flagged rows with leftover values | 0 ✔ |
| Duplicate dated before its original | 0 ✔ |
| Duplicate with a different sender | 0 ✔ |
| Score range | 90.08 – 100.00 ✔ |
| `integrity_check` / `foreign_key_check` | ok / 0 ✔ |
| CSV rows (+ header), `same_timestamp` True/False | 10,675; 9,979 / 696 ✔ |
| **Second run:** flags hash / report MD5 | **identical** ✔ |

First report row (the "Education Survey" email from Q3 of `sample_queries.sql`):
`<23185873…>, <12045714…>, Education Survey, jan_levine@travisintl.com, 1998-01-06T01:32:00+00:00, 1998-01-06T01:32:00+00:00, 100.00, True`

**Unexpected / not sure:**
1. **Only 389 of the 4,558 Task 4 targets are later than their original.** In the other 4,169 groups the "latest" is a same-timestamp folder copy, chosen by the `source_file` tie-break. That matters for Task 4: about 4,558 notices vs Gmail's ~500/day.
2. **`--limit` changed meaning** (now print-only), so D42 is amended.
