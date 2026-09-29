"""Async helpers for awaiting Windows Runtime (winsdk) operations.

Why this exists
---------------
winsdk's async operations are WinRT/COM futures wrapped as asyncio futures.
They are **not cancellable**: the COM operation keeps running after
``Future.cancel()``, and when it completes, winsdk's completion callback calls
``Future.set_result()`` on the already-cancelled future. That raises::

    asyncio.exceptions.InvalidStateError: invalid state

which surfaces as a noisy unhandled-callback traceback on the event loop and
can stall the loop.

``asyncio.wait_for()`` cancels its awaitable on timeout, so wrapping a winsdk
future in ``wait_for`` is what triggers this. Use :func:`winrt_wait` instead:
it races the operation against a timeout using ``asyncio.shield``, so on
timeout the WinRT op is left to finish harmlessly rather than being cancelled.
"""

import asyncio
from typing import Any, Optional


async def winrt_wait(awaitable, timeout: float) -> Optional[Any]:
    """Await a WinRT async op with a timeout, without cancelling it.

    Returns the result, or ``None`` if the timeout elapsed or the operation
    raised. Never propagates ``InvalidStateError`` from a late completion.

    Use this in place of ``asyncio.wait_for(winrt_op, timeout)``.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError:
        # The WinRT op is still running. Let it finish; retrieve/ignore its
        # eventual result so Python doesn't warn about an unretrieved exception.
        def _swallow(t: "asyncio.Future") -> None:
            if not t.cancelled():
                t.exception()

        task.add_done_callback(_swallow)
        return None
    except asyncio.InvalidStateError:
        # Late completion raced us — treat as a failed read, not a crash.
        return None
    except Exception:
        return None
