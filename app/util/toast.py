from typing import Literal


class ToastException(Exception):
    """Shows a toast on the frontend if raised on an HTMX endpoint"""

    def __init__(
        self, message: str, type: Literal["error", "success", "info"] = "error"
    ):
        self.message = message
        self.type = type
