"""
auth.py — Simple API key authentication for NetOracle.
=========================================================
Write endpoints are protected when API_KEY is configured in the environment.
Read/status endpoints remain open for demo access.

Usage in main.py:
    from app.auth import require_write_auth
    @app.post("/api/sensitive/endpoint", dependencies=[Depends(require_write_auth)])

Set API_KEY= in .env to enable protection.
Leave blank (default) to disable (open demo mode).
"""
import os

from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_write_auth(key: str | None = Security(_API_KEY_HEADER)) -> None:
    """
    Dependency for write/mutating endpoints.
    If API_KEY is configured in the environment, the header must match.
    If API_KEY is not set, all requests pass (open demo mode).
    """
    configured = os.getenv("API_KEY", "").strip()
    if not configured:
        return  # open demo mode — no key required
    if key != configured:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key header. Set API_KEY in your .env to configure.",
        )
