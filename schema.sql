-- Enron email database schema (SQLite). Task 2.
-- Applied by src/load_db.py. Every statement uses IF NOT EXISTS, so applying
-- it again is safe (D30). Decisions: D25-D31 in DECISIONS.md.

-- One row per parsed email (D27: integer id + unique message_id).
CREATE TABLE IF NOT EXISTS emails (
    id                 INTEGER PRIMARY KEY,
    message_id         TEXT    NOT NULL UNIQUE,        -- spec: unique constraint
    date               TEXT    NOT NULL,               -- UTC ISO-8601, e.g. 2001-05-14T23:39:00+00:00 (D31)
    from_address       TEXT    NOT NULL,
    subject            TEXT    NOT NULL,               -- may be '' (D5)
    body               TEXT    NOT NULL,               -- may be '' for pure forwards (D22)
    forwarded_content  TEXT,
    quoted_content     TEXT,
    headings           TEXT,                           -- one heading per line (D11)
    x_from             TEXT,
    x_to               TEXT,
    x_cc               TEXT,
    x_bcc              TEXT,
    x_folder           TEXT,
    x_origin           TEXT,
    content_type       TEXT,
    has_attachment     INTEGER NOT NULL DEFAULT 0 CHECK (has_attachment IN (0, 1)),
    source_file        TEXT    NOT NULL,

    -- Task 3/4 state (D28). A re-load never overwrites these (D30).
    is_duplicate       INTEGER NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0, 1)),
    duplicate_of       TEXT    REFERENCES emails(message_id),   -- the original's message_id
    similarity_score   REAL,                                    -- vs the original, 0-100
    notification_sent  INTEGER NOT NULL DEFAULT 0 CHECK (notification_sent IN (0, 1)),
    notification_date  TEXT                                     -- UTC ISO-8601
);

-- Each distinct address stored once (D26).
CREATE TABLE IF NOT EXISTS addresses (
    id       INTEGER PRIMARY KEY,
    address  TEXT NOT NULL UNIQUE
);

-- Who received each email, and how (D26). One row per (email, address, type) (D29).
CREATE TABLE IF NOT EXISTS email_recipients (
    email_id        INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    address_id      INTEGER NOT NULL REFERENCES addresses(id),
    recipient_type  TEXT    NOT NULL CHECK (recipient_type IN ('to', 'cc', 'bcc')),
    PRIMARY KEY (email_id, address_id, recipient_type)
);

-- Indexes required by the spec.
CREATE INDEX IF NOT EXISTS idx_emails_date         ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_from_address ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_subject      ON emails(subject);

-- Extra indexes: "emails received by X", and Task 3/4 lookups.
CREATE INDEX IF NOT EXISTS idx_recipients_address  ON email_recipients(address_id);
CREATE INDEX IF NOT EXISTS idx_emails_is_duplicate ON emails(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_emails_duplicate_of ON emails(duplicate_of);
