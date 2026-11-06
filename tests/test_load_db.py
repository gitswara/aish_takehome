"""Tests for src/load_db.py (PLAN.md Task 2, step 7).

Each test builds a fresh SQLite DB in a pytest temp folder from a few
synthetic records, so no Enron data and no real output/enron.db are needed.
Run:  pytest -q
"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import load_db  # noqa: E402


def make_record(n, to=("a@enron.com",), cc=(), bcc=()):
    """A minimal parsed-email record, shaped like one line of parsed_emails.jsonl."""
    return {
        "message_id": f"<{n}.JavaMail@test>", "date": f"2001-05-{n:02d}T10:00:00+00:00",
        "from_address": "sender@enron.com", "subject": f"Subject {n}", "body": f"Body {n}",
        "forwarded_content": None, "quoted_content": None, "headings": None,
        "x_from": "Sender", "x_to": None, "x_cc": None, "x_bcc": None,
        "x_folder": "\\Test", "x_origin": "Test-T", "content_type": "text/plain",
        "has_attachment": False, "source_file": f"maildir/test/inbox/{n}.",
        "to_addresses": list(to), "cc_addresses": list(cc), "bcc_addresses": list(bcc),
    }


@pytest.fixture
def conn(tmp_path):
    connection = load_db.connect(str(tmp_path / "test.db"))
    load_db.apply_schema(connection)
    yield connection
    connection.close()


def row(conn, message_id):
    return conn.execute(
        "SELECT subject, is_duplicate, duplicate_of, similarity_score, notification_sent "
        "FROM emails WHERE message_id = ?", (message_id,)).fetchone()


def recipients(conn, message_id):
    return sorted(conn.execute(
        "SELECT r.recipient_type, a.address FROM email_recipients r "
        "JOIN emails e ON e.id = r.email_id JOIN addresses a ON a.id = r.address_id "
        "WHERE e.message_id = ?", (message_id,)).fetchall())


def test_rerun_updates_parsed_fields_but_keeps_task34_state(conn):
    """D30: a re-load refreshes parsed fields and never touches the Task 3/4 columns."""
    r1, r2 = make_record(1), make_record(2)
    report = load_db.load(conn, [r1, r2])
    assert (report["inserted"], report["updated"]) == (2, 0)

    # Task 3/4 marks r2 as a notified duplicate of r1.
    with conn:
        conn.execute("UPDATE emails SET is_duplicate = 1, duplicate_of = ?, similarity_score = 96.5, "
                     "notification_sent = 1 WHERE message_id = ?", (r1["message_id"], r2["message_id"]))

    r2["subject"] = "Subject 2 (parser fixed)"          # a parser change
    report = load_db.load(conn, [r1, r2])
    assert (report["inserted"], report["updated"]) == (0, 2)
    assert row(conn, r2["message_id"]) == ("Subject 2 (parser fixed)", 1, r1["message_id"], 96.5, 1)


def test_recipients_are_replaced_on_reload(conn):
    """D30: a re-load deletes and re-inserts each email's recipients (no stale ones left)."""
    r = make_record(1, to=("a@enron.com", "b@enron.com"), cc=("c@enron.com",))
    load_db.load(conn, [r])
    r["to_addresses"], r["cc_addresses"] = ["a@enron.com"], []      # parser now finds fewer
    report = load_db.load(conn, [r])
    assert recipients(conn, r["message_id"]) == [("to", "a@enron.com")]
    assert report["unused_addresses_removed"] == 2                   # b@ and c@ no longer used


def test_repeated_address_in_one_list_is_stored_once(conn):
    """D29: the same address twice in To -> one row; the repeat is counted as skipped."""
    r = make_record(1, to=("a@enron.com", "a@enron.com"), cc=("a@enron.com",))
    report = load_db.load(conn, [r])
    assert recipients(conn, r["message_id"]) == [("cc", "a@enron.com"), ("to", "a@enron.com")]
    assert report["repeat_recipients_skipped"] == 1


def test_stale_original_is_deleted_and_its_duplicates_cleared(conn):
    """D30: an email no longer in the JSONL is deleted; duplicates pointing to it are reset."""
    original, dup = make_record(1), make_record(2)
    load_db.load(conn, [original, dup])
    with conn:
        conn.execute("UPDATE emails SET is_duplicate = 1, duplicate_of = ?, similarity_score = 95.0 "
                     "WHERE message_id = ?", (original["message_id"], dup["message_id"]))

    report = load_db.load(conn, [dup])                                # original went stale
    assert report["stale_deleted"] == 1 and report["duplicate_flags_cleared"] == 1
    assert row(conn, original["message_id"]) is None
    assert row(conn, dup["message_id"])[1:] == (0, None, None, 0)
    assert recipients(conn, original["message_id"]) == []              # cascade removed them


def test_stale_original_kept_when_a_notified_duplicate_points_to_it(conn):
    """D30 guard: keep a stale original if a sent notice refers to it."""
    original, dup = make_record(1), make_record(2)
    load_db.load(conn, [original, dup])
    with conn:
        conn.execute("UPDATE emails SET is_duplicate = 1, duplicate_of = ?, similarity_score = 97.0, "
                     "notification_sent = 1 WHERE message_id = ?", (original["message_id"], dup["message_id"]))

    report = load_db.load(conn, [dup])
    assert report["stale_deleted"] == 0
    assert report["stale_kept_for_notification_history"] == [original["message_id"]]
    assert row(conn, original["message_id"]) is not None
    assert row(conn, dup["message_id"])[1:] == (1, original["message_id"], 97.0, 1)


def test_unique_constraint_rejects_plain_duplicate_insert(conn):
    """Spec: a plain INSERT of an existing message_id fails."""
    r = make_record(1)
    load_db.load(conn, [r])
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed: emails.message_id"):
        conn.execute("INSERT INTO emails (message_id, date, from_address, subject, body, source_file) "
                     "VALUES (?, '2001-01-01T00:00:00+00:00', 'x@y.com', 's', '', 'n/a')", (r["message_id"],))


def test_rebuild_refused_once_a_notification_was_sent(tmp_path):
    """D30: --rebuild must not erase notification history."""
    db_path = str(tmp_path / "test.db")
    connection = load_db.connect(db_path)
    load_db.apply_schema(connection)
    load_db.load(connection, [make_record(1)])
    assert load_db.rebuild_allowed(db_path) is True
    with connection:
        connection.execute("UPDATE emails SET notification_sent = 1")
    connection.close()
    assert load_db.rebuild_allowed(db_path) is False
