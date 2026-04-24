"""
Browser executor for Claude Computer Use tool calls.

STUB phase: execute_tool() returns a 1x1 white PNG and logs the action.
Real Playwright implementation wired in after stub end-to-end test passes.
"""
import asyncio
import base64
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# 1x1 white PNG, base64-encoded — used as placeholder screenshot in stub mode
_STUB_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
)

STUB_MODE = False


@asynccontextmanager
async def browser_session() -> AsyncGenerator[None, None]:
    """Async context manager that owns the browser lifecycle."""
    if STUB_MODE:
        logger.info("[browser] STUB session opened")
        yield
        logger.info("[browser] STUB session closed")
        return

    # --- Real Playwright implementation (activated in Phase 5) ---
    from playwright.async_api import async_playwright  # noqa: PLC0415

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # Store page on a task-local object so execute_tool() can reach it
        _state.page = page
        _state.deadline = asyncio.get_event_loop().time() + 300  # 5-minute hard timeout

        try:
            yield
        finally:
            await browser.close()
            _state.page = None


class _BrowserState:
    page = None
    deadline: float = 0.0


_state = _BrowserState()


async def execute_tool(tool_call: dict) -> str:
    """
    Execute a single Computer Use tool action and return a base64 PNG screenshot.

    tool_call examples:
        {"action": "screenshot"}
        {"action": "left_click", "coordinate": [640, 400]}
        {"action": "type", "text": "hello"}
        {"action": "key", "text": "Return"}
        {"action": "scroll", "coordinate": [640, 400], "direction": "down", "amount": 3}
        {"action": "mouse_move", "coordinate": [640, 400]}
    """
    if STUB_MODE:
        logger.info("[browser] STUB execute_tool: %s", tool_call.get("action"))
        return _STUB_PNG

    page = _state.page
    if page is None:
        raise RuntimeError("execute_tool called outside of browser_session context")

    # Enforce 90-second hard timeout
    remaining = _state.deadline - asyncio.get_event_loop().time()
    if remaining <= 0:
        raise TimeoutError("Browser session exceeded 90-second limit")

    action = tool_call.get("action")

    try:
        if action == "screenshot":
            pass  # fall through to screenshot capture below

        elif action in ("left_click", "click"):
            x, y = tool_call["coordinate"]
            await page.mouse.click(x, y)

        elif action == "right_click":
            x, y = tool_call["coordinate"]
            await page.mouse.click(x, y, button="right")

        elif action == "double_click":
            x, y = tool_call["coordinate"]
            await page.mouse.dblclick(x, y)

        elif action == "mouse_move":
            x, y = tool_call["coordinate"]
            await page.mouse.move(x, y)

        elif action == "type":
            await page.keyboard.type(tool_call["text"])

        elif action == "key":
            # Claude sends key names like "Return", "Tab", "ctrl+a"
            key = tool_call["text"]
            if "+" in key:
                # e.g. "ctrl+a" → hold ctrl, press a
                parts = key.split("+")
                modifiers = parts[:-1]
                main_key = parts[-1]
                for mod in modifiers:
                    await page.keyboard.down(mod.capitalize())
                await page.keyboard.press(main_key)
                for mod in reversed(modifiers):
                    await page.keyboard.up(mod.capitalize())
            else:
                await page.keyboard.press(key)

        elif action == "scroll":
            x, y = tool_call["coordinate"]
            direction = tool_call.get("direction", "down")
            amount = tool_call.get("amount", 3)
            delta_y = 100 * amount if direction == "down" else -100 * amount
            await page.mouse.move(x, y)
            await page.mouse.wheel(0, delta_y)

        else:
            logger.warning("[browser] Unknown action: %s", action)

        # Short settle time so DOM updates are captured in screenshot
        await asyncio.sleep(0.3)

    except Exception as exc:
        logger.error("[browser] Action %s failed: %s", action, exc)
        # Return screenshot anyway so Claude can see the error state
        screenshot_bytes = await page.screenshot(type="png")
        b64 = base64.b64encode(screenshot_bytes).decode()
        return b64

    screenshot_bytes = await page.screenshot(type="png")
    return base64.b64encode(screenshot_bytes).decode()


async def navigate(url: str) -> None:
    """Navigate the browser to a URL (used at session start)."""
    if STUB_MODE:
        logger.info("[browser] STUB navigate: %s", url)
        return
    await _state.page.goto(url, wait_until="networkidle", timeout=30_000)
