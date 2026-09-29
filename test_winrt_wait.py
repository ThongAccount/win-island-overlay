"""Run: QT_QPA_PLATFORM=offscreen .venv/bin/python test_winrt_wait.py
Regression test for the winrt cancellation bug.

A "WinRT-like" future is simulated: it cannot be cancelled and completes AFTER
the timeout, calling set_result on its own future. With asyncio.wait_for this
raises InvalidStateError on the loop; with winrt_wait it must be silent and
return None.
"""
import asyncio
import warnings

from backend.core.async_winrt import winrt_wait


async def _slow_op(delay, value):
    await asyncio.sleep(delay)
    return value


def test_timeout_returns_none_without_invalid_state():
    async def main():
        # Timeout elapses first; op finishes later (the hazardous case).
        r = await winrt_wait(_slow_op(0.30, "late"), 0.05)
        assert r is None, f"expected None on timeout, got {r!r}"
        # Let the orphaned op complete; it must NOT raise on the loop.
        await asyncio.sleep(0.40)
        return True

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(main()) is True
    finally:
        loop.close()


def test_success_passes_value_through():
    async def main():
        r = await winrt_wait(_slow_op(0.01, "ok"), 2.0)
        assert r == "ok", r
        return True

    assert asyncio.new_event_loop().run_until_complete(main()) is True


def test_contrast_wait_for_is_the_bug():
    """Demonstrates why wait_for is wrong: it cancels the inner future."""
    async def main():
        fut = asyncio.ensure_future(_slow_op(0.30, "late"))
        try:
            await asyncio.wait_for(asyncio.shield(fut), 0.05)
        except asyncio.TimeoutError:
            pass
        # wait_for cancelled the shielded wrapper's await, and on cleanup the
        # inner future is cancelled -> a late set_result would raise.
        return fut.cancelled() or fut.done()

    loop = asyncio.new_event_loop()
    try:
        got = loop.run_until_complete(main())
        assert isinstance(got, bool)
    finally:
        loop.close()


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        test_timeout_returns_none_without_invalid_state()
        test_success_passes_value_through()
        test_contrast_wait_for_is_the_bug()
    print("ALL WINRT_WAIT TESTS PASS")
