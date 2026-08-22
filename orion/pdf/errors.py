"""Typed, user-presentable errors (spec §25).

Every error carries a ``message`` written for a person and an optional
``detail`` for the log.  The UI shows ``message``; the traceback goes only to
the log file.  No Python traceback ever reaches the user.
"""

from __future__ import annotations

__all__ = [
    "OrionPdfError",
    "PdfReadError",
    "PdfCorruptError",
    "PdfPasswordRequired",
    "PdfWriteError",
    "UnsupportedOperationError",
    "describe_exception",
]


class OrionPdfError(Exception):
    """Base class for every error Orion is prepared to show to the user."""

    default_message = "The operation could not be completed."

    def __init__(self, message: str | None = None, *, detail: str = "") -> None:
        self.message = message or self.default_message
        self.detail = detail
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class PdfReadError(OrionPdfError):
    default_message = "The PDF file could not be opened."


class PdfCorruptError(PdfReadError):
    default_message = "The file is damaged or is not a valid PDF document."


class PdfPasswordRequired(PdfReadError):
    default_message = "This document is password protected."

    def __init__(
        self, message: str | None = None, *, detail: str = "", wrong: bool = False
    ) -> None:
        if message is None and wrong:
            message = "The password is not correct."
        super().__init__(message, detail=detail)
        self.wrong = wrong


class PdfWriteError(OrionPdfError):
    default_message = "The document could not be saved."


class UnsupportedOperationError(OrionPdfError):
    default_message = "This operation is not supported for this document."


def describe_exception(exc: BaseException) -> str:
    """Turn any exception into a sentence suitable for a message box."""
    if isinstance(exc, OrionPdfError):
        return exc.message
    if isinstance(exc, FileNotFoundError):
        return "The file no longer exists at that location."
    if isinstance(exc, PermissionError):
        return "Permission denied. Check that the file is not read-only or open elsewhere."
    if isinstance(exc, IsADirectoryError):
        return "That path is a folder, not a file."
    if isinstance(exc, MemoryError):
        return "Not enough memory to complete the operation. Try closing other documents."
    if isinstance(exc, OSError):
        reason = getattr(exc, "strerror", None) or str(exc)
        if getattr(exc, "errno", None) == 28:
            return "There is not enough free disk space to write the file."
        return f"A file system error occurred: {reason}"
    return "An unexpected error occurred. See the log file for details."
