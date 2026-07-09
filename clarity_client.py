"""
clarity_client.py -- the service layer that talks to Microsoft Clarity.

This file knows NOTHING about MCP, tools, or Claude. Its only job is:
  1. Take a well-formed request in Python terms (numOfDays, dimensions)
  2. Validate it BEFORE spending an API call
  3. Call the real Clarity Data Export API
  4. Turn the raw response (or a raw error) into either clean data or one
     of our custom exceptions

Keeping this separate from the MCP tool layer means you could reuse this
exact client in a completely different context (a CLI script, a Flask
app, a scheduled job) without any MCP code getting in the way.

Official endpoint reference:
  GET https://www.clarity.ms/export-data/api/v1/project-live-insights
  Auth: Authorization: Bearer <token>
  Params: numOfDays (1, 2, or 3), dimension1, dimension2, dimension3 (all optional)
  Limit: 10 requests per project per day (enforced by Microsoft, not us)
"""

import requests
from typing import Optional

from exceptions import (
    ClarityAuthError,
    ClarityValidationError,
    ClarityRateLimitError,
    ClarityAPIError,
)

CLARITY_API_URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights"

# These are the dimension names Clarity's dashboard exposes for filtering.
# NOTE: Microsoft's own docs don't publish one single canonical list, and
# there have been reported issues (see microsoft/clarity#630 on GitHub)
# where multi-word dimension names like "Popular Pages" don't work as
# expected from the API even though they appear on the dashboard. Treat
# this list as a strong starting point, and verify against your own
# Clarity project's dashboard filter dropdown if a dimension errors out.
VALID_DIMENSIONS = [
    "Browser",
    "Device",
    "Country/Region",
    "OS",
    "Source",
    "Medium",
    "Campaign",
    "Channel",
    "URL",
]


class ClarityClient:
    def __init__(self, api_token: str, timeout_seconds: int = 15):
        if not api_token or not isinstance(api_token, str):
            # Fail at construction time, not on first use -- so a
            # misconfigured server fails loudly at startup, not silently
            # on the first tool call your manager makes.
            raise ClarityAuthError(
                "No Clarity API token provided. Generate one in your "
                "Clarity project under Settings -> Data Export -> "
                "Generate new API token."
            )
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    # ---------- validation helpers (spend zero API calls) ----------

    def _validate_num_days(self, num_of_days: int) -> None:
        if num_of_days not in (1, 2, 3):
            raise ClarityValidationError(
                f"numOfDays must be 1, 2, or 3 (got {num_of_days}). "
                "Clarity only supports the last 24h, 48h, or 72h."
            )

    def _validate_dimension(self, dimension: Optional[str]) -> None:
        if dimension is not None and dimension not in VALID_DIMENSIONS:
            raise ClarityValidationError(
                f"'{dimension}' is not a recognized dimension. "
                f"Valid options: {', '.join(VALID_DIMENSIONS)}"
            )

    # ---------- the actual HTTP call ----------

    def _call_api(self, params: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(
                CLARITY_API_URL,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            raise ClarityAPIError("Request to Clarity timed out.")
        except requests.exceptions.ConnectionError as e:
            raise ClarityAPIError(f"Could not reach Clarity API: {e}")

        if response.status_code in (401, 403):
            raise ClarityAuthError(
                "Clarity rejected the API token (401/403). It may be "
                "invalid, revoked, or expired. Generate a new one from "
                "Settings -> Data Export in your Clarity project."
            )
        if response.status_code == 429:
            raise ClarityRateLimitError(
                "Clarity's daily limit of 10 API requests per project has "
                "been reached. It resets 24 hours after your first call "
                "of the day. This is exactly why we cache responses --"
                " check the cache before trying again."
            )
        if not response.ok:
            raise ClarityAPIError(
                f"Clarity API returned an unexpected error.",
                status_code=response.status_code,
                body=response.text[:500],
            )

        try:
            return response.json()
        except ValueError:
            raise ClarityAPIError(
                "Clarity returned a 200 OK but the body wasn't valid JSON.",
                status_code=response.status_code,
                body=response.text[:500],
            )

    # ---------- public methods used by the MCP tools ----------

    def get_traffic_overview(self, num_of_days: int) -> dict:
        """Overall metrics (Traffic, EngagementTime, ScrollDepth, etc.)
        with NO dimension breakdown -- the big-picture numbers."""
        self._validate_num_days(num_of_days)
        return self._call_api({"numOfDays": num_of_days})

    def get_insights_by_dimension(self, num_of_days: int, dimension: str) -> dict:
        """Same metrics, broken down by ONE dimension, e.g. by Device
        (Desktop vs Mobile vs Tablet)."""
        self._validate_num_days(num_of_days)
        self._validate_dimension(dimension)
        return self._call_api({"numOfDays": num_of_days, "dimension1": dimension})

    def get_cross_dimension_insights(
        self,
        num_of_days: int,
        dimension1: str,
        dimension2: Optional[str] = None,
        dimension3: Optional[str] = None,
    ) -> dict:
        """Break down metrics by up to THREE dimensions at once, e.g.
        Device x Browser x Country -- lets you answer questions like
        'how do mobile Chrome users in India engage differently?'"""
        self._validate_num_days(num_of_days)
        self._validate_dimension(dimension1)
        self._validate_dimension(dimension2)
        self._validate_dimension(dimension3)

        params = {"numOfDays": num_of_days, "dimension1": dimension1}
        if dimension2:
            params["dimension2"] = dimension2
        if dimension3:
            params["dimension3"] = dimension3
        return self._call_api(params)

    def list_valid_dimensions(self) -> list:
        """No API call at all -- just returns our known-good dimension
        list so the LLM (or your manager) can see valid options without
        spending any of the 10 daily requests."""
        return VALID_DIMENSIONS
