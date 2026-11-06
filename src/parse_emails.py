"""Task 1: parse raw Enron email files into structured records.

Run:  python src/parse_emails.py            (all files)
      python src/parse_emails.py --limit 200 (quick sample)
"""

import argparse
import email
import json
import os
import quopri
import re
from datetime import timezone
from email.utils import getaddresses, parsedate_to_datetime

from dateutil import parser as dateutil_parser

# ---------------------------------------------------------------------------
# Config (all tunable values live here)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(PROJECT_ROOT, "data")       # folder that contains maildir/
MAILDIR = os.path.join(DATA_ROOT, "maildir")
MAILBOXES = ["lay-k", "skilling-j", "whalley-l", "lavorato-j", "delainey-d"]  # D3
ERROR_LOG = os.path.join(PROJECT_ROOT, "error_log.txt")
PARSED_JSONL = os.path.join(PROJECT_ROOT, "output", "parsed_emails.jsonl")   # D12 (git-ignored, D23)
SAMPLE_JSONL = os.path.join(PROJECT_ROOT, "output", "sample_parsed_emails.jsonl")   # D23 (committed)
SAMPLE_PER_CATEGORY = 3   # D23: records per category in the committed sample
TEXT_ENCODING = "cp1252"   # Windows-1252: how non-ASCII bytes are read (never fails with errors="replace")
GARBLED_APOSTROPHE = "\x01,"   # D16: replaced with "'"

# D6: dates that are placeholders, not real send dates (as UTC ISO strings).
# "31 Dec 1979 16:00 PST" = 1 Jan 1980 00:00 UTC, the DOS/Windows "zero" date.
PLACEHOLDER_DATES_UTC = ["1980-01-01T00:00:00+00:00"]

# Fallback for dates with a zone name but no numeric offset (hours from UTC).
# Every date in our 5 mailboxes has a numeric offset, but the spec asks us to handle these.
# D10: file types that count as an attachment when a filename is mentioned.
ATTACHMENT_EXTENSIONS = ["xls", "xlsx", "doc", "docx", "ppt", "pptx", "pdf", "zip",
                         "txt", "rtf", "csv", "wpd", "htm", "html", "jpg", "jpeg",
                         "gif", "bmp", "tif", "tiff", "msg"]

TZ_ABBREVIATIONS = {
    "UT": 0, "UTC": 0, "GMT": 0,
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7,
}


# ---------------------------------------------------------------------------
# Step 1: discover files
# ---------------------------------------------------------------------------
def discover_files(maildir, mailboxes):
    """Return a sorted list of every file path under the chosen mailboxes."""
    paths = []
    for mailbox in mailboxes:
        mailbox_dir = os.path.join(maildir, mailbox)
        if not os.path.isdir(mailbox_dir):
            print(f"WARNING: mailbox folder not found: {mailbox_dir}")
            continue
        for folder, _subfolders, filenames in os.walk(mailbox_dir):
            for name in filenames:
                paths.append(os.path.join(folder, name))
    return sorted(paths)


def take_sample(paths, limit):
    """Pick `limit` files spread evenly across the sorted list.

    Evenly spaced (not the first N) so a small sample still covers all
    five mailboxes and many folders. Deterministic: same input, same sample.
    """
    if limit is None or limit >= len(paths):
        return paths
    step = len(paths) / limit
    return [paths[int(i * step)] for i in range(limit)]


# ---------------------------------------------------------------------------
# Step 2: read one file safely
# ---------------------------------------------------------------------------
def read_email(path):
    """Read a raw email file and return (message, body_text).

    1. Read bytes and turn Windows line endings (CRLF) into LF. Headers use
       CRLF and bodies use LF, which confuses the header/body split.
    2. Decode bytes as Windows-1252. errors="replace" means a bad byte
       becomes '�' instead of crashing.
    3. Parse headers with Python's built-in email module.
    4. Decode quoted-printable only when the header declares it (D13).
    """
    with open(path, "rb") as f:
        raw = f.read()
    raw = raw.replace(b"\r\n", b"\n")
    text = raw.decode(TEXT_ENCODING, errors="replace")
    msg = email.message_from_string(text)

    body = msg.get_payload()
    encoding = (msg.get("Content-Transfer-Encoding") or "").strip().lower()
    if encoding == "quoted-printable":
        decoded = quopri.decodestring(body.encode(TEXT_ENCODING, errors="replace"))
        body = decoded.decode(TEXT_ENCODING, errors="replace")

    # D16: "\x01," is a garbled curly apostrophe (e.g. "Enron\x01,s").
    # Only this provable case is fixed; other \x01 forms are left as-is.
    body = body.replace(GARBLED_APOSTROPHE, "'")
    return msg, body


