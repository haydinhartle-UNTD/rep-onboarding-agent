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

    remaining = _state.deadline - asyncio.get_event_loop().time()
    if remaining <= 0:
        raise TimeoutError(f"Browser session exceeded hard timeout")

    action = tool_call.get("action")

    # Map Computer Use modifier names to Playwright names
    _MOD_MAP = {"ctrl": "Control", "control": "Control",
                "shift": "Shift", "alt": "Alt", "meta": "Meta",
                "cmd": "Meta", "command": "Meta"}

    try:
        if action == "screenshot":
            pass  # fall through to screenshot capture below

        elif action == "wait":
            duration = float(tool_call.get("duration", 1))
            await asyncio.sleep(min(duration, 5))  # cap at 5s

        elif action in ("left_click", "click"):
            x, y = tool_call["coordinate"]
            await page.mouse.click(x, y)

        elif action == "right_click":
            x, y = tool_call["coordinate"]
            await page.mouse.click(x, y, button="right")

        elif action == "double_click":
            x, y = tool_call["coordinate"]
            await page.mouse.dblclick(x, y)

        elif action == "triple_click":
            x, y = tool_call["coordinate"]
            await page.mouse.click(x, y, click_count=3)

        elif action == "mouse_move":
            x, y = tool_call["coordinate"]
            await page.mouse.move(x, y)

        elif action == "left_click_drag":
            start_x, start_y = tool_call.get("start_coordinate", [0, 0])
            end_x, end_y = tool_call.get("coordinate", [0, 0])
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            await page.mouse.move(end_x, end_y)
            await page.mouse.up()

        elif action == "type":
            await page.keyboard.type(tool_call["text"])

        elif action == "key":
            key = tool_call["text"]
            if "+" in key:
                parts = key.split("+")
                modifiers = parts[:-1]
                main_key = parts[-1]
                for mod in modifiers:
                    pw_mod = _MOD_MAP.get(mod.lower(), mod.capitalize())
                    await page.keyboard.down(pw_mod)
                await page.keyboard.press(main_key)
                for mod in reversed(modifiers):
                    pw_mod = _MOD_MAP.get(mod.lower(), mod.capitalize())
                    await page.keyboard.up(pw_mod)
            else:
                await page.keyboard.press(key)

        elif action == "scroll":
            x, y = tool_call["coordinate"]
            direction = tool_call.get("scroll_direction", tool_call.get("direction", "down"))
            amount = tool_call.get("scroll_amount", tool_call.get("amount", 3))
            delta_y = 100 * amount if direction == "down" else -100 * amount
            delta_x = 0
            if direction == "right":
                delta_x = 100 * amount
                delta_y = 0
            elif direction == "left":
                delta_x = -100 * amount
                delta_y = 0
            await page.mouse.move(x, y)
            await page.mouse.wheel(delta_x, delta_y)

        elif action == "cursor_position":
            pass  # just take a screenshot

        else:
            logger.warning("[browser] Unknown action: %s", action)

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
