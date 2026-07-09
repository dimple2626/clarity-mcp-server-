# Clarity MCP Server — Remote Setup Guide

A Model Context Protocol (MCP) server that lets Claude query
Microsoft Clarity analytics — and lets a remote client connect to it
from Claude Desktop, running entirely off your office PC.

---

## 1. How the pieces fit together

```
Your office PC
┌─────────────────────────────────────────────────┐
│  server.py  (FastMCP, listens on port 8000)      │
│     │                                            │
│     ├── clarity_client.py  → calls Clarity API   │
│     ├── cache.py           → saves your 10/day   │
│     │                        quota               │
│     └── bearer token auth  → blocks strangers     │
└─────────────────────┬─────────────────────────────┘
                       │
                  ngrok / Cloudflare Tunnel
                       │  (makes an outbound connection,
                       │   gives you a public https:// URL)
                       ▼
              https://your-tunnel-url.ngrok-free.app/mcp
                       │
                       ▼
              Claude Desktop (custom connector)
```

Four files do the actual work:

| File | Job |
|---|---|
| `exceptions.py` | Defines specific error types (auth failed, bad input, rate-limited) so failures are readable, not raw tracebacks |
| `cache.py` | A simple 1-hour cache so repeat questions don't burn your 10-requests/day Clarity quota |
| `clarity_client.py` | The only file that talks to Clarity's real API — validates input, handles auth, parses responses |
| `server.py` | Wraps all of the above as 4 MCP tools, adds bearer-token auth, and serves it over HTTP instead of stdio |

---

## 2. Why HTTP instead of stdio

Every MCP tutorial you'll find starts with **stdio transport** — the
server and client run as one local process pair, no networking
involved. That's great for testing on your own machine, but a client
sitting elsewhere can't spawn a process on your PC. So this server
uses **streamable-HTTP transport** instead: it's a normal web server
listening on a port, reachable by URL, exactly like any REST API.

That single line does it:
```python
mcp.run(transport="http", host="0.0.0.0", port=8000)
```

---

## 3. Why authentication is not optional here

The moment your server has a public URL, it's public — not "unlisted,"
actually public. Anyone who discovers the URL could call your Clarity
tools and burn your 10 daily requests, or worse. So this server uses
FastMCP's `StaticTokenVerifier`: a single secret string
(`MCP_ACCESS_TOKEN`) that the client must send with every request as
`Authorization: Bearer <token>`. No token, no access — verified above:
requests without it get an immediate `401`.

This token is **not** your Clarity API token. Think of it as a second,
separate password — one you invent, one that only unlocks your MCP
server, never Clarity directly.

---

## 4. Setup on your Windows PC (PowerShell)

```powershell
# 1. Get the project onto your PC (copy this folder over, or unzip it)
cd C:\Users\<you>\clarity-mcp-server

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your real .env file from the example
Copy-Item .env.example .env
notepad .env
```

In `.env`, fill in:
- `CLARITY_API_TOKEN` — from Clarity dashboard: **Settings → Data Export → Generate new API token**
- `MCP_ACCESS_TOKEN` — invent one. Quick way:
  ```powershell
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
  Paste the output in as `MCP_ACCESS_TOKEN`.

```powershell
# 5. Run the server
python server.py
```

You should see `Starting Clarity MCP server on http://0.0.0.0:8000/mcp`.
Leave this window open — closing it stops the server.

---

## 5. Making it reachable from outside the office (the tunnel)

Since the connecting client is remote and you can't port-forward on an office
network, use a tunnel — it makes an *outbound* connection from your PC,
so no firewall changes or IT tickets needed.

**Option A — ngrok (fastest to test):**
```powershell
# one-time: download from https://ngrok.com/download, unzip, then:
.\ngrok.exe http 8000
```
It prints a URL like `https://a1b2c3d4.ngrok-free.app` — this forwards
to your local port 8000. Free tier URLs change every restart; fine for
demos, annoying for daily use.

**Option B — Cloudflare Tunnel (more stable, still free):**
```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8000
```
Gives a similar public URL, and can be configured with a fixed
subdomain if you set up a free Cloudflare account.

Either way, the client's connector URL becomes:
```
https://<your-tunnel-domain>/mcp
```

---

## 6. What to share with the connecting client

Two things, ideally over a secure channel (Teams DM, not email in plaintext):
1. The tunnel URL: `https://your-tunnel-url/mcp`
2. The `MCP_ACCESS_TOKEN` value from your `.env`

**Their side (Claude Desktop):**
Settings → Connectors → Add custom connector → paste the URL → when
prompted for a header, add:
```
Authorization: Bearer <the MCP_ACCESS_TOKEN you gave them>
```

Once connected, they can ask Claude things like *"what's our traffic
overview for the last 3 days?"* and Claude will call your
`get_traffic_overview` tool.

---

## 7. Testing it yourself first (recommended before sharing access)

```powershell
# Terminal 1
python server.py

# Terminal 2 — simulate a request without a token (should fail with 401)
curl.exe -X POST http://localhost:8000/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}"

# With the token (should get further)
curl.exe -X POST http://localhost:8000/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Authorization: Bearer YOUR_MCP_ACCESS_TOKEN" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}"
```

---

## 8. Known limitations, said plainly

- **Uptime is tied to your PC.** Sleep, restart, or closing the
  terminal kills the connection. Fine for a scheduled demo, not for
  something a client relies on daily.
- **10 requests/day is Microsoft's hard limit**, not something this
  code can raise. The cache buys you headroom, it doesn't remove the
  ceiling — after the cache TTL expires, a fresh question still spends
  a real request.
- **Dimension names**: the list in `clarity_client.py` (`Browser`,
  `Device`, `Country/Region`, `OS`, `Source`, `Medium`, `Campaign`,
  `Channel`, `URL`) matches Clarity's dashboard filters, but Microsoft
  doesn't publish one definitive canonical list, and multi-word
  dimensions have had quirks in the past (see
  `microsoft/clarity#630` on GitHub). If a dimension call errors out
  unexpectedly, double check the exact spelling against your own
  Clarity dashboard's filter dropdown.
- **Free ngrok URLs are not permanent** — if you restart ngrok, the
  URL changes and you'll need to re-share it with the client.

---

## 9. If this becomes more than a demo

Running long-term off a desk PC + tunnel is a workaround, not a real
deployment. If ongoing access is needed, the natural next
step — especially since your office already uses Microsoft tooling —
is deploying `server.py` to **Azure App Service** or a small **Azure
Container App**, which gives you a permanent HTTPS URL, no tunnel, and
no dependency on your PC staying on.
