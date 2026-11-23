"""
Kept as a thin re-export so callers have one import path.

The old IsFrontDesk / IsAnalyst / IsChecker / IsApprover classes are gone:
roles are data now, so nothing asks "which role is this?" — it asks
"may this user do this?". See accounts/authz.py.
"""
from accounts.authz import RequiresPermission, has_perm  # noqa: F401
