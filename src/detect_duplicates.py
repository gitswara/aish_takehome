"""Task 3: find duplicate emails in output/enron.db and flag them.

Duplicate (spec + DECISIONS.md D35-D44): same from_address, same subject after
removing Re:/Fw:/Fwd: prefixes, and full text >= 90% similar (rapidfuzz
fuzz.ratio), plus the D44 body gate. In each group the earliest email is the
original; every other email is flagged as its duplicate.

Run:  python src/detect_duplicates.py
      python src/detect_duplicates.py --limit 300   (only 300 candidate blocks; no DB writes)
"""

import argparse
import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "output", "enron.db")
SIMILARITY_THRESHOLD = 90      # D41: inclusive, 0-100 scale
SCORE_DECIMALS = 2             # D41
REPORT_CSV = os.path.join(PROJECT_ROOT, "duplicates_report.csv")          # D42
STATS_JSON = os.path.join(PROJECT_ROOT, "output", "dedup_stats.json")     # D42
REPORT_COLUMNS = ["duplicate_message_id", "original_message_id", "subject", "from_address",
                  "duplicate_date", "original_date", "similarity_score",   # the 7 spec columns
                  "same_timestamp"]                                        # D39 extra column

# D35: one or more reply/forward prefixes at the start: "Re:", "RE: FW:", "Fwd[2]:" ...
REPLY_PREFIXES = re.compile(r"^\s*((re|fw|fwd)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Step 1: read candidates and build blocks
# ---------------------------------------------------------------------------
def collapse_whitespace(text):
    """'a \n\t b' -> 'a b' (D36: layout differences shouldn't count)."""
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_subject(subject):
    """'RE: FW:  Budget  Q3' -> 'budget q3' (D35)."""
    return collapse_whitespace(REPLY_PREFIXES.sub("", subject or "")).lower()


def load_emails(conn):
    """Every email with the fields Task 3 needs, as dicts."""
    rows = conn.execute(
        "SELECT message_id, date, from_address, subject, body, forwarded_content, "
        "quoted_content, source_file, notification_sent FROM emails").fetchall()
    emails = []
    for (message_id, date, from_address, subject, body, forwarded, quoted,
         source_file, notification_sent) in rows:
        emails.append({
            "message_id": message_id, "date": date, "from_address": from_address,
            "subject": subject, "source_file": source_file,
            "notification_sent": notification_sent,
            # D9 + D36: full text = body + forwarded + quoted, whitespace collapsed.
            "full_text": collapse_whitespace(f"{body} {forwarded or ''} {quoted or ''}"),
            # D44: the primary body on its own, for the body gate.
            "body_text": collapse_whitespace(body),
        })
    return emails


def build_blocks(emails):
    """Group emails by (from_address, normalised subject). Only blocks with 2+
    emails can contain duplicates. Each block is sorted oldest first, ties broken
    by source_file (D39), so the first email of a group is its original."""
    blocks = {}
    for email in emails:
        key = (email["from_address"], normalize_subject(email["subject"]))
        blocks.setdefault(key, []).append(email)
    candidate_blocks = [b for b in blocks.values() if len(b) >= 2]
    for block in candidate_blocks:
        block.sort(key=lambda e: (e["date"], e["source_file"]))
    return blocks, candidate_blocks


# ---------------------------------------------------------------------------
# Step 2: group within each block, anchored to the original (D38)
# ---------------------------------------------------------------------------
def body_gate_passes(email, original):
    """D44: the primary bodies must also match, with explicit empty-body rules.

    both empty      -> pass (pure forwards: the full text decides)
    exactly one empty -> fail (one has the sender's own words, the other doesn't)
    otherwise       -> body similarity >= threshold
    """
    a, b = email["body_text"], original["body_text"]
    if not a and not b:
        return True
    if not a or not b:
        return False
    return fuzz.ratio(a, b) >= SIMILARITY_THRESHOLD


def group_block(block, counters):
    """Return the duplicate groups in one block (oldest-first list).

    Each email is compared with the ORIGINAL of each group found so far and joins
    the first one where the full text is >= threshold AND the body gate passes.
    Otherwise it starts a new group (and becomes that group's original).
    A group is {"original": email, "duplicates": [(email, full_text_score), ...]}.
    """
    groups = []
    for email in block:
        for group in groups:
            score = fuzz.ratio(email["full_text"], group["original"]["full_text"])
            if score < SIMILARITY_THRESHOLD:
                continue
            if not body_gate_passes(email, group["original"]):
                counters["body_gate_rejections"] += 1
                continue
            group["duplicates"].append((email, round(score, SCORE_DECIMALS)))
            break
        else:
            groups.append({"original": email, "duplicates": []})
    return [g for g in groups if g["duplicates"]]


def find_groups(candidate_blocks):
    counters = {"body_gate_rejections": 0}
    groups = []
    for block in candidate_blocks:
        groups.extend(group_block(block, counters))
    return groups, counters


# ---------------------------------------------------------------------------
# Step 3: write flags to the DB (D40)
# ---------------------------------------------------------------------------
def write_flags(conn, groups):
    """Recompute all Task 3 flags in ONE transaction. Rows already notified are
    never changed (D40); if the new result disagrees with one, it's a conflict.

    Returns (rows_flagged, conflicts) where conflicts is a list of message_ids.
    """
    new = {}   # duplicate message_id -> (original message_id, score)
    for group in groups:
        for email, score in group["duplicates"]:
            new[email["message_id"]] = (group["original"]["message_id"], score)

    notified = {mid: dup_of for mid, dup_of in conn.execute(
        "SELECT message_id, duplicate_of FROM emails WHERE notification_sent = 1")}
    conflicts = [mid for mid, dup_of in notified.items()
                 if mid not in new or new[mid][0] != dup_of]

    rows_flagged = 0
    with conn:
        conn.execute("UPDATE emails SET is_duplicate = 0, duplicate_of = NULL, similarity_score = NULL "
                     "WHERE notification_sent = 0")
        for message_id, (original_id, score) in new.items():
            if message_id in notified:
                continue                       # notification history is never rewritten
            conn.execute("UPDATE emails SET is_duplicate = 1, duplicate_of = ?, similarity_score = ? "
                         "WHERE message_id = ?", (original_id, score, message_id))
            rows_flagged += 1
    return rows_flagged, conflicts


# ---------------------------------------------------------------------------
# Step 4: duplicates_report.csv, built from what is stored in the DB
# ---------------------------------------------------------------------------
def read_flagged_pairs(conn):
    """Every flagged email joined to its original, as stored in the DB."""
    return conn.execute(
        "SELECT d.message_id, o.message_id, d.subject, d.from_address, d.date, o.date, "
        "       d.similarity_score, d.source_file "
        "FROM emails d JOIN emails o ON o.message_id = d.duplicate_of "
        "WHERE d.is_duplicate = 1 "
        "ORDER BY o.date, o.message_id, d.date, d.source_file").fetchall()


def write_report(pairs, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REPORT_COLUMNS)
        for dup_id, orig_id, subject, sender, dup_date, orig_date, score, _source in pairs:
            writer.writerow([dup_id, orig_id, subject, sender, dup_date, orig_date,
                             f"{score:.{SCORE_DECIMALS}f}", dup_date == orig_date])


# ---------------------------------------------------------------------------
# Step 5: statistics
# ---------------------------------------------------------------------------
def build_stats(emails, blocks, candidate_blocks, pairs, counters, rows_flagged, conflicts):
    """Spec stats (groups, flagged, average group size) plus the D39 split,
    score bands, and the Task 4 targets (latest duplicate of each group)."""
    groups = {}
    for dup_id, orig_id, _subj, _from, dup_date, orig_date, score, source in pairs:
        groups.setdefault(orig_id, []).append((dup_date, source, dup_id, dup_date == orig_date))
    # Task 4 target = the latest duplicate in each group, by (date, source_file) (D39).
    targets = [max(members) for members in groups.values()]
    scores = [p[6] for p in pairs]
    sizes = [len(members) + 1 for members in groups.values()]
    return {
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "scorer": "rapidfuzz fuzz.ratio on full text (body + forwarded + quoted) + D44 body gate",
        "emails": len(emails),
        "blocks": len(blocks),
        "candidate_blocks": len(candidate_blocks),
        "duplicate_groups": len(groups),
        "emails_flagged": len(pairs),
        "average_group_size": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        "largest_group_size": max(sizes, default=0),
        "flagged_same_timestamp_as_original": sum(1 for p in pairs if p[4] == p[5]),
        "flagged_later_than_original": sum(1 for p in pairs if p[4] != p[5]),
        "score_bands": {
            "100": sum(1 for s in scores if s == 100),
            "95_to_under_100": sum(1 for s in scores if 95 <= s < 100),
            "90_to_under_95": sum(1 for s in scores if s < 95),
        },
        "lowest_score": min(scores, default=None),
        "body_gate_rejected_comparisons": counters["body_gate_rejections"],
        "rows_flagged_this_run": rows_flagged,
        "notified_rows_conflicts": conflicts,
        "task4_targets": len(targets),
        "task4_targets_later_than_original": sum(1 for t in targets if not t[3]),
    }


def print_stats(stats):
    print(f"Emails: {stats['emails']}   blocks: {stats['blocks']}   candidate blocks: {stats['candidate_blocks']}")
    print(f"Duplicate groups: {stats['duplicate_groups']}   emails flagged: {stats['emails_flagged']}   "
          f"average group size: {stats['average_group_size']}   largest group: {stats['largest_group_size']}")
    print(f"  same timestamp as original (folder copies): {stats['flagged_same_timestamp_as_original']}   "
          f"later than original (re-sends): {stats['flagged_later_than_original']}")
    bands = stats["score_bands"]
    print(f"  scores: 100 = {bands['100']}   95-<100 = {bands['95_to_under_100']}   "
          f"90-<95 = {bands['90_to_under_95']}   lowest = {stats['lowest_score']}")
    print(f"  body gate (D44) rejected comparisons: {stats['body_gate_rejected_comparisons']}")
    print(f"  notified rows in conflict (kept unchanged): {len(stats['notified_rows_conflicts'])}")
    print(f"Task 4 targets (latest duplicate per group): {stats['task4_targets']}   "
          f"of which later than their original: {stats['task4_targets_later_than_original']}")


def take_sample(items, limit):
    """Evenly spaced sample (same idea as D15), for quick --limit runs."""
    if limit is None or limit >= len(items):
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def main():
    parser = argparse.ArgumentParser(description="Find and flag duplicate emails.")
    parser.add_argument("--limit", type=int, default=None,
                        help="only process N candidate blocks (evenly spread)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    emails = load_emails(conn)
    blocks, candidate_blocks = build_blocks(emails)
    candidate_blocks = take_sample(candidate_blocks, args.limit)
    groups, counters = find_groups(candidate_blocks)

    if args.limit is None:
        rows_flagged, conflicts = write_flags(conn, groups)
        pairs = read_flagged_pairs(conn)
        write_report(pairs, REPORT_CSV)
        stats = build_stats(emails, blocks, candidate_blocks, pairs, counters, rows_flagged, conflicts)
        with open(STATS_JSON, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        conn.close()
        print_stats(stats)
        print(f"\nWrote: flags in {os.path.relpath(DB_PATH, PROJECT_ROOT)}, "
              f"{os.path.relpath(REPORT_CSV, PROJECT_ROOT)}, {os.path.relpath(STATS_JSON, PROJECT_ROOT)}")
        return
    conn.close()

    # --limit: a print-only preview from memory (no DB writes, no files).
    flagged = [(g["original"], email, score) for g in groups for email, score in g["duplicates"]]
    same_ts = sum(1 for original, email, _ in flagged if email["date"] == original["date"])
    print(f"Emails: {len(emails)}   blocks: {len(blocks)}   candidate blocks (2+ emails): "
          f"{len(candidate_blocks)}" + (f"  (--limit {args.limit})" if args.limit else ""))
    print(f"Duplicate groups: {len(groups)}   emails flagged: {len(flagged)}   "
          f"average group size: {(len(flagged) + len(groups)) / max(len(groups), 1):.2f}")
    print(f"  same timestamp as original (folder copies): {same_ts}   later (re-sends): {len(flagged) - same_ts}")
    print(f"  body-gate rejections (full text passed, body failed, D44): {counters['body_gate_rejections']}")
    lowest = min((score for _, _, score in flagged), default=None)
    print(f"  lowest flagged full-text score: {lowest}")


if __name__ == "__main__":
    main()
