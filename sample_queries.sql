-- Sample queries for the Enron email database (Task 2, D34).
-- Run:  sqlite3 output/enron.db < sample_queries.sql
-- (after: python src/parse_emails.py && python src/load_db.py)
-- Note: query 5 fails ON PURPOSE (it shows the unique constraint), so the
-- sqlite3 CLI prints one "Runtime error" and exits with code 1. The other
-- queries still run, and the database is not changed.
--
-- Each query has an "Expected output" note recorded from the full load
-- (20,339 emails, 11,146 recipient addresses, 190,390 recipient rows).

.headers on
.mode column


-- ---------------------------------------------------------------------------
-- 1. Emails per sender: top 10 senders by number of emails.
--    Uses the index on from_address.
-- Expected output: 10 rows, largest first. Top 3:
--   david.delainey@enron.com    2961
--   john.lavorato@enron.com     2299
--   rosalee.fleming@enron.com    904   (Ken Lay's assistant)
-- then sherri.sera 687, liz.taylor 473, lavorato@enron.com 401, kay.chapman 365,
-- greg.whalley 361, enron.announcements 360, leonardo.pacheco 177.
-- Note: john.lavorato@ and lavorato@ are the same person under two addresses
-- (a known Task 3 limitation, see PLAN.md).
-- ---------------------------------------------------------------------------
SELECT from_address, COUNT(*) AS emails
FROM emails
GROUP BY from_address
ORDER BY emails DESC
LIMIT 10;


-- ---------------------------------------------------------------------------
-- 2. Emails in a date range: October 2001 (UTC), the month Enron's collapse began.
--    Dates are UTC ISO-8601 text, so a text range works and uses the date index.
-- Expected output: a count of 650, then the first 5 emails of the month by time:
--   2001-10-01T05:27:19+00:00  andrew.henderson@enron.com    Internet
--   2001-10-01T13:01:22+00:00  mark.lay@solutioncompany.com  Bush Economic Team "Inept"
--   2001-10-01T14:41:34+00:00  bpaddock@ghcf.org             Oct. 3rd meeting
--   ... (2 more). Subjects are cut to 50 characters for display.
-- ---------------------------------------------------------------------------
SELECT COUNT(*) AS emails_in_october_2001
FROM emails
WHERE date >= '2001-10-01' AND date < '2001-11-01';

SELECT date, from_address, SUBSTR(subject, 1, 50) AS subject
FROM emails
WHERE date >= '2001-10-01' AND date < '2001-11-01'
ORDER BY date
LIMIT 5;


-- ---------------------------------------------------------------------------
-- 3. Emails with CC recipients: how many, and a sample with their Cc lists.
--    Joins through email_recipients and addresses (the normalised tables).
-- Expected output: a count of 5471 (matches the parser's cc_addresses
-- completeness), then the 5 earliest emails with Cc, each with its Cc list.
-- The first 3 rows are the SAME email ("Education Survey", 1998-01-06,
-- jan_levine@travisintl.com -> cc wvlarkin@travisintl.com) stored in 3 folders:
-- exactly the kind of cross-folder copy Task 3 will flag.
-- ---------------------------------------------------------------------------
SELECT COUNT(DISTINCT email_id) AS emails_with_cc
FROM email_recipients
WHERE recipient_type = 'cc';

SELECT e.date, e.from_address, SUBSTR(e.subject, 1, 30) AS subject, COUNT(*) AS cc_count,
       GROUP_CONCAT(a.address, ', ') AS cc_addresses
FROM emails e
JOIN email_recipients r ON r.email_id = e.id AND r.recipient_type = 'cc'
JOIN addresses a ON a.id = r.address_id
GROUP BY e.id
ORDER BY e.date
LIMIT 5;


-- ---------------------------------------------------------------------------
-- 4. All recipients of one email, by type.
--    Shows one email's To/Cc/Bcc rebuilt from the normalised tables
--    (maildir/skilling-j/inbox/1533., Karen Denne -> Jeff Skilling).
-- Expected output: 9 rows:
--   to   jeff.skilling@enron.com
--   cc   joannie.williamson@enron.com, karen.denne@enron.com,
--        mark.palmer@enron.com, meredith.philipp@enron.com   (4 rows)
--   bcc  the same 4 addresses as cc   (Bcc copies Cc in this dataset, D7)
-- ---------------------------------------------------------------------------
SELECT r.recipient_type, a.address
FROM emails e
JOIN email_recipients r ON r.email_id = e.id
JOIN addresses a ON a.id = r.address_id
WHERE e.message_id = '<7474422.1075852683329.JavaMail.evans@thyme>'
ORDER BY CASE r.recipient_type WHEN 'to' THEN 1 WHEN 'cc' THEN 2 ELSE 3 END, a.address;


-- ---------------------------------------------------------------------------
-- 5. The unique constraint on message_id: inserting an email whose
--    message_id already exists is rejected.
-- Expected output: the INSERT fails with
--   Runtime error ...: UNIQUE constraint failed: emails.message_id (19)
-- and the count afterwards is still 1. No row was added (verified: the DB
-- file's MD5 is identical before and after running this whole script).
-- ---------------------------------------------------------------------------
INSERT INTO emails (message_id, date, from_address, subject, body, source_file)
VALUES ('<7474422.1075852683329.JavaMail.evans@thyme>',
        '2001-01-01T00:00:00+00:00', 'test@example.com', 'duplicate insert', '', 'n/a');

SELECT COUNT(*) AS rows_with_this_message_id
FROM emails
WHERE message_id = '<7474422.1075852683329.JavaMail.evans@thyme>';


-- ---------------------------------------------------------------------------
-- 6. Duplicate groups (only returns rows after Task 3 has run).
--    Each original with how many emails were flagged as its duplicates.
-- Expected output: no rows until Task 3 has run (before Task 3, every
-- is_duplicate = 0). After Task 3: up to 10 originals with the most flagged
-- duplicates, their lowest similarity score (>= 90) and latest duplicate date.
-- (Real output to be recorded here after Task 3.)
-- ---------------------------------------------------------------------------
SELECT o.message_id AS original_message_id, o.from_address, SUBSTR(o.subject, 1, 40) AS subject,
       o.date AS original_date,
       COUNT(d.id) AS duplicates_flagged,
       ROUND(MIN(d.similarity_score), 1) AS min_similarity,
       MAX(d.date) AS latest_duplicate_date
FROM emails o
JOIN emails d ON d.duplicate_of = o.message_id AND d.is_duplicate = 1
GROUP BY o.id
ORDER BY duplicates_flagged DESC, o.date
LIMIT 10;
