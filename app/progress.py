"""
progress.py – lightweight async event bus for SSE streaming.

Usage (inside any async agent code):
    from app.progress import emit
    await emit({"type": "agent_step", "phase": "perception", "text": "..."})

The emitter must first be registered by the HTTP handler via:
    from app.progress import set_emitter
    token = set_emitter(my_async_fn)   # returns a contextvars Token
    ...
    progress_ctx.reset(token)          # cleanup (optional)
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)

# ContextVar holds an optional async callable: async (event: dict) -> None
_emitter: ContextVar[Optional[Callable[[Dict[str, Any]], Coroutine]]] = ContextVar(
    "_progress_emitter", default=None
)


def set_emitter(fn: Callable[[Dict[str, Any]], Coroutine]):
    """Register *fn* as the progress emitter for the current async context.

    Returns the ContextVar token (call ``_emitter.reset(token)`` to clean up).
    """
    return _emitter.set(fn)


async def emit(event: Dict[str, Any]) -> None:
    """Emit one progress event to the caller's SSE stream (no-op if unset)."""
    fn = _emitter.get()
    if fn is None:
        return
    try:
        await fn(event)
    except Exception as exc:
        logger.debug(f"[progress] emit error (ignored): {exc}")
