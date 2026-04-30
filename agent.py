"""
Claude Computer Use agent — fills the installer Typeform for a new rep.

Uses claude-sonnet-4-5 with the computer_20250124 tool to drive a headless
Playwright browser. Claude reads each form question, matches it to the rep
data, types the value, and advances until the thank-you screen appears.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# Sensitive field names to scrub from logs
_SENSITIVE = {"ssn", "ssn_last4", "dob", "date_of_birth", "social", "social_security"}

_SYSTEM_PROMPT = """\
You are an onboarding agent for a solar sales company. Your job is to fill out \
a Typeform on behalf of a new sales rep using the data provided.

Field mapping reference (use this to match form labels to data keys):
- "First Name" or similar → use `first_name`
- "Last Name" or similar → use `last_name`
- "Work Email", "Company Email", "Business Email", or just "Email" → use `new_gmail`
- "Phone", "Phone Number", "Mobile", or "Cell" → use `phone`
- "Company ID", "Enter Company ID", "Installer ID", "Installer Company ID", or \
similar → use `company_id`

How to operate the form:
1. Take a screenshot first to see the current state of the page.
2. If a "Start" or welcome button is shown, click it to begin.
3. For each question:
   - Read the question label carefully
   - Match it to the correct field in the rep data using the mapping above
   - Click the input field to focus it
   - Type the value
   - Press Enter (or click "OK"/"Next") to advance
   - Take a screenshot to verify you advanced
4. After the last field, look for a "Submit" button — click it.
5. Wait for and confirm a thank-you / confirmation screen before reporting success.

If a required field has no matching data after consulting the mapping above, \
STOP immediately and respond with:
   ```json
   {"status": "failed", "reason": "missing field: <exact field label>"}
   ```
   Do NOT guess or make up values.

Always end your response with a fenced JSON block containing your verdict:
   ```json
   {"status": "submitted", "notes": "<list every field label you saw>"}
   ```
   or
   ```json
   {"status": "failed", "reason": "<specific reason>"}
   ```
"""


def _safe_rep_log(rep_data: dict) -> dict:
    return {
        k: ("***REDACTED***" if k in _SENSITIVE else v)
        for k, v in rep_data.items()
    }


def _parse_verdict(text: str) -> dict:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {"status": "failed", "reason": f"agent did not return structured verdict: {text[:200]}"}


async def fill_installer_typeform(typeform_url: str, rep_data: dict) -> dict:
    logger.info("fill_installer_typeform called for %s %s",
                rep_data.get("first_name"), rep_data.get("last_name"))

    import anthropic
    from browser import browser_session, execute_tool, navigate

    max_iterations = int(os.environ.get("MAX_AGENT_ITERATIONS", "40"))
    client = anthropic.AsyncAnthropic()

    rep_summary = json.dumps(_safe_rep_log(rep_data), indent=2)
    user_message = (
        f"Please fill out this Typeform for a new rep:\n\n"
        f"URL: {typeform_url}\n\n"
        f"Rep data:\n{rep_summary}"
    )

    messages = [{"role": "user", "content": user_message}]

    computer_tool = {
        "type": "computer_20250124",
        "name": "computer",
        "display_width_px": 1280,
        "display_height_px": 800,
        "display_number": 1,
    }

    async with browser_session():
        await navigate(typeform_url)
        for iteration in range(max_iterations):
            response = await client.beta.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                tools=[computer_tool],
                messages=messages,
                betas=["computer-use-2025-01-24"],
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason == "end_turn" and not tool_uses:
                final_text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                logger.info("Agent finished. Final text: %s", final_text[:500])
                return _parse_verdict(final_text)

            tool_results = []
            for tu in tool_uses:
                screenshot_b64 = await execute_tool(tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": [{
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    }],
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            logger.info("Computer Use iteration %d/%d complete", iteration + 1, max_iterations)

    return {
        "status": "failed",
        "reason": f"agent hit max iterations ({max_iterations}) without finishing",
    }
