# AI Usage Log

How I used Claude Code (Opus 5.5) during this challenge: what I asked for, what it did, and what I checked or decided myself.

---

## 1. Project setup (requirements, .gitignore, venv install)

- **What I asked:** Create `requirements.txt` (rapidfuzz, python-dateutil, mcp, python-dotenv, tqdm, pytest) and a `.gitignore` (.venv/, data/, *.db, .env, .mcp.json, __pycache__/, .DS_Store, .pytest_cache/), install into the local `.venv`, then pin exact versions.
- **What it did:**
  - Noticed the `.venv` wasn't active in the shell (`which python` → miniforge base), so it activated `.venv` first and confirmed `which python` → `.venv/bin/python` (Python 3.13.12).
  - Installed with `pip install -r requirements.txt` — success, `pip check` reports no broken requirements (38 packages total incl. transitive deps).
  - Pinned the 6 direct packages to the versions shown by `pip freeze`.
- **My decision:** I pinned only my 6 direct dependencies, not the full 38-line freeze, to keep `requirements.txt` to "exactly these packages". Trade-off: transitive deps can still drift; if I need full reproducibility I can add a `requirements-lock.txt` from `pip freeze`.
- **No pipeline code written in this step.**

## 2. Lock file for reproducibility

- **What I asked:** Keep `requirements.txt` as is (6 direct deps, pinned), save the full `pip freeze` as `requirements-lock.txt`, add a one-line purpose comment to each, note the lock file in SETUP.md, and log the decision.
- **What it did:** Created `requirements-lock.txt` (38 pinned packages + header comment), added a header comment to `requirements.txt`, added an install-from-lock note to SETUP.md section 4, and created DECISIONS.md with D1.
- **My decision:** I chose option (c), both files. See DECISIONS.md D1.

## 3. MCP integration

- **What I asked:** Review `mcp_server/gmail_server.py`, check that it starts, give me the `claude mcp add` command (project scope, absolute paths), create `mcp_config.json.example`, and document it. I said not to read or print `.env`.
- **What it did:**
  - Reviewed the server: it is a FastMCP stdio server with one `send_email` tool that sends via Gmail SMTP_SSL, using credentials loaded from `.env`.
  - Start check **failed**: `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. The installed `mcp==2.3.0` renamed `FastMCP` → `MCPServer` (`mcp.server.mcpserver`). It confirmed the 2.x class exists, and that 1.x (latest 1.30.0) is still on PyPI.
  - Confirmed `.env` exists (with `test -f` only; it was never opened).
  - Created `mcp_config.json.example` (placeholder paths, empty `env`) and ARCHITECTURE.md (MCP section).
- **Resolved:** I pinned `mcp==1.30.0` (DECISIONS.md D2). See debugging story #1 below. The server now starts cleanly, and I register it myself with `claude mcp add`.
- **Registration (I ran it myself):** `claude mcp add gmail --scope project ...` wrote `.mcp.json`. `claude mcp get gmail` shows Scope: Project, Type: stdio, Status: ✔ Connected. `.mcp.json` is git-ignored (`.gitignore` line 5).
- **Config check:** `.mcp.json` and `mcp_config.json.example` have identical structure (`mcpServers.gmail` with `type: stdio`, `command`, `args`, `env: {}`). The only difference is absolute paths vs `/path/to/...` placeholders, so the example needed no changes. Neither file contains secrets.
- **Live test send (first attempt, blocked):** I asked Claude to send "MCP test" / "hello from Claude Code" to my Gmail with `send_email`. The tool wasn't available in that Claude session: Claude Code loads MCP servers at session start, and I registered `gmail` after the session began. Claude deliberately did **not** work around this by calling SMTP from a script, because the assignment needs proof of a send *through the MCP tool*.
- **Live test send (done, new session):** After restarting `claude`, the `mcp__gmail__send_email` tool was available. Claude called it with to `swara.awsm@gmail.com`, subject "MCP test", body "hello from Claude Code". Tool result: `sent to swara.awsm@gmail.com (Message-ID <179390911815.21710.5710468976951489097@dedup.local>)`. **Succeeded:** I confirmed the email arrived in my Gmail inbox. The screenshot is in `docs/mcp_test_send.png`.
- **Config re-check (same session):** I compared `.mcp.json` with `mcp_config.json.example` again. They still have the same structure (`mcpServers.gmail` → `type: stdio`, `command`, `args` [1 item], `env: {}`). The only difference is still absolute paths vs `/path/to/...` placeholders, so I left the example unchanged.

---

# Debugging stories

## Debugging story #1: AI-generated code vs. an unpinned dependency

- **Symptom:** the Gmail MCP server crashed on import with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`.
- **Cause:** `gmail_server.py` was AI-generated code written against the **mcp 1.x** API (`FastMCP`). My first `requirements.txt` was unpinned, so `pip` installed the newest release, **mcp 2.3.0**, where `FastMCP` was renamed to `MCPServer`. Pinning *after* install (step 1) only froze the broken version.
- **How we found it:** a quick start check before registering the server. The error message itself named the 2.x rename and pointed to `mcp<2`.
- **Fix:** I pinned `mcp==1.30.0`, reinstalled, and regenerated `requirements-lock.txt`. Claude noticed the downgrade had left 5 orphan 2.x-only packages in `.venv`. It did a fresh install into a temporary venv to see what *should* be there, removed the orphans, and confirmed the lock file matches a clean install (38 packages).
- **Verified:** the import succeeds, the MCP `initialize` handshake succeeds, and `tools/list` returns `send_email`.
- **Lesson:** pin dependencies up front, especially for fast-moving libraries like `mcp`, and check that AI-generated code matches the installed library version before building on it. Also: a downgrade can leave packages behind, so regenerate lock files from a clean install, not from a reused venv.
