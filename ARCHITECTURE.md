# Architecture

Inputs → scripts → outputs. (Pipeline sections get added as I build each step.)

---

## MCP server (Gmail notifications)

```
 Claude Code ──(stdio, MCP)──► mcp_server/gmail_server.py ──(SMTP_SSL :465)──► smtp.gmail.com ──► NOTIFY_TO inbox
      ▲                               │
      │                               └─ reads GMAIL_USER / GMAIL_APP_PASSWORD from .env (not committed)
  .mcp.json (project scope, not committed)
  mcp_config.json.example (committed template, placeholder paths)
```

- **What it is:** a small, separate process that exposes one tool, `send_email(to, subject, body, references)`. It has no knowledge of the dedup pipeline.
- **How it's launched:** Claude Code starts it via `.mcp.json` using the project's `.venv/bin/python` and talks to it over stdin/stdout (stdio transport).
- **How it fits in:** the pipeline writes its results (and drafted replies in `output/replies/`) to disk. Claude Code then calls `send_email` to send live notifications. Because the original Enron addresses are dead, they go to `NOTIFY_TO`. Setting `references` to the original Message-ID makes the email thread as a reply.
- **Secrets:** they only ever live in `.env`, which the server loads itself. `.mcp.json` and the example config contain no credentials.
