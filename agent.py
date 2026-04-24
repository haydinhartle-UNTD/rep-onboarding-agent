"""
Claude Computer Use agent — fills the installer Typeform for a new rep.

STUB phase: fill_installer_typeform() returns immediately with status=submitted.
Real Computer Use loop activated after stub end-to-end test passes.
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
- Any "work email", "company email", or "business email" field → use `new_gmail`
- Any "Company ID", "Enter Company ID", "Installer ID", or similar → use `company_id`
- "First Name" or similar → use `first_name`
- "Last Name" or similar → use `last_name`
- "Phone", "Phone Number", "Mobile" or similar → use `phone`

Rules you must follow:
1. Open the URL, read every question carefully before filling anything.
2. Use the field mapping reference above to match form labels to the correct data.
3. If a required field has no matching data after consulting the mapping above, \
STOP immediately and respond with:
   ```json
   {"status": "failed", "reason": "missing field: <exact field label from form>"}
   ```
   Do NOT guess or make up values.
4. After submitting, wait for and confirm a thank-you or confirmation screen \
before reporting success.
5. Report every field label you encountered in the form inside the `notes` key, \
even fields you skipped.
6. Always end your response with a fenced JSON block containing your verdict:
   ```json
   {"status": "submitted", "notes": "<summary including all field labels seen>"}
   ```
   or
   ```json
   {"status": "failed", "reason": "<specific reason>"}
   ```
"""


def _safe_rep_log(rep_data: dict) -> dict:
    """Return a copy of rep_data with sensitive fields redacted for logging."""
    return {
        k: ("***REDACTED***" if k in _SENSITIVE else v)
        for k, v in rep_data.items()
    }


def _parse_verdict(text: str) -> dict:
    """Extract the fenced ```json block from Claude's final message."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Fallback: if no fenced block, treat whole response as failure note
    return {"status": "failed", "reason": f"agent did not return structured verdict: {text[:200]}"}


async def fill_installer_typeform(typeform_url: str, rep_data: dict) -> dict:
    """
    Fill the installer Typeform for a new rep.

    Returns:
        {"status": "submitted", "notes": "..."}  on success
        {"status": "failed",    "reason": "..."} on failure
    """
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
