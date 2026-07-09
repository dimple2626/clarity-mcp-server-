"""
server.py -- the MCP layer. This is the ONLY file that knows about MCP
itself. It wires together:
  - clarity_client.py  (talks to Microsoft Clarity)
  - cache.py           (protects your 10-requests/day quota)
  - fastmcp's auth      (so random people can't hit your manager's data)
  - streamable-http transport (so this is reachable over a URL, not just stdio)

WHY EACH TOOL EXISTS (matches the 4 tools you've already been building):
  1. get_traffic_overview      -> big picture, no breakdown
  2. get_insights_by_dimension -> one breakdown (e.g. by Device)
  3. get_cross_dimension_insights -> up to 3 breakdowns at once
  4. list_valid_dimensions     -> zero-cost helper so Claude/manager can
                                   see valid dimension names without
                                   guessing and wasting an API call
"""

import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from clarity_client import ClarityClient
from cache import TTLCache
from exceptions import ClarityError

load_dotenv()  # reads variables from a local .env file into os.environ

# ---------------------------------------------------------------------
# 1. CONFIG -- read secrets from environment, never hardcode them
# ---------------------------------------------------------------------
CLARITY_API_TOKEN = os.environ.get("CLARITY_API_TOKEN")
MCP_ACCESS_TOKEN = os.environ.get("MCP_ACCESS_TOKEN")  # the token YOU give your manager
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))
SERVER_PORT = int(os.environ.get("PORT", "8000"))

if not CLARITY_API_TOKEN:
    raise RuntimeError(
        "CLARITY_API_TOKEN is not set. Create a .env file (see .env.example) "
        "with your Clarity Data Export API token."
    )
if not MCP_ACCESS_TOKEN:
    raise RuntimeError(
        "MCP_ACCESS_TOKEN is not set. This is the token YOUR MANAGER will use "
        "to connect to this server -- pick any long random string and put it "
        "in .env. Generate one quickly with: python -c \"import secrets; "
        "print(secrets.token_urlsafe(32))\""
    )

# ---------------------------------------------------------------------
# 2. AUTH -- StaticTokenVerifier is FastMCP's built-in way to protect a
# server with a fixed bearer token (no OAuth provider needed for this
# use case -- it's just you and your manager, not the public internet).
# Whoever connects must send: Authorization: Bearer <MCP_ACCESS_TOKEN>
# ---------------------------------------------------------------------
verifier = StaticTokenVerifier(
    tokens={
        MCP_ACCESS_TOKEN: {
            "client_id": "manager",
            "scopes": ["read:clarity"],
        }
    },
    required_scopes=["read:clarity"],
)

# ---------------------------------------------------------------------
# 3. WIRE UP THE CLIENT + CACHE (built once, reused across every request)
# ---------------------------------------------------------------------
clarity = ClarityClient(api_token=CLARITY_API_TOKEN)
cache = TTLCache(default_ttl_seconds=CACHE_TTL_SECONDS)

mcp = FastMCP(name="clarity-mcp-server", auth=verifier)


def _safe(fn):
    """Wrap Clarity calls so any ClarityError becomes a clean, readable
    string for the LLM/manager instead of a raw Python traceback."""
    try:
        return fn()
    except ClarityError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------
# 4. THE FOUR TOOLS
# ---------------------------------------------------------------------

@mcp.tool()
def get_traffic_overview(num_of_days: int = 3) -> dict:
    """Get overall Clarity traffic metrics (Traffic, EngagementTime,
    ScrollDepth, rage clicks, dead clicks, etc.) with no dimension
    breakdown -- the headline numbers for the site.

    Args:
        num_of_days: 1, 2, or 3 (last 24h, 48h, or 72h). Defaults to 3.
    """
    result = cache.get_or_set(
        key_parts=("traffic_overview", num_of_days),
        fetch_fn=lambda: _safe(lambda: clarity.get_traffic_overview(num_of_days)),
    )
    return result


@mcp.tool()
def get_insights_by_dimension(num_of_days: int, dimension: str) -> dict:
    """Get Clarity metrics broken down by a single dimension, e.g. by
    Device (Desktop/Mobile/Tablet) or Browser or Country/Region.

    Args:
        num_of_days: 1, 2, or 3.
        dimension: one of the values from list_valid_dimensions().
    """
    result = cache.get_or_set(
        key_parts=("insights_by_dimension", num_of_days, dimension),
        fetch_fn=lambda: _safe(
            lambda: clarity.get_insights_by_dimension(num_of_days, dimension)
        ),
    )
    return result


@mcp.tool()
def get_cross_dimension_insights(
    num_of_days: int,
    dimension1: str,
    dimension2: str = None,
    dimension3: str = None,
) -> dict:
    """Get Clarity metrics broken down by up to THREE dimensions at once
    (e.g. Device x Browser x Country/Region), for more granular
    cross-cuts of the data.

    Args:
        num_of_days: 1, 2, or 3.
        dimension1: required first breakdown dimension.
        dimension2: optional second breakdown dimension.
        dimension3: optional third breakdown dimension.
    """
    result = cache.get_or_set(
        key_parts=("cross_dimension", num_of_days, dimension1, dimension2, dimension3),
        fetch_fn=lambda: _safe(
            lambda: clarity.get_cross_dimension_insights(
                num_of_days, dimension1, dimension2, dimension3
            )
        ),
    )
    return result


@mcp.tool()
def list_valid_dimensions() -> list:
    """List the dimension names accepted by Clarity for breaking down
    insights (Browser, Device, Country/Region, OS, etc.). This never
    calls the Clarity API and never uses up your daily quota."""
    return clarity.list_valid_dimensions()


# ---------------------------------------------------------------------
# 5. RUN THE SERVER OVER STREAMABLE-HTTP (not stdio) so it's reachable
# by URL -- this is what makes it a "remote" MCP server your manager
# can connect to from anywhere, once you expose the port via a tunnel.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Starting Clarity MCP server on http://0.0.0.0:{SERVER_PORT}/mcp")
    print("Give your manager the tunnel URL + the MCP_ACCESS_TOKEN from your .env")
    mcp.run(transport="http", host="0.0.0.0", port=SERVER_PORT)
