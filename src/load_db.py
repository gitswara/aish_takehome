"""Task 2: load parsed emails (JSONL) into SQLite.

Run:  python src/load_db.py              (load everything into output/enron.db)
      python src/load_db.py --limit 200  (sample load into output/sample_run/enron.db)
      python src/load_db.py --rebuild    (delete the DB first; refused if any notification was sent)

Safe to re-run (D30): emails are upserted on message_id, the Task 3/4 columns
are never overwritten, and recipient rows are replaced per email.
"""

import argparse
import json
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_SQL = os.path.join(PROJECT_ROOT, "schema.sql")
PARSED_JSONL = os.path.join(PROJECT_ROOT, "output", "parsed_emails.jsonl")
DB_PATH = os.path.join(PROJECT_ROOT, "output", "enron.db")
SAMPLE_DB_PATH = os.path.join(PROJECT_ROOT, "output", "sample_run", "enron.db")   # --limit runs (D24)

# Parsed fields copied from the JSONL into the emails table. The Task 3/4
# columns (is_duplicate, duplicate_of, similarity_score, notification_sent,
# notification_date) are deliberately NOT in this list, so a re-load never
# changes them (D30).
EMAIL_COLUMNS = [
    "message_id", "date", "from_address", "subject", "body",
    "forwarded_content", "quoted_content", "headings",
    "x_from", "x_to", "x_cc", "x_bcc", "x_folder", "x_origin",
    "content_type", "has_attachment", "source_file",
]
RECIPIENT_FIELDS = {"to_addresses": "to", "cc_addresses": "cc", "bcc_addresses": "bcc"}


# ---------------------------------------------------------------------------
# Read input
# ---------------------------------------------------------------------------
def read_jsonl(path, limit=None):
    """Return the parsed records. With --limit, an evenly spaced sample (as D15)."""
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    if limit is not None and limit < len(records):
        step = len(records) / limit
        records = [records[int(i * step)] for i in range(limit)]
    return records


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
def connect(db_path):
    """Open the DB with foreign keys switched on (SQLite has them off by default)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn):
    with open(SCHEMA_SQL, encoding="utf-8") as f:
        conn.executescript(f.read())


def rebuild_allowed(db_path):
    """--rebuild is refused if any notification has been sent (D30)."""
    if not os.path.exists(db_path):
        return True
    conn = sqlite3.connect(db_path)
    try:
        sent = conn.execute("SELECT COUNT(*) FROM emails WHERE notification_sent = 1").fetchone()[0]
    except sqlite3.OperationalError:     # no emails table yet
        sent = 0
    conn.close()
    if sent:
        print(f"REFUSED: --rebuild would erase notification history ({sent} emails have "
              f"notification_sent = 1). Run without --rebuild.")
        return False
    return True


# ---------------------------------------------------------------------------
# Load steps
# ---------------------------------------------------------------------------
def upsert_email(conn, record):
    """Insert the email, or refresh its parsed fields if message_id already exists.

    Returns the email's id. ON CONFLICT only updates EMAIL_COLUMNS, so the
    Task 3/4 columns keep their values (D30).
    """
    columns = ", ".join(EMAIL_COLUMNS)
    placeholders = ", ".join("?" for _ in EMAIL_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in EMAIL_COLUMNS if c != "message_id")
    sql = (f"INSERT INTO emails ({columns}) VALUES ({placeholders}) "
           f"ON CONFLICT(message_id) DO UPDATE SET {updates} RETURNING id")
    values = [int(record[c]) if c == "has_attachment" else record[c] for c in EMAIL_COLUMNS]
    return conn.execute(sql, values).fetchone()[0]


def address_id(conn, address, cache):
    """Return the id for an address, inserting it if it's new (D26)."""
    if address not in cache:
        conn.execute("INSERT OR IGNORE INTO addresses (address) VALUES (?)", (address,))
        cache[address] = conn.execute(
            "SELECT id FROM addresses WHERE address = ?", (address,)).fetchone()[0]
    return cache[address]


def replace_recipients(conn, email_id, record, cache):
    """Delete this email's recipient rows and insert them again from the record (D30).

    A repeated address in the same list hits the primary key and is skipped (D29).
    Returns (rows_written, repeats_skipped).
    """
    conn.execute("DELETE FROM email_recipients WHERE email_id = ?", (email_id,))
    written = skipped = 0
    for field, recipient_type in RECIPIENT_FIELDS.items():
        for address in record[field]:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO email_recipients (email_id, address_id, recipient_type) "
                "VALUES (?, ?, ?)", (email_id, address_id(conn, address, cache), recipient_type))
            if cursor.rowcount == 1:
                written += 1
            else:
                skipped += 1
    return written, skipped


