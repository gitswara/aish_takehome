"""Tests for src/detect_duplicates.py (PLAN.md Task 3, step 8).

Small synthetic emails only: no Enron data and no real output/enron.db.
Run:  pytest -q
"""

import os
import sys

from rapidfuzz import fuzz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import detect_duplicates as dd  # noqa: E402
import load_db  # noqa: E402

QUOTED_THREAD = ("-----Original Message----- From: Lavorato, John Sent: Monday To: Delainey, David "
                 "Subject: Spring Business Meeting " + "Agenda item for the spring business meeting. " * 40)


def email(n, body="", rest="", date="2001-05-01T10:00:00+00:00", source=None):
    """A candidate email shaped like load_emails() output."""
    return {"message_id": f"<{n}@test>", "date": date, "from_address": "dave@enron.com",
            "subject": "Spring Business Meeting", "source_file": source or f"maildir/t/inbox/{n}.",
            "notification_sent": 0,
            "full_text": dd.collapse_whitespace(f"{body} {rest}"), "body_text": dd.collapse_whitespace(body)}


# --- D35: subject normalisation ---------------------------------------------
def test_subject_normalisation():
    assert dd.normalize_subject("RE: Fw: Re: Budget  Q3") == "budget q3"     # chain, case, spaces
    assert dd.normalize_subject("Re[2]: Hello") == "hello"                    # [n] counter
    assert dd.normalize_subject("FWD:re:   Hello   World ") == "hello world"
    assert dd.normalize_subject("FYI: Lunch") == "fyi: lunch"                 # not a reply prefix
    assert dd.normalize_subject("") == ""


# --- D44: body gate -----------------------------------------------------------
def test_different_replies_over_same_quoted_thread_are_not_duplicates():
    """Full text >= 90 because of the shared quoted thread, but the bodies differ."""
    a = email(1, body="John, what do you want to do with this? We had discussed. Regards Delainey",
              rest=QUOTED_THREAD, date="2001-01-29T14:05:00+00:00")
    b = email(2, body="fyi, action", rest=QUOTED_THREAD, date="2001-02-02T10:17:00+00:00")
    assert fuzz.ratio(a["full_text"], b["full_text"]) >= 90              # precondition
    counters = {"body_gate_rejections": 0}
    assert dd.group_block([a, b], counters) == []
    assert counters["body_gate_rejections"] == 1


def test_body_gate_empty_bodies():
    both_empty = (email(1, body="", rest=QUOTED_THREAD), email(2, body="", rest=QUOTED_THREAD))
    one_empty = (email(1, body="Would this guy be a candidate?", rest=QUOTED_THREAD),
                 email(2, body="", rest=QUOTED_THREAD))
    assert dd.body_gate_passes(*both_empty) is True        # pure forwards: full text decides
    assert dd.body_gate_passes(*one_empty) is False        # one has the sender's own words


# --- D38: anchor grouping -----------------------------------------------------
def test_chain_does_not_pull_a_dissimilar_email_into_the_group():
    """A ~ B and B ~ C (>= 90), but A vs C < 90: C must not join A's group."""
    base = "abcdefghij" * 10
    text_a = base
    text_b = base[:10] + "ABCD" + base[14:50] + "EFGH" + base[54:]           # 8 changes from A
    text_c = text_b[:30] + "WXYZ" + text_b[34:70] + "STUV" + text_b[74:]     # 8 more from B
    a, b, c = (email(1, body=text_a, date="2001-01-01T00:00:00+00:00"),
               email(2, body=text_b, date="2001-01-02T00:00:00+00:00"),
               email(3, body=text_c, date="2001-01-03T00:00:00+00:00"))
    assert fuzz.ratio(text_a, text_b) >= 90 and fuzz.ratio(text_b, text_c) >= 90   # precondition
    assert fuzz.ratio(text_a, text_c) < 90                                        # precondition
    groups = dd.group_block([a, b, c], {"body_gate_rejections": 0})
    assert len(groups) == 1
    assert groups[0]["original"]["message_id"] == a["message_id"]
    assert [e["message_id"] for e, _ in groups[0]["duplicates"]] == [b["message_id"]]
    assert all(score >= 90 for _, score in groups[0]["duplicates"])


