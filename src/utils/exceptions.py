"""
src/utils/exceptions.py

Custom exceptions for the project.
"""

class LLMStructuredOutputError(Exception):
    """
    Exception raised when LLM structured output parsing fails.
    """
    pass


class TransactionIdentificationFailedError(Exception):
    """
    Exception raised when the agent fails to identify a network transaction
    that corresponds to the user's requested task after exhausting all attempts.
    """
    pass
