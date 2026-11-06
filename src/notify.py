"""Task 4: duplicate notifications (draft .eml files; live sends via the Gmail MCP server).

Run:  python src/notify.py                               (dry run: drafts only, no network, no DB writes)
      python src/notify.py --preview [--max-sends N]       (list the live targets; sends nothing)
      python src/notify.py --send-live [--max-sends N]     (send via the Gmail MCP server to NOTIFY_TO)

Decisions D47-D56 in DECISIONS.md.
"""

import argparse
import asyncio
import csv
import os
import re
import sqlite3
import sys
import time
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from datetime import datetime, timezone

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

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
TOTAL_SEND_BUDGET = 10                                         # D58: live sends across ALL runs (from the DB)
SEND_DELAY_SECONDS = 1                                         # D55
DRAFTS_COMMIT_LIMIT_MB = 25                                    # D48: above this, zip the drafts
SEND_LOG_CSV = os.path.join(PROJECT_ROOT, "output", "send_log.csv")          # D54
SEND_LOG_COLUMNS = ["timestamp", "recipient", "subject", "status", "error",   # spec columns
                    "intended_recipient", "duplicate_message_id"]             # D51/D54 extras
MCP_SERVER = os.path.join(PROJECT_ROOT, "mcp_server", "gmail_server.py")    # D55
RETRY_DELAYS_SECONDS = [2, 4, 8]                                             # D55: transient errors
# D55: how to classify an error message coming back from send_email.
AUTH_ERROR_MARKERS = ["535", "authentication", "username and password not accepted", "gmail_user",
                      "gmail_app_password"]
QUOTA_ERROR_MARKERS = ["5.4.5", "421", "quota", "rate limit", "too many"]
TRANSIENT_ERROR_MARKERS = ["timed out", "timeout", "connection", "temporarily"]

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


# ---------------------------------------------------------------------------
# Step 4: choose live targets (D50, D49)
# ---------------------------------------------------------------------------
def select_live_targets(notices, max_sends):
    """Real re-send targets not yet notified, ordered by recipient_overlap (high
    first), then similarity_score (high first), then duplicate date (oldest first)."""
    eligible = [p for p in notices
                if p["is_target"] and p["is_real_resend"] and not p["notification_sent"]]
    eligible.sort(key=lambda p: (-p["recipient_overlap"], -p["similarity_score"], p["duplicate_date"]))
    return eligible[:max_sends], len(eligible)


def print_preview(selected, eligible_count):
    print(f"Live-eligible real re-send targets not yet notified: {eligible_count}   "
          f"selected for this run: {len(selected)}")
    for i, p in enumerate(selected, 1):
        print(f"{i:3d}. overlap {p['recipient_overlap']:5.1f}  score {p['similarity_score']:6.2f}  "
              f"{p['from_address']:34s} {notice_subject(p['original_subject'])[:62]}")
        print(f"     original {p['original_date'][:16]}  ->  duplicate {p['duplicate_date'][:16]}   "
              f"{p['duplicate_message_id']}")


# ---------------------------------------------------------------------------
# Step 5: send through the Gmail MCP server (D55)
# ---------------------------------------------------------------------------
def classify_error(text):
    """'auth' / 'quota' -> stop the run; 'transient' -> retry; 'other' -> log and continue."""
    lowered = text.lower()
    if any(m in lowered for m in AUTH_ERROR_MARKERS):
        return "auth"
    if any(m in lowered for m in QUOTA_ERROR_MARKERS):
        return "quota"
    if any(m in lowered for m in TRANSIENT_ERROR_MARKERS):
        return "transient"
    return "other"


async def call_send_email(session, arguments):
    """One send_email call with retries for transient errors.
    Returns (ok, kind, text): kind is None on success, else the error class."""
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        result = await session.call_tool("send_email", arguments)
        text = " ".join(getattr(c, "text", "") for c in result.content).strip()
        if not result.isError:
            return True, None, text
        kind = classify_error(text)
        if kind != "transient" or attempt == len(RETRY_DELAYS_SECONDS):
            return False, kind, text
        await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])