# ---------------------------------------------------------------------------
# Step 3: header fields
# ---------------------------------------------------------------------------
def unfold(value):
    """Join a header that wraps onto several lines into one line.

    A wrapped header continues on a line that starts with a space or tab.
    Returns None for a missing or blank header (spec: NULL if not present).
    """
    if value is None:
        return None
    value = re.sub(r"\n[ \t]+", " ", value).strip()
    return value or None


def parse_address_list(value):
    """'a@x.com, "Name" <b@y.com>' -> ['a@x.com', 'b@y.com'] (lowercased).

    D18: strict=False because Python's default (strict) mode throws away the
    WHOLE list if one address is malformed, e.g. '<"barbara"@x.com@enron.com>'.
    Lenient mode can return fragments like 'enron.com', so only tokens that
    look like name@domain are kept.
    """
    value = unfold(value)
    if not value:
        return []
    addresses = []
    for _display_name, address in getaddresses([value], strict=False):
        address = address.strip().lower()
        if is_valid_address(address):
            addresses.append(address)
    return addresses


def is_valid_address(address):
    """True if it looks like name@domain (one @, text on both sides)."""
    return bool(address) and re.fullmatch(r"[^@\s]+@[^@\s]+", address) is not None


def parse_date_utc(value):
    """Parse a Date header and return it in UTC as an ISO string, or None."""
    value = unfold(value)
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)          # handles '-0800 (PST)'
    except (TypeError, ValueError):
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        # Fallback: zone names like 'PST' with no numeric offset.
        tzinfos = {name: hours * 3600 for name, hours in TZ_ABBREVIATIONS.items()}
        try:
            parsed = dateutil_parser.parse(value, tzinfos=tzinfos, fuzzy=True)
        except (ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            return None   # no time zone at all: can't convert to UTC safely
    return parsed.astimezone(timezone.utc).isoformat()


def extract_header_fields(msg, path):
    """Pull every header field from the spec into a dict.

    Missing values are None (or [] for lists). Mandatory-field checks happen
    later (step 6), so this function never rejects an email.
    """
    from_list = parse_address_list(msg.get("From"))
    return {
        "message_id": unfold(msg.get("Message-ID")),
        "date": parse_date_utc(msg.get("Date")),
        "from_address": from_list[0] if from_list else None,
        "to_addresses": parse_address_list(msg.get("To")),
        "cc_addresses": parse_address_list(msg.get("Cc")),
        "bcc_addresses": parse_address_list(msg.get("Bcc")),   # D7: stored as given
        # D5: a present-but-blank Subject is "" (valid); a missing one is None.
        "subject": (unfold(msg.get("Subject")) or "") if msg.get("Subject") is not None else None,
        "x_from": unfold(msg.get("X-From")),
        "x_to": unfold(msg.get("X-To")),
        "x_cc": unfold(msg.get("X-cc")),
        "x_bcc": unfold(msg.get("X-bcc")),
        "x_folder": unfold(msg.get("X-Folder")),
        "x_origin": unfold(msg.get("X-Origin")),
        "content_type": unfold(msg.get("Content-Type")),
        "source_file": relative_source(path),
    }


# ---------------------------------------------------------------------------
# Step 4: split body / forwarded / quoted  (D8, D17)
# ---------------------------------------------------------------------------
# A Notes date like "08/05/2000 06:25:04 PM" or "10/18/99 07:08 AM".
NOTES_DATE = r"\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M"

# Each marker: (name, field it sends the rest of the text to, pattern).
# The EARLIEST marker in the body decides the cut point and the field (D8).
SPLIT_MARKERS = [
    # Lotus Notes forward: "---------------------- Forwarded by Steven J Kean/HOU/EES on ..."
    ("notes_forward", "forwarded",
     re.compile(r"^[ \t]*-{3,}\s*Forwarded by\b", re.MULTILINE)),
    # Outlook reply/forward: "-----Original Message-----"
    ("outlook_original", "quoted",
     re.compile(r"^[ \t]*-{3,}\s*Original Message\s*-{3,}", re.MULTILINE | re.IGNORECASE)),
    # Notes one-line reply header: "Loyal Lay <x@y.com> on 08/05/2000 06:25:04 PM" + "To:" within 3 lines
    ("notes_reply_one_line", "quoted",
     re.compile(r"^[^\n]{1,150}? on " + NOTES_DATE + r"[^\n]*\n(?:[^\n]*\n){0,2}?[ \t]*To:", re.MULTILINE)),
    # Notes two-line reply header: "Joe Hillings" / "09/25/2000 08:53 AM" / "To: ..."
    ("notes_reply_two_line", "quoted",
     re.compile(r"^[^\n:]{1,80}\n[ \t]*" + NOTES_DATE + r"[ \t]*\n[ \t]*To:", re.MULTILINE)),
    # Notes "From:" reply header mid-body: "From:  Michael Mann @ EES      08/08/2000 09:12 PM"
    ("notes_reply_from_line", "quoted",
     re.compile(r"^[ \t]*From:[ \t]+[^\n]+?[ \t]{2,}" + NOTES_DATE, re.MULTILINE)),
    # Classic quoting: at least 2 consecutive lines starting with ">" (D19).
    # A single ">" line is often not a quote, e.g. "  >40 GW   $250/MWh".
    ("gt_quoted", "quoted",
     re.compile(r"^[ \t]*>[^\n]*\n[ \t]*>", re.MULTILINE)),
]

# D17: a body that STARTS with a Notes header block ("From:  Name   date",
# "Sent by:", "To:", "cc:", "Subject:"). The block is the message's own header,
# so it is removed and the text below it is the real body.
LEADING_NOTES_BLOCK = re.compile(
    r"\A\s*From:[ \t]+[^\n]+?[ \t]{2,}" + NOTES_DATE + r".*?^Subject:[^\n]*\n",
    re.MULTILINE | re.DOTALL)


def split_body(text):
    """Return (body, forwarded_content, quoted_content, marker_name, stripped_notes_block).

    Text above the first marker is the body. Everything from the first marker
    on goes to forwarded_content (Notes forward) or quoted_content (replies).
    marker_name (None if no marker) and stripped_notes_block (D17) are for stats.
    """
    stripped_notes_block = False
    match = LEADING_NOTES_BLOCK.match(text)
    if match:
        text = text[match.end():]
        stripped_notes_block = True

    first = None   # (position, marker name, field)
    for name, field, pattern in SPLIT_MARKERS:
        found = pattern.search(text)
        if found and (first is None or found.start() < first[0]):
            first = (found.start(), name, field)

    if first is None:
        return text.strip(), None, None, None, stripped_notes_block

    position, name, field = first
    body = text[:position].strip()
    rest = text[position:].strip()
    forwarded = rest if field == "forwarded" else None
    quoted = rest if field == "quoted" else None
    return body, forwarded, quoted, name, stripped_notes_block


# ---------------------------------------------------------------------------
# Step 5: has_attachment  (D10: filename patterns only)
# ---------------------------------------------------------------------------
_EXT = "|".join(ATTACHMENT_EXTENSIONS)
ATTACHMENT_PATTERNS = [
    # Lotus Notes: a line like " - Architectural Electronics-Huntingdon.xls"
    re.compile(r"^[ \t]*-[ \t]+[^\n]{1,200}?\.(?:" + _EXT + r")[ \t]*$", re.MULTILINE | re.IGNORECASE),
    # Outlook: "<<Q3 budget.doc>>" or "<<File: notes.pdf>>"
    re.compile(r"<<[^<>\n]{1,200}?\.(?:" + _EXT + r")\s*>>", re.IGNORECASE),
]


def has_attachment(text):
    """True if the text names an attached file in Notes or Outlook style."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in ATTACHMENT_PATTERNS)


# ---------------------------------------------------------------------------
# Step 6: mandatory-field check
# ---------------------------------------------------------------------------
def find_failure_reasons(record):
    """Return a list of reasons this record fails the spec's mandatory fields.

    An empty list means the record is valid. Every reason found is listed,
    so one email can fail for more than one reason.
    """
    reasons = []
    if not record["message_id"]:
        reasons.append("missing Message-ID")
    if record["date"] is None:
        reasons.append("missing or unparseable Date")
    elif record["date"] in PLACEHOLDER_DATES_UTC:
        reasons.append("placeholder date")                          # D6
    if not is_valid_address(record["from_address"]):
        reasons.append("invalid From address")                      # D14
    if not record["to_addresses"]:
        reasons.append("missing To")                                # D4
    if record["subject"] is None:
        reasons.append("missing Subject header")                    # D5: blank is OK
    # D22: body is satisfied if the email has ANY text. A pure forward has an
    # empty primary body but its content is in forwarded/quoted.
    if not (record["body"] or record["forwarded_content"] or record["quoted_content"]):
        reasons.append("missing body")
    return reasons


def write_error_log(failures, path):
    """Write one failed file per line: source_file <TAB> reason(s)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("source_file\treason\n")
        for source_file, reason in failures:
            f.write(f"{source_file}\t{reason}\n")


# ---------------------------------------------------------------------------
# Step 7: write parsed records as JSON Lines  (D12)
# ---------------------------------------------------------------------------
def write_jsonl(records, path):
    """Write one JSON object per line. Lists stay lists; missing values are null."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def sample_category(record):
    """Name the kind of email this is, for picking the committed sample (D23)."""
    forwarded = record["forwarded_content"] or ""
    quoted = record["quoted_content"] or ""
    if record["subject"] == "":
        return "blank_subject"
    if record["has_attachment"]:
        return "attachment"
    if forwarded.count("Forwarded by") >= 2:
        return "nested_forward"
    if re.match(r"-{3,}\s*Original Message", quoted, re.IGNORECASE):
        return "outlook_reply"
    if quoted and not quoted.startswith(">"):
        return "notes_reply"
    if not forwarded and not quoted:
        return "plain"
    return None


def pick_sample(records, per_category):
    """Pick up to `per_category` records of each kind, each from a different
    mailbox where possible, so the sample is small but varied. Deterministic."""
    picked = {}      # category -> list of records
    for record in records:
        category = sample_category(record)
        if category is None:
            continue
        chosen = picked.setdefault(category, [])
        mailbox = record["source_file"].split("/")[1]
        used_mailboxes = {r["source_file"].split("/")[1] for r in chosen}
        if len(chosen) < per_category and mailbox not in used_mailboxes:
            chosen.append(record)
    return [record for category in sorted(picked) for record in picked[category]]


def relative_source(path):
    """Path relative to data/, e.g. 'maildir/lay-k/inbox/45.' (spec: source_file)."""
    return os.path.relpath(path, DATA_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Parse Enron email files.")
    parser.add_argument("--limit", type=int, default=None,
                        help="only process this many files (evenly spread sample)")
    args = parser.parse_args()

    all_paths = discover_files(MAILDIR, MAILBOXES)
    paths = take_sample(all_paths, args.limit)

    print(f"Files found: {len(all_paths)}")
    for mailbox in MAILBOXES:
        count = sum(1 for p in all_paths if relative_source(p).split(os.sep)[1] == mailbox)
        print(f"  {mailbox:12s} {count}")
    print(f"Files selected for this run: {len(paths)}")

    failures = []   # (source_file, reason) — written to error_log.txt in step 6
    records = []
    split_counts = {}   # marker name -> how many emails were cut at that marker
    notes_blocks_stripped = 0
    for path in paths:
        try:
            msg, raw_body = read_email(path)
            record = extract_header_fields(msg, path)
            body, forwarded, quoted, marker, stripped = split_body(raw_body)
            record["body"] = body
            record["forwarded_content"] = forwarded
            record["quoted_content"] = quoted
            # D21: search body + forwarded text. A Notes forward carries the
            # original's attachment along; a reply's quoted text usually does not.
            record["has_attachment"] = has_attachment(body) or has_attachment(forwarded)
            split_counts[marker or "no_marker"] = split_counts.get(marker or "no_marker", 0) + 1
            notes_blocks_stripped += stripped

            reasons = find_failure_reasons(record)
            if reasons:
                failures.append((record["source_file"], "; ".join(reasons)))
            else:
                records.append(record)
        except Exception as e:   # never let one bad file stop the run
            failures.append((relative_source(path), f"unexpected error: {type(e).__name__}: {e}"))

    write_error_log(failures, ERROR_LOG)
    write_jsonl(records, PARSED_JSONL)
    print(f"Wrote {len(records)} records to {os.path.relpath(PARSED_JSONL, PROJECT_ROOT)}")
    if args.limit is None:   # only refresh the committed sample on a full run
        sample = pick_sample(records, SAMPLE_PER_CATEGORY)
        write_jsonl(sample, SAMPLE_JSONL)
        print(f"Wrote {len(sample)} records to {os.path.relpath(SAMPLE_JSONL, PROJECT_ROOT)}")
    print(f"Parsed OK: {len(records)}   Failed: {len(failures)}   (failures written to {os.path.relpath(ERROR_LOG, PROJECT_ROOT)})")
    reason_counts = {}
    for _source, reason in failures:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda item: -item[1]):
        print(f"  {count:6d}  {reason}")

    print("Body split, by first marker found:")
    for marker, count in sorted(split_counts.items(), key=lambda item: -item[1]):
        print(f"  {marker:22s} {count:6d}")
    print(f"Leading Notes header blocks stripped (D17): {notes_blocks_stripped}")

    # Quick completeness check (full stats come in step 8).
    print("Field completeness (non-empty):")
    for field in records[0] if records else []:
        filled = sum(1 for r in records if r[field] not in (None, "", [], False))
        print(f"  {field:18s} {filled:6d}  {100 * filled / len(records):5.1f}%")


if __name__ == "__main__":
    main()
