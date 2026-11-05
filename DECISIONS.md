# Decisions

Each decision or assumption, the options I considered, why I chose this one, and how many rows it affected.

---

## D1. How to pin dependencies

- **Options:**
  - (a) Direct deps only: `requirements.txt` with my 6 packages pinned
  - (b) Full freeze only: `requirements.txt` = `pip freeze` (38 packages)
  - (c) Both: short `requirements.txt` + full `requirements-lock.txt`
- **I chose (c).** `requirements.txt` stays short and readable (it shows what the project actually depends on), and `requirements-lock.txt` guarantees reproducibility by pinning all 38 packages, including transitive ones.
- **Rows affected:** none (environment setup, no data change).

## D2. Fixing the MCP server import failure (mcp 1.x vs 2.x)

- **Context:** `gmail_server.py` imports `mcp.server.fastmcp.FastMCP` (1.x API). The unpinned install pulled `mcp==2.3.0`, where it was renamed to `mcp.server.mcpserver.MCPServer`, so the server crashed on import.
- **Options:**
  - (a) Pin `mcp==1.30.0` (latest 1.x) and keep the code as written
  - (b) Port the server to the 2.x `MCPServer` API and keep `mcp==2.3.0`
  - (c) Use a version range instead of an exact pin
- **I chose (a).** The code is known to work on 1.x, porting would bring in 2.x API changes I'd have to explain, and the risk is lower under time pressure.
- **Why not (c):** a bare `>=` range (e.g. `mcp>=1.30`) would still allow 2.x and the same crash. A bounded `>=1.30,<2` would block 2.x, but it would still allow untested 1.x releases, so an exact pin is more reproducible.
- **Side effect:** downgrading left 5 orphan packages that only 2.x needed (`httpcore2`, `httpx2`, `mcp-types`, `opentelemetry-api`, `truststore`). I removed them so `requirements-lock.txt` (38 packages) exactly matches a fresh install of `requirements.txt`.
- **Verified:** the server imports, completes the MCP `initialize` handshake, and lists the `send_email` tool.
- **Rows affected:** none (environment setup, no data change).

## D3. Mailbox selection

- **Context:** the assignment needs at least 10k emails. I'm using a subset of the Enron maildir.
- **Options:**
  - (a) The largest mailboxes (20k+ emails each)
  - (b) Randomly picked mailboxes
  - (c) Senior executives who wrote to each other
- **I chose (c):** `lay-k`, `skilling-j`, `whalley-l`, `lavorato-j`, `delainey-d`. Because these people corresponded, the same message shows up in several of their mailboxes and folders (sent, inbox, `all_documents`, `discussion_threads`). That gives duplicate detection realistic cross-mailbox cases. At about 21.7k emails, it also keeps iteration fast while clearing the 10k minimum.
- **Why not (a):** each large mailbox alone is 20k+ emails, which slows iteration, and one person's mailbox has fewer cross-mailbox duplicates.
- **Why not (b):** random mailboxes may never have written to each other, so there would be few realistic cross-mailbox duplicates.
- **Rows affected:** 21,662 files in scope. I verified the count with `find -type f`: lay-k 5,937 · skilling-j 4,139 · whalley-l 3,335 · lavorato-j 4,685 · delainey-d 3,566.
