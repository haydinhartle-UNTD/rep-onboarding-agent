import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def send_imessage(text: str) -> None:
    api_key = os.environ.get("BLOOIO_API_KEY", "")
    phone = os.environ.get("NOTIFY_PHONE_NUMBER", "")

    if not api_key or not phone:
        logger.error("send_imessage: BLOOIO_API_KEY or NOTIFY_PHONE_NUMBER not set — skipping")
        return

    url = f"https://backend.blooio.com/v2/api/chats/{phone}/messages"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"text": text}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("iMessage sent: %s", text[:80])
    except Exception as exc:
        logger.error("send_imessage failed (non-fatal): %s", exc)
