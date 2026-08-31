"""The one tenancy refusal every read port shares.

A lending book is the most enumerable thing a bank owns: obligor ids are short, sequential in
many systems, and a 404 that means "not yours" is indistinguishable from a 404 that means "does
not exist" only until somebody counts the response times. So every read port here answers 403 for
a record that exists under ANOTHER tenant and 404 only for one that exists nowhere, and the
offline adapters obey the same rule as the managed ones, so the offline gate proves the
authorisation rather than assuming it.
"""

from __future__ import annotations


class CrossTenantError(PermissionError):
    """Asked for a record owned by another tenant: 403, never 404."""

    http_status = 403
