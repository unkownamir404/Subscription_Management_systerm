"""
Core Domain Exceptions for Brightloop Subscription Management System.
"""

class DomainError(Exception):
    """
    User-safe exception raised when a business domain rule or state transition invariant is violated.
    Views catch this exception and display a user-friendly flash message.
    """
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message
