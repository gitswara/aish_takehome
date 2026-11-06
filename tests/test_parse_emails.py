"""Edge-case tests for src/parse_emails.py (PLAN.md step 11).

Each test writes a small fake email in the same format as the Enron files
(headers with CRLF line endings, body with LF) and runs the real parser on it.
Run:  pytest -q
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import parse_emails as p  # noqa: E402


def make_email(tmp_path, body, to="klay@enron.com",
               date="Mon, 14 May 2001 16:39:00 -0700 (PDT)", extra_headers=""):
    """Write a fake Enron-style email file and return its path."""
    headers = (
        "Message-ID: <123.JavaMail.evans@thyme>\r\n"
        f"Date: {date}\r\n"
        "From: sender@enron.com\r\n"
        + (f"To: {to}\r\n" if to else "")
        + "Subject: Test subject\r\n"
        "Mime-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n"
        "Content-Transfer-Encoding: 7bit\r\n"
        + extra_headers
        + "X-From: Sender\r\n"
        "X-To: Ken Lay\r\n"
        "X-cc: \r\n"
        "X-bcc: \r\n"
        "X-Folder: \\Test\\Inbox\r\n"
        "X-Origin: Test-T\r\n"
        "X-FileName: test.nsf\r\n"
        "\r\n"
    )
    path = tmp_path / "1."
    path.write_bytes(headers.encode("ascii") + body.encode("cp1252"))
    return str(path)


def test_nested_forward_goes_to_forwarded_content(tmp_path):
    """D8: a pure Notes forward (2 levels) -> empty body, whole chain in forwarded_content."""
    body = (
        "---------------------- Forwarded by Steven J Kean/HOU/EES on 10/18/99 08:46 AM ---------------------------\n"
        "\n"
        "Karen Denne@ENRON\n10/18/99 07:08 AM\nTo: Steven J Kean/HOU/EES@EES\nSubject: Articles\n\n"
        "---------------------- Forwarded by Karen Denne/Corp/Enron on 10/18/99 07:07 AM ---------------------------\n"
        "Here it is!\n"
    )
    record, reasons, marker, _ = p.parse_file(make_email(tmp_path, body))
    assert reasons == []                       # D22: empty primary body is NOT a failure
    assert marker == "notes_forward"
    assert record["body"] == ""
    assert record["forwarded_content"].count("Forwarded by") == 2
    assert "Here it is!" in record["forwarded_content"]
    assert record["quoted_content"] is None


def test_leading_notes_block_is_stripped(tmp_path):
    """D17: a body starting with a Notes header block keeps only the message under it,
    and the two-line Notes reply header below it starts quoted_content."""
    body = (
        "From:  David W Delainey                           08/22/2000 10:02 AM\n\t\n\n"
        "Sent by: Kay Chapman\nTo: Ina Rangel/HOU/ECT@ECT\ncc:  \nSubject: Re: ENA Management Committee\n\n"
        "This is the original memo sent to all the committee members from Dave.\n\nThanks,\nKay\n\n\n"
        "David W Delainey\n08/15/2000 02:05 PM\nTo: Tim Belden/HOU/ECT@ECT\nSubject: ENA Management Committee\n\n"
        "As part of the restructuring...\n"
    )
    record, reasons, marker, stripped = p.parse_file(make_email(tmp_path, body))
    assert stripped is True
    assert record["body"].startswith("This is the original memo")
    assert "Sent by:" not in record["body"]
    assert marker == "notes_reply_two_line"
    assert record["quoted_content"].startswith("David W Delainey\n08/15/2000 02:05 PM")


def test_single_gt_line_is_not_a_quote(tmp_path):
    """D19: one line starting with '>' (a table cell) does not split the body."""
    body = "Price caps by load level:\n  >40 GW   $250/MWh  $250/MWh\n  <40 GW   $150/MWh\n"
    record, _, marker, _ = p.parse_file(make_email(tmp_path, body))
    assert marker is None
    assert ">40 GW" in record["body"]
    assert record["quoted_content"] is None


def test_two_gt_lines_are_a_quote(tmp_path):
    """D19: two or more consecutive '>' lines are quoted content."""
    body = "Agreed, see below.\n\n> Can we meet Tuesday?\n> 2pm works for me.\n"
    record, _, marker, _ = p.parse_file(make_email(tmp_path, body))
    assert marker == "gt_quoted"
    assert record["body"] == "Agreed, see below."
    assert record["quoted_content"].startswith("> Can we meet Tuesday?")


def test_missing_to_fails(tmp_path):
    """D4: no To header -> logged as a failed parse with reason 'missing To'."""
    record, reasons, _, _ = p.parse_file(make_email(tmp_path, "Calendar entry\n", to=None))
    assert record["to_addresses"] == []
    assert reasons == ["missing To"]


def test_placeholder_date_fails(tmp_path):
    """D6: 31 Dec 1979 16:00 PST = 1 Jan 1980 00:00 UTC -> 'placeholder date'."""
    record, reasons, _, _ = p.parse_file(
        make_email(tmp_path, "Hello\n", date="Mon, 31 Dec 1979 16:00:00 -0800 (PST)"))
    assert record["date"] == "1980-01-01T00:00:00+00:00"
    assert reasons == ["placeholder date"]


def test_folded_to_header_and_utc_date(tmp_path):
    """A To header wrapped over 3 lines gives every address; the date is converted to UTC."""
    to = "a@enron.com, b@enron.com, \r\n\tc@enron.com, d@enron.com, \r\n\te@enron.com"
    record, reasons, _, _ = p.parse_file(make_email(tmp_path, "Hi all\n", to=to))
    assert reasons == []
    assert record["to_addresses"] == ["a@enron.com", "b@enron.com", "c@enron.com",
                                      "d@enron.com", "e@enron.com"]
    assert record["date"] == "2001-05-14T23:39:00+00:00"   # 16:39 PDT (-0700) -> 23:39 UTC


def test_quoted_printable_decoded_only_when_declared(tmp_path):
    """D13 + D16: declared QP is decoded and '\\x01,' becomes an apostrophe."""
    body = "Enron=01,s temporary staffing users have resear=\nched=20\nthe options.\n"
    path = make_email(tmp_path, body)
    raw = open(path, "rb").read().replace(b"Content-Transfer-Encoding: 7bit",
                                          b"Content-Transfer-Encoding: quoted-printable")
    open(path, "wb").write(raw)
    record, _, _, _ = p.parse_file(path)
    assert record["body"].startswith("Enron's temporary staffing users have researched")
    assert "=20" not in record["body"]