# --- D39: tie-break -------------------------------------------------------------
def test_identical_timestamps_original_is_first_source_file():
    same = "2000-11-06T18:45:00+00:00"
    copies = [email(1, body="Hello all", source="maildir/d/sent/9.", date=same),
              email(2, body="Hello all", source="maildir/d/_sent_mail/3.", date=same),
              email(3, body="Hello all", source="maildir/d/all_documents/5.", date=same)]
    for order in (copies, list(reversed(copies))):                 # same result either way
        _, blocks = dd.build_blocks([dict(e) for e in order])
        groups = dd.group_block(blocks[0], {"body_gate_rejections": 0})
        assert groups[0]["original"]["source_file"] == "maildir/d/_sent_mail/3."
        assert [e["source_file"] for e, _ in groups[0]["duplicates"]] == [
            "maildir/d/all_documents/5.", "maildir/d/sent/9."]


# --- D40: re-run safety ---------------------------------------------------------
def test_notified_row_keeps_its_flags_after_a_rerun(tmp_path):
    conn = load_db.connect(str(tmp_path / "t.db"))
    load_db.apply_schema(conn)
    records = []
    for n in (1, 2):
        records.append({"message_id": f"<{n}@test>", "date": f"2001-05-0{n}T10:00:00+00:00",
                        "from_address": "dave@enron.com", "subject": "Hello", "body": "Same text",
                        "forwarded_content": None, "quoted_content": None, "headings": None,
                        "x_from": None, "x_to": None, "x_cc": None, "x_bcc": None, "x_folder": None,
                        "x_origin": None, "content_type": None, "has_attachment": False,
                        "source_file": f"maildir/t/inbox/{n}.", "to_addresses": ["a@enron.com"],
                        "cc_addresses": [], "bcc_addresses": []})
    load_db.load(conn, records)

    _, blocks = dd.build_blocks(dd.load_emails(conn))
    groups, _ = dd.find_groups(blocks)
    dd.write_flags(conn, groups)
    with conn:                                                    # Task 4 sends a notice for <2>
        conn.execute("UPDATE emails SET notification_sent = 1 WHERE message_id = '<2@test>'")

    rows_flagged, conflicts = dd.write_flags(conn, [])            # a re-run that finds nothing
    row = conn.execute("SELECT is_duplicate, duplicate_of, similarity_score, notification_sent "
                       "FROM emails WHERE message_id = '<2@test>'").fetchone()
    assert row == (1, "<1@test>", 100.0, 1)                       # untouched
    assert conflicts == ["<2@test>"] and rows_flagged == 0
    conn.close()


# --- D45: likely_export_copy ------------------------------------------------------
def test_likely_export_copy():
    notes, outlook = "\\John_Lavorato_Dec2000\\Notes Folders\\'sent mail", "\\jlavora\\Sent Items"
    orig = "2000-11-25T20:11:00+00:00"
    assert dd.likely_export_copy("2000-11-26T08:11:00+00:00", orig, 100.0, outlook, notes) is True   # +12 h
    assert dd.likely_export_copy("2000-11-28T20:11:00+00:00", orig, 100.0, outlook, notes) is False  # 3 days
    assert dd.likely_export_copy("2000-11-26T08:11:00+00:00", orig, 100.0, notes, notes) is False    # same kind
    assert dd.likely_export_copy("2000-11-26T08:41:00+00:00", orig, 100.0, outlook, notes) is False  # 12.5 h
    # D45 amendment: score >= 99 and a gap within 60 s of whole hours
    assert dd.likely_export_copy("2000-11-26T08:11:00+00:00", orig, 99.81, outlook, notes) is True   # #10-like
    assert dd.likely_export_copy("2000-11-26T08:11:01+00:00", orig, 99.98, outlook, notes) is True   # +12 h + 1 s
    assert dd.likely_export_copy("2000-11-26T08:12:01+00:00", orig, 100.0, outlook, notes) is False  # +12 h + 61 s
    assert dd.likely_export_copy("2000-11-26T08:11:00+00:00", orig, 98.9, outlook, notes) is False   # score < 99


# --- D46: recipient_overlap -------------------------------------------------------
def test_recipient_overlap():
    assert dd.recipient_overlap({"a@x.com", "b@x.com"}, {"b@x.com", "a@x.com"}) == 100.0
    assert dd.recipient_overlap({"a@x.com"}, {"b@x.com"}) == 0.0
    assert dd.recipient_overlap({"a@x.com", "b@x.com"}, {"b@x.com", "c@x.com"}) == 33.3
