"""Partner-channel surface.

The extracted service ships no partner channels; this package exists so
modules that mention partner scopes keep importing.
"""

from __future__ import annotations

from .scope import is_partner_user_id, partner_user_id

__all__ = ["is_partner_user_id", "partner_user_id"]
