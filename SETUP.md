# Setup

Everything below runs in a **terminal** unless it says otherwise.
- **Mac:** Cmd + Space → "Terminal". **Windows:** Start → "PowerShell". VS Code also has one built in (View → Terminal).
- The terminal is always "in" a folder. `cd <folder>` moves into it, `pwd` shows where you are.
- Commands are Mac/Linux style. Windows differences are noted inline.

---

## 0. Prerequisites

- **Python 3.11+**: check with `python3 --version`; install from python.org if missing.
- **git**: check with `git --version`.
- **Claude Code**: `curl -fsSL https://claude.ai/install.sh | sh`
  (or `npm install -g @anthropic-ai/claude-code` with Node 18+; don't use sudo). Run `claude` once to log in.
- **VS Code** (optional, recommended) for editing files.

## 1. Create the project folder

You don't make folders by hand; these commands do it. Start from your home folder (where a new terminal opens).

```bash
mkdir enron-dedup
cd enron-dedup
mkdir -p src mcp_server output/replies data docs
```

## 2. Download the dataset (start this early, it's slow)

```bash
cd data
curl -O https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
```

While it downloads, open a second terminal tab (Cmd+T), `cd ~/enron-dedup`, and carry on with steps 4–6.

## 3. Pick and extract mailboxes

Count emails per person without extracting anything (run inside `data/`):

```bash
tar -tzf enron_mail_20150507.tar.gz | grep -v '/$' | awk -F/ '{print $2}' | sort | uniq -c | sort -rn | head -40
```

Pick **5 mailboxes totaling ~12–20k emails**, ideally people who emailed each other (e.g. executives and their circle). Write down why; it goes in the README and DECISIONS.md.

Extract only those (replace the names with your picks):

```bash
tar -xzf enron_mail_20150507.tar.gz maildir/lay-k maildir/skilling-j maildir/kean-s maildir/<4th> maildir/<5th>
cd ..
```

Windows 10+ has `tar` built in; the extract command works the same in PowerShell. The count command needs Git Bash or WSL on Windows.

## 4. Python environment

```bash
git init
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

You'll see `(.venv)` at the start of the line when it's active. **Re-run the activate command every time you open a new terminal.**

Create `requirements.txt` (in VS Code: File → Open Folder → `enron-dedup`):

```
rapidfuzz
python-dateutil
mcp
python-dotenv
tqdm
pytest
```

```bash
pip install -r requirements.txt
```

**For the exact tested environment** (every package pinned, including transitive deps), install from the lock file instead:

```bash
pip install -r requirements-lock.txt
```

`requirements.txt` lists only the 6 direct dependencies (pinned); `requirements-lock.txt` is the full `pip freeze`.

Create `.gitignore`:

```
.venv/
data/
*.db
.env
__pycache__/
.mcp.json
```

## 5. Gmail App Password (in your browser)

1. myaccount.google.com → **Security** → turn on **2-Step Verification** (required).
2. Search "App passwords" in the account settings search bar → create one named `enron-dedup`.
3. Copy the 16-character password (shown once).
4. Create `.env` in the project root (never commit this):

```
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=abcdefghijklmnop
NOTIFY_TO=you@gmail.com
```

Paste the password without spaces. `NOTIFY_TO` is where live notifications actually go, since the original Enron addresses are dead.

## 6. MCP server

Put `gmail_server.py` at `mcp_server/gmail_server.py`. It exposes one tool, `send_email(to, subject, body, references)`, which sends through Gmail SMTP using the `.env` values.

Quick check that it starts (Ctrl+C to stop; it will sit silently waiting, which is correct):

```bash
python mcp_server/gmail_server.py
```

## 7. Register the server with Claude Code and test it

From the project root:

```bash
claude mcp add gmail --scope project -- "$(pwd)/.venv/bin/python" "$(pwd)/mcp_server/gmail_server.py"
claude mcp list
```

On Windows the Python path is `.venv\Scripts\python.exe`. `--scope project` writes `.mcp.json` in the repo.

Then:

1. Run `claude`, then type `/mcp`. You should see `gmail` and its `send_email` tool.
2. Prompt: *"Use the gmail send_email tool to send a test email to you@gmail.com with subject 'MCP test' and body 'hello from Claude Code'."*
3. Check your inbox. **Take a screenshot**; the assignment requires proof of a live send.

If it fails with an auth error, it's almost always one of these: 2FA is off, the password has spaces, or `GMAIL_USER` doesn't match the account the password belongs to.

## 8. Config template

Copy `.mcp.json` to `mcp_config.json.example` and replace your absolute paths with placeholders like `/path/to/enron-dedup/...`. This file gets committed; `.mcp.json` doesn't.

## 9. Hand off to Claude Code

Make sure these are in the repo root / `docs/`:

- `CLAUDE.md`: how we work (Claude Code reads it automatically)
- `docs/ASSIGNMENT.md`: the full spec
- `SETUP.md`: this file

```bash
git add .
git commit -m "Project setup: skeleton, MCP server, docs"
claude
```

First prompt: *"Read CLAUDE.md and docs/ASSIGNMENT.md, then sample emails from data/maildir and do step 1 of the workflow."*

Final layout:

```
enron-dedup/
  CLAUDE.md
  SETUP.md
  requirements.txt
  .env                  (not committed)
  .mcp.json             (not committed)
  mcp_config.json.example
  docs/ASSIGNMENT.md
  data/maildir/...      (not committed)
  mcp_server/gmail_server.py
  output/replies/
  src/
```