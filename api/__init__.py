from importlib import import_module
from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        module = import_module(".main", __name__)
        return module.app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