def handle_stale_emails(conn, current_message_ids):
    """Emails in the DB but no longer in the JSONL (D30).

    Delete each one and clear the Task 3 flags of duplicates that point to it,
    UNLESS it was notified itself or a notified email points to it: then keep it
    ("stale, kept for notification history"). Returns (deleted, kept, flags_cleared).
    """
    in_db = [row[0] for row in conn.execute("SELECT message_id FROM emails")]
    stale = [m for m in in_db if m not in current_message_ids]
    deleted, kept, flags_cleared = [], [], 0
    for message_id in stale:
        notified_self = conn.execute(
            "SELECT notification_sent FROM emails WHERE message_id = ?", (message_id,)).fetchone()[0]
        notified_pointers = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE duplicate_of = ? AND notification_sent = 1",
            (message_id,)).fetchone()[0]
        if notified_self or notified_pointers:
            kept.append(message_id)
            continue
        cursor = conn.execute(
            "UPDATE emails SET is_duplicate = 0, duplicate_of = NULL, similarity_score = NULL "
            "WHERE duplicate_of = ?", (message_id,))
        flags_cleared += cursor.rowcount
        conn.execute("DELETE FROM emails WHERE message_id = ?", (message_id,))   # recipients cascade
        deleted.append(message_id)
    return deleted, kept, flags_cleared


def load(conn, records):
    """Load all records in ONE transaction. Returns a report dict."""
    existing = {row[0] for row in conn.execute("SELECT message_id FROM emails")}
    current = {r["message_id"] for r in records}
    cache = {}
    report = {"emails_in_jsonl": len(records), "inserted": 0, "updated": 0,
              "recipient_rows_written": 0, "repeat_recipients_skipped": 0}
    with conn:   # commits on success, rolls back everything on any error
        for record in records:
            email_id = upsert_email(conn, record)
            report["updated" if record["message_id"] in existing else "inserted"] += 1
            written, skipped = replace_recipients(conn, email_id, record, cache)
            report["recipient_rows_written"] += written
            report["repeat_recipients_skipped"] += skipped
        deleted, kept, flags_cleared = handle_stale_emails(conn, current)
        # Remove addresses no recipient row uses any more (e.g. after stale deletes
        # or a parser change).
        cursor = conn.execute(
            "DELETE FROM addresses WHERE id NOT IN (SELECT address_id FROM email_recipients)")
        report["unused_addresses_removed"] = cursor.rowcount
    report["stale_deleted"] = len(deleted)
    report["stale_kept_for_notification_history"] = kept
    report["duplicate_flags_cleared"] = flags_cleared
    return report


def table_counts(conn):
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("emails", "addresses", "email_recipients")}


def main():
    parser = argparse.ArgumentParser(description="Load parsed emails into SQLite.")
    parser.add_argument("--limit", type=int, default=None,
                        help="load only N records (evenly spread) into output/sample_run/enron.db")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete the database first (refused if any notification was sent)")
    args = parser.parse_args()

    db_path = DB_PATH if args.limit is None else SAMPLE_DB_PATH
    if args.rebuild:
        if not rebuild_allowed(db_path):
            sys.exit(1)
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"Rebuild: deleted {os.path.relpath(db_path, PROJECT_ROOT)}")

    records = read_jsonl(PARSED_JSONL, args.limit)
    conn = connect(db_path)
    apply_schema(conn)
    report = load(conn, records)
    counts = table_counts(conn)
    conn.close()

    print(f"Database: {os.path.relpath(db_path, PROJECT_ROOT)}")
    print(f"Emails in JSONL: {report['emails_in_jsonl']}   inserted: {report['inserted']}   "
          f"updated: {report['updated']}")
    print(f"Recipient rows written: {report['recipient_rows_written']}   "
          f"repeats skipped (D29): {report['repeat_recipients_skipped']}")
    print(f"Stale emails deleted: {report['stale_deleted']}   "
          f"duplicate flags cleared: {report['duplicate_flags_cleared']}   "
          f"unused addresses removed: {report['unused_addresses_removed']}")
    kept = report["stale_kept_for_notification_history"]
    print(f"Stale, kept for notification history: {len(kept)}")
    for message_id in kept:
        print(f"  {message_id}")
    print("Table rows: " + "   ".join(f"{t}: {n}" for t, n in counts.items()))


if __name__ == "__main__":
    main()
