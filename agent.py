"""
Typeform filler — direct Playwright scripting, no AI/Computer Use.

Navigates the installer Typeform, reads each question label, matches it to
rep data, fills it in, and advances. Completes in under 30 seconds.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# Map label keywords (lowercase) to rep_data keys.
# Add entries here if the form ever adds new fields.
_LABEL_MAP = [
    (["first name", "first"],           "first_name"),
    (["last name", "last"],             "last_name"),
    (["work email", "company email",
      "business email", "email"],       "new_gmail"),
    (["phone", "mobile", "cell"],       "phone"),
    (["company id", "installer id",
      "installer", "company"],          "company_id"),
]


def _match_label(label_text: str, rep_data: dict) -> str | None:
    """Return the rep data value whose keywords best match the label."""
    lowered = label_text.lower()
    for keywords, key in _LABEL_MAP:
        if any(kw in lowered for kw in keywords):
            return rep_data.get(key, "")
    return None


async def fill_installer_typeform(typeform_url: str, rep_data: dict) -> dict:
    """
    Fill the installer Typeform for a new rep using direct Playwright scripting.

    Returns:
        {"status": "submitted", "notes": "..."}  on success
        {"status": "failed",    "reason": "..."} on failure
    """
    from playwright.async_api import async_playwright

    first = rep_data.get("first_name", "")
    last = rep_data.get("last_name", "")
    logger.info("Starting Playwright form fill for %s %s", first, last)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            await page.goto(typeform_url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(2)

            # Click "Start" button if present (some Typeforms have a welcome screen)
            for start_text in ["Start", "Let's go", "Begin", "Continue"]:
                try:
                    btn = page.get_by_role("button", name=start_text)
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(1.5)
                        break
                except Exception:
                    pass

            fields_filled = []

            for question_num in range(25):
                await asyncio.sleep(1)

                # Check for thank-you / confirmation screen
                page_text = await page.inner_text("body")
                if any(kw in page_text.lower() for kw in
                       ["thank you", "thanks!", "you're done", "all done",
                        "submitted", "response recorded"]):
                    notes = "Fields filled: " + ", ".join(fields_filled)
                    logger.info("Form submitted successfully. %s", notes)
                    return {"status": "submitted", "notes": notes}

                # Find the visible question label
                label_text = ""
                for selector in [
                    "[data-qa='question-title']",
                    ".question-title",
                    "[class*='questionTitle']",
                    "[class*='question-title']",
                    "h1",
                    "label",
                ]:
                    try:
                        el = page.locator(selector).first
                        if await el.is_visible():
                            label_text = (await el.inner_text()).strip()
                            if label_text:
                                break
                    except Exception:
                        pass

                logger.info("Question %d label: '%s'", question_num + 1, label_text)

                # Match label to rep data
                value = _match_label(label_text, rep_data)
                if value is None:
                    return {
                        "status": "failed",
                        "reason": f"missing field: {label_text or 'unknown (no label found)'}",
                    }

                # Find and fill the visible input
                filled = False
                for input_selector in [
                    "input[type='text']:visible",
                    "input[type='email']:visible",
                    "input[type='tel']:visible",
                    "input[type='number']:visible",
                    "textarea:visible",
                    "input:not([type='hidden']):visible",
                ]:
                    try:
                        inp = page.locator(input_selector).first
                        if await inp.is_visible():
                            await inp.click()
                            await asyncio.sleep(0.3)
                            # Clear any existing value, then type character-by-character
                            # (fill() can skip Typeform's React validation events)
                            await page.keyboard.press("Control+a")
                            await page.keyboard.press("Delete")
                            await inp.press_sequentially(value, delay=50)
                            await asyncio.sleep(0.5)
                            filled = True
                            fields_filled.append(f"{label_text}={value[:15]}")
                            logger.info("Filled '%s' with '%s'", label_text, value[:30])
                            break
                    except Exception as e:
                        logger.warning("Input selector %s failed: %s", input_selector, e)

                if not filled:
                    # Look for a submit button — might be the final step
                    for submit_text in ["Submit", "Send", "Done", "Finish"]:
                        try:
                            btn = page.get_by_role("button", name=submit_text)
                            if await btn.is_visible():
                                await btn.click()
                                await asyncio.sleep(2)
                                filled = True
                                break
                        except Exception:
                            pass

                if not filled:
                    return {
                        "status": "failed",
                        "reason": f"could not find input for question: {label_text}",
                    }

                # Capture current question text BEFORE advancing, to detect change
                before_url = page.url
                before_label = label_text

                # Press Enter — Typeform's primary advance mechanism
                await page.keyboard.press("Enter")
                await asyncio.sleep(2)

                # Verify the question actually changed; if not, try clicking buttons
                new_label = ""
                for selector in [
                    "[data-qa='question-title']", ".question-title",
                    "[class*='questionTitle']", "h1",
                ]:
                    try:
                        el = page.locator(selector).first
                        if await el.is_visible():
                            new_label = (await el.inner_text()).strip()
                            if new_label:
                                break
                    except Exception:
                        pass

                if new_label == before_label:
                    logger.warning("Enter didn't advance — trying buttons")
                    # Log every visible button so we can debug what Typeform shows
                    try:
                        btns = page.locator("button:visible")
                        count = await btns.count()
                        for i in range(count):
                            btn = btns.nth(i)
                            btn_text = (await btn.inner_text()).strip()
                            logger.info("Visible button #%d: '%s'", i, btn_text)
                    except Exception:
                        pass

                    # Try clicking submit-style buttons specifically
                    clicked = False
                    for text in ["Submit", "Send", "Done", "Finish", "OK", "Next", "Continue"]:
                        try:
                            btn = page.get_by_role("button", name=text)
                            if await btn.is_visible():
                                await btn.click()
                                clicked = True
                                logger.info("Clicked button: %s", text)
                                await asyncio.sleep(2)
                                break
                        except Exception:
                            pass

                    if not clicked:
                        return {
                            "status": "failed",
                            "reason": f"stuck on '{label_text}' — Enter and buttons did not advance",
                        }

            return {
                "status": "failed",
                "reason": "form did not reach thank-you screen after 25 questions",
            }

    except Exception as exc:
        logger.exception("Playwright error during form fill")
        return {"status": "failed", "reason": f"browser error: {exc}"}
