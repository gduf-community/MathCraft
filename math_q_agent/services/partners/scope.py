"""Partner-scope helpers.

Upstream reserves a synthetic user id prefix for IM-connected partners. The
extracted service has one tenant and no partner channels, so no id is ever a
partner id.
"""

from __future__ import annotations

PARTNER_USER_PREFIX = "partner:"


def partner_user_id(partner_id: str) -> str:
    return f"{PARTNER_USER_PREFIX}{partner_id}"


def is_partner_user_id(user_id: str) -> bool:
    """Whether *user_id* names a synthetic partner scope rather than a person."""
    return user_id.startswith(PARTNER_USER_PREFIX)
