"""
Shared validation helpers for the trading engine.

These utilities are meant to be reused across route handlers
to keep validation logic consistent.
"""

MIN_ACCOUNT_NAME_LENGTH = 2
MAX_ACCOUNT_NAME_LENGTH = 128


def validate_transaction_amount(amount: float) -> tuple[bool, str]:
    """Validate that a transaction amount is acceptable.

    Returns a tuple of (is_valid, error_message).
    """
    if not isinstance(amount, (int, float)):
        return False, "Amount must be numeric"

    if amount == 0:
        return False, "Transaction amount cannot be zero"

    if amount < 0:
        return False, "Transaction amount cannot be negative"

    if amount > 1_000_000:
        return False, "Transaction amount exceeds maximum allowed"

    return True, ""


def validate_account_name(name: str) -> tuple[bool, str]:
    """Validate that an account name meets our requirements."""
    name = name.strip()

    if len(name) < MIN_ACCOUNT_NAME_LENGTH:
        return False, "Account name is too short"

    if len(name) > MAX_ACCOUNT_NAME_LENGTH:
        return False, "Account name exceeds maximum length"

    # Only allow alphanumeric chars, spaces, and hyphens
    if not name.replace(" ", "").replace("-", "").isalnum():
        return False, "Account name contains invalid characters"

    return True, ""
