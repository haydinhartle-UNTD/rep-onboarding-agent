import hmac
import logging
import os
import time

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel

from agent import fill_installer_typeform
from notifications import send_imessage

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idempotency cache: prevents double-submission if Zapier retries the webhook.
# Key: "{new_gmail}:{first_name}:{last_name}"
# Value: Unix timestamp of first receipt
# ---------------------------------------------------------------------------
_SEEN: dict[str, float] = {}
_DEDUPE_TTL = 600  # 10 minutes


def _is_duplicate(key: str) -> bool:
    now = time.time()
    expired = [k for k, ts in _SEEN.items() if now - ts > _DEDUPE_TTL]
    for k in expired:
        del _SEEN[k]
    if key in _SEEN:
        return True
    _SEEN[key] = now
    return False


# ---------------------------------------------------------------------------
# Pydantic model — fields sent by Zapier (Google Workspace New User trigger)
# company_id is static and injected from env, not required in payload
# ---------------------------------------------------------------------------
class RepPayload(BaseModel):
    first_name: str
    last_name: str
    new_gmail: str
    phone: str


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Rep Onboarding Agent")


@app.get("/")
async def health_check():
    return {"status": "ok"}


@app.post("/webhook/rep-onboarding")
async def rep_onboarding_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    # 1. Verify shared secret
    webhook_secret = os.environ.get("ZAPIER_WEBHOOK_SECRET", "")
    incoming_secret = request.headers.get("X-Webhook-Secret", "")
    if not webhook_secret or not hmac.compare_digest(webhook_secret, incoming_secret):
        logger.warning("Webhook rejected: bad or missing X-Webhook-Secret")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Parse + validate payload
    try:
        body = await request.json()
        payload = RepPayload(**body)
    except Exception as exc:
        logger.error("Payload validation failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    # 3. Idempotency check
    dedup_key = f"{payload.new_gmail}:{payload.first_name}:{payload.last_name}"
    if _is_duplicate(dedup_key):
        logger.info("Duplicate webhook ignored for key: %s", dedup_key)
        return {"status": "duplicate", "message": "Already processing this rep — ignoring retry"}

    logger.info("Webhook accepted for %s %s (%s)", payload.first_name, payload.last_name, payload.new_gmail)

    # 4. Return 200 immediately (Zapier has a short timeout)
    background_tasks.add_task(_run_onboarding, payload)
    return {"status": "accepted", "message": f"Onboarding started for {payload.first_name} {payload.last_name}"}


async def _run_onboarding(payload: RepPayload) -> None:
    """Background task: run the agent and send an iMessage with the result."""
    first = payload.first_name
    last = payload.last_name
    typeform_url = os.environ.get("INSTALLER_TYPEFORM_URL", "")

    if not typeform_url:
        msg = f"💥 Onboarding aborted for {first} {last} — INSTALLER_TYPEFORM_URL env var not set"
        logger.error(msg)
        await send_imessage(msg)
        return

    # Inject static company_id — never comes from the webhook
    rep_data = payload.model_dump()
    rep_data["company_id"] = os.environ.get("COMPANY_ID", "")

    try:
        logger.info("Starting agent for %s %s", first, last)
        result = await fill_installer_typeform(typeform_url, rep_data)
        status = result.get("status")

        if status == "submitted":
            notes = result.get("notes", "")
            msg = f"✅ Onboarding complete: {first} {last} — {notes}"
            logger.info(msg)
        else:
            reason = result.get("reason", "unknown error")
            msg = f"❌ Onboarding failed: {first} {last} — {reason}"
            logger.error(msg)

        await send_imessage(msg)

    except Exception as exc:
        msg = f"💥 Onboarding crashed: {first} {last} — {exc}"
        logger.exception("Unhandled exception in _run_onboarding")
        await send_imessage(msg)
