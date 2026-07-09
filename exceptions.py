"""
Custom exceptions for the Clarity API client.

Why custom exceptions instead of just letting `requests` errors bubble up?
Because an MCP tool needs to tell the calling LLM (and through it, the human)
*what kind* of failure happened, in plain language. "ConnectionError" means
nothing to Claude on the other end deciding what to tell the manager.
"ClarityAuthError: your token is invalid or expired" does.
"""


class ClarityError(Exception):
    """Base class for all Clarity client errors. Catch this if you just
    want to handle 'anything went wrong with Clarity' in one place."""
    pass


class ClarityAuthError(ClarityError):
    """Raised when the Clarity API token is missing, invalid, or expired.
    Maps to HTTP 401/403 from the Clarity API."""
    pass


class ClarityValidationError(ClarityError):
    """Raised BEFORE we even call the API, when the caller passes bad
    input -- e.g. numOfDays=5 (only 1/2/3 allowed) or an unknown dimension
    name. Failing fast here saves one of our precious 10 daily API calls."""
    pass


class ClarityRateLimitError(ClarityError):
    """Raised when Clarity's own rate limit (10 requests/project/day) is
    hit. Maps to HTTP 429."""
    pass


class ClarityAPIError(ClarityError):
    """Catch-all for any other non-2xx response from Clarity (500s, 404s,
    unexpected payloads, etc). Carries the raw status code and body so you
    can inspect what actually came back."""

    def __init__(self, message: str, status_code: int = None, body: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
