import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def send_imessage(text: str) -> None:
    api_key = os.environ.get("BLOOIO_API_KEY", "")
    to_phone = os.environ.get("NOTIFY_PHONE_NUMBER", "")
    from_phone = os.environ.get("BLOOIO_SENDING_NUMBER", "")

    if not api_key or not to_phone:
        logger.error("send_imessage: BLOOIO_API_KEY or NOTIFY_PHONE_NUMBER not set — skipping")
        return

    url = f"https://backend.blooio.com/v2/api/chats/{to_phone}/messages"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"text": text, "from_number": from_phone} if from_phone else {"text": text}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            logger.info("Blooio response: %s %s", resp.status_code, resp.text[:200])
            resp.raise_for_status()
            logger.info("iMessage sent: %s", text[:80])
    except Exception as exc:
        logger.error("send_imessage failed (non-fatal): %s", exc)
