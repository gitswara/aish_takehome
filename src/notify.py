"""Task 4: duplicate notifications (draft .eml files; live sends via the Gmail MCP server).

Run:  python src/notify.py                          (dry run: drafts only, no network, no DB writes)
      python src/notify.py --send-live [--max-sends N]   (steps 4-7: not built yet)

Decisions D47-D56 in DECISIONS.md.
"""

import argparse
import os
import re
import sqlite3
import sys
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect_duplicates as dd  # noqa: E402  (reuse D39/D45/D46 logic and the D35 regex)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "output", "enron.db")
REPLIES_DIR = os.path.join(PROJECT_ROOT, "output", "replies")
DRAFT_FROM = "Email Deduplication System <dedup@localhost>"   # D53: drafts are never sent
MESSAGE_ID_DOMAIN = "dedup.local"                              # D53
MAX_SENDS_DEFAULT = 10                                         # D49
MAX_SENDS_LIMIT = 100                                          # D49
SEND_DELAY_SECONDS = 1                                         # D55
DRAFTS_COMMIT_LIMIT_MB = 25                                    # D48: above this, zip the drafts

# §4.2 template (body). Placeholders are filled by build_body().
BODY_TEMPLATE = """This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  {dup_id}
    Date Sent:   {dup_date}
    Subject:     {subject}

  Original Email on Record:
    Message-ID:  {orig_id}
    Date Sent:   {orig_date}

  Similarity Score: {score}%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
"""


# ---------------------------------------------------------------------------
# Step 1: read flagged duplicates and pick each group's target
# ---------------------------------------------------------------------------
def read_notices(conn):
    """Every flagged duplicate (one draft each, D47), with its original's subject,
    and is_target = True for the latest duplicate of each group (D39)."""
    pairs = dd.read_flagged_pairs(conn)    # includes same_timestamp, likely_export_copy, recipient_overlap
    original_subjects = dict(conn.execute(
        "SELECT message_id, subject FROM emails WHERE message_id IN "
        "(SELECT duplicate_of FROM emails WHERE is_duplicate = 1)"))
    sent = {mid for (mid,) in conn.execute("SELECT message_id FROM emails WHERE notification_sent = 1")}

    latest = {}   # original id -> the pair with the latest (date, source_file)
    for p in pairs:
        key = (p["duplicate_date"], p["source_file"])
        current = latest.get(p["original_message_id"])
        if current is None or key > (current["duplicate_date"], current["source_file"]):
            latest[p["original_message_id"]] = p
    target_ids = {p["duplicate_message_id"] for p in latest.values()}

    for p in pairs:
        p["original_subject"] = original_subjects[p["original_message_id"]]
        p["is_target"] = p["duplicate_message_id"] in target_ids
        p["is_real_resend"] = dd.is_real_resend(p)
        p["notification_sent"] = p["duplicate_message_id"] in sent
    return pairs


# ---------------------------------------------------------------------------
# Step 2: build one notice
# ---------------------------------------------------------------------------
def notice_subject(original_subject):
    """D52: '[Duplicate Notice] Re: <original subject without its own Re:/Fw: prefixes>'."""
    cleaned = dd.REPLY_PREFIXES.sub("", original_subject or "").strip()
    return f"[Duplicate Notice] Re: {cleaned or '(no subject)'}"


def readable_utc(iso_date):
    """'2001-05-01T00:11:00+00:00' -> '2001-05-01 00:11:00 UTC' (D53)."""
    return datetime.fromisoformat(iso_date).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_body(p):
    return BODY_TEMPLATE.format(
        dup_id=p["duplicate_message_id"], dup_date=readable_utc(p["duplicate_date"]),
        subject=p["subject"] or "(no subject)",          # D52: same wording as the header
        orig_id=p["original_message_id"], orig_date=readable_utc(p["original_date"]),
        score=f"{p['similarity_score']:.2f}")


def build_message(p, to_address, from_address=DRAFT_FROM):
    """The full notice as an EmailMessage (D53).

    References and In-Reply-To = the flagged email's own Message-ID. For a group's
    target (and every live send) that is the spec's message_id_of_latest_duplicate.
    """
    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = notice_subject(p["original_subject"])
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(domain=MESSAGE_ID_DOMAIN)
    msg["References"] = p["duplicate_message_id"]
    msg["In-Reply-To"] = p["duplicate_message_id"]
    msg.set_content(build_body(p))          # text/plain; charset utf-8
    return msg


def safe_filename(message_id):
    """'<12846475.1075854481614.JavaMail.evans@thyme>' ->
    '12846475.1075854481614.JavaMail.evans_at_thyme.eml' (D53)."""
    name = message_id.strip().strip("<>").replace("@", "_at_")
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) + ".eml"


# ---------------------------------------------------------------------------
# Step 3: dry run, write every draft
# ---------------------------------------------------------------------------
def write_drafts(notices, folder):
    """Clear old drafts and write one .eml per flagged duplicate (D47, D54).
    Returns (files_written, total_bytes)."""
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.endswith(".eml"):
            os.remove(os.path.join(folder, name))

    names = [safe_filename(p["duplicate_message_id"]) for p in notices]
    if len(set(names)) != len(names):
        raise SystemExit("STOP: two drafts would get the same file name after cleaning (D53).")

    total_bytes = 0
    for p, name in zip(notices, names):
        data = build_message(p, to_address=p["from_address"]).as_bytes()   # D51: drafts -> real sender
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
        total_bytes += len(data)
    return len(names), total_bytes


def main():
    parser = argparse.ArgumentParser(description="Duplicate notifications (dry run by default).")
    parser.add_argument("--send-live", action="store_true", help="send notices via the Gmail MCP server")
    parser.add_argument("--max-sends", type=int, default=MAX_SENDS_DEFAULT,
                        help=f"live sends per run (default {MAX_SENDS_DEFAULT}, max {MAX_SENDS_LIMIT})")
    args = parser.parse_args()
    if args.send_live:
        raise SystemExit("--send-live is not built yet (PLAN.md Task 4 steps 4-7).")

    conn = sqlite3.connect(DB_PATH)
    notices = read_notices(conn)
    conn.close()

    targets = [p for p in notices if p["is_target"]]
    real = [p for p in targets if p["is_real_resend"]]
    files, total_bytes = write_drafts(notices, REPLIES_DIR)

    print(f"Flagged duplicates: {len(notices)}   groups (targets): {len(targets)}   "
          f"real re-send targets (live-eligible, D50): {len(real)}   already notified: "
          f"{sum(p['notification_sent'] for p in targets)}")
    print(f"Drafts written: {files} to {os.path.relpath(REPLIES_DIR, PROJECT_ROOT)}/   "
          f"total size: {total_bytes / 1_000_000:.1f} MB (content bytes)   "
          f"D48: {'commit all' if total_bytes / 1_000_000 <= DRAFTS_COMMIT_LIMIT_MB else 'zip'}")
    print("Dry run: no emails sent, DB unchanged.")


if __name__ == "__main__":
    main()
