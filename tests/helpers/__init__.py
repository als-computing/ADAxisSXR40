"""Shared helpers for the ADAxisSXR40 functional test suite.

Nothing in here starts or stops services, and `ca.CA.put()` refuses any PV that is
not in `policy.SAFE_WRITES`. See tests/README.md.
"""
