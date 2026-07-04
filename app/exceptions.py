"""Shared application exceptions."""


class HarnessError(RuntimeError):
    """Raised when the Connor loop harness cannot continue safely."""