# ---------------------------------------------------------------------------
# Step 6: record each outcome (D54)
# ---------------------------------------------------------------------------
def append_send_log(row):
    """Append one row to output/send_log.csv (header written once). Never overwrites."""
    new_file = not os.path.exists(SEND_LOG_CSV)
    with open(SEND_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(SEND_LOG_COLUMNS)
        writer.writerow([row[c] for c in SEND_LOG_COLUMNS])


def mark_notified(conn, message_id, when):
    """Set notification_sent / notification_date ONLY after a confirmed send."""
    with conn:
        conn.execute("UPDATE emails SET notification_sent = 1, notification_date = ? "
                     "WHERE message_id = ? AND notification_sent = 0", (when, message_id))


async def send_live(conn, selected, notify_to):
    """Open one MCP session, send each selected notice to NOTIFY_TO, log every outcome.
    Stops early on auth or quota errors. Returns a summary dict."""
    summary = {"sent": 0, "failed": 0, "stopped_reason": None}
    server = StdioServerParameters(command=sys.executable, args=[MCP_SERVER])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for i, p in enumerate(selected):
                if i > 0:
                    time.sleep(SEND_DELAY_SECONDS)                      # D55: ~1 s between sends
                subject = notice_subject(p["original_subject"])
                ok, kind, text = await call_send_email(session, {
                    "to": notify_to, "subject": subject, "body": build_body(p),
                    "references": p["duplicate_message_id"]})
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                append_send_log({"timestamp": now, "recipient": notify_to, "subject": subject,
                                 "status": "sent" if ok else "failed", "error": "" if ok else text,
                                 "intended_recipient": p["from_address"],
                                 "duplicate_message_id": p["duplicate_message_id"]})
                if ok:
                    mark_notified(conn, p["duplicate_message_id"], now)
                    summary["sent"] += 1
                    print(f"  sent {i + 1}/{len(selected)}: {subject[:60]}   ({text})")
                else:
                    summary["failed"] += 1
                    print(f"  FAILED {i + 1}/{len(selected)} [{kind}]: {text[:120]}")
                    if kind in ("auth", "quota"):
                        summary["stopped_reason"] = kind
                        print(f"  Stopping the run ({kind} error); remaining targets stay unsent.")
                        break
    return summary


def main():
    parser = argparse.ArgumentParser(description="Duplicate notifications (dry run by default).")
    parser.add_argument("--send-live", action="store_true", help="send notices via the Gmail MCP server")
    parser.add_argument("--preview", action="store_true", help="list the live targets and stop (sends nothing)")
    parser.add_argument("--max-sends", type=int, default=MAX_SENDS_DEFAULT,
                        help=f"live sends per run (default {MAX_SENDS_DEFAULT}, max {MAX_SENDS_LIMIT})")
    args = parser.parse_args()
    if not 1 <= args.max_sends <= MAX_SENDS_LIMIT:
        raise SystemExit(f"--max-sends must be between 1 and {MAX_SENDS_LIMIT} (D49).")

    conn = sqlite3.connect(DB_PATH)
    notices = read_notices(conn)

    if args.preview or args.send_live:
        # D58: never exceed TOTAL_SEND_BUDGET live sends in total, counted from the DB.
        already_sent = conn.execute("SELECT COUNT(*) FROM emails WHERE notification_sent = 1").fetchone()[0]
        budget_left = max(TOTAL_SEND_BUDGET - already_sent, 0)
        print(f"Live budget (D58): {already_sent} of {TOTAL_SEND_BUDGET} already sent; {budget_left} left")
        selected, eligible_count = select_live_targets(notices, min(args.max_sends, budget_left))
        print_preview(selected, eligible_count)
        if not selected and args.send_live:
            conn.close()
            print("Nothing to send (budget used up or no eligible targets). 0 emails sent.")
            return
        if args.preview:
            conn.close()
            print("Preview only: nothing sent, DB unchanged.")
            return
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"))   # the program reads it; values are never printed
        notify_to = os.environ.get("NOTIFY_TO", "").strip()
        if not notify_to:
            conn.close()
            raise SystemExit("REFUSED: NOTIFY_TO is not set, so there is nowhere safe to send (D51).")
        print(f"Sending {len(selected)} notice(s) to NOTIFY_TO (never to the original senders, D51) ...")
        summary = asyncio.run(send_live(conn, selected, notify_to))
        conn.close()
        print(f"Live run: sent {summary['sent']}   failed {summary['failed']}"
              + (f"   stopped early: {summary['stopped_reason']}" if summary["stopped_reason"] else "")
              + f"   log: {os.path.relpath(SEND_LOG_CSV, PROJECT_ROOT)}")
        return
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
