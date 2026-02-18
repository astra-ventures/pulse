"""
OpenClaw Webhook — the bridge between Pulse and the agent.

Supports two session modes:
- "main": Injects message into the main session (original behavior)
- "isolated": Spawns a separate hook session that doesn't compete with 
  the main conversation. Results can be announced back to the channel.

The isolated approach lets Pulse-triggered work happen in the background
while the main session stays clean for human conversation.
"""

import json
import logging
from typing import Optional

import aiohttp

from pulse.src.core.config import PulseConfig

logger = logging.getLogger("pulse.webhook")


class OpenClawWebhook:
    """Triggers OpenClaw agent turns via webhook."""

    def __init__(self, config: PulseConfig):
        self.url = config.openclaw.webhook_url
        self.token = config.openclaw.webhook_token
        self.session_mode = config.openclaw.session_mode
        self.deliver = config.openclaw.deliver
        self.isolated_model = config.openclaw.isolated_model
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def trigger(self, message: str, name: str = "Pulse") -> bool:
        """
        Trigger an agent turn via OpenClaw webhook.
        
        In isolated mode, the hook session runs separately from the main
        conversation. The agent gets full tool access and can announce
        results back to the channel when done.
        
        Args:
            message: The prompt/context for the agent turn
            name: Human-readable name for the hook
            
        Returns:
            True if webhook accepted (202), False otherwise
        """
        session = await self._get_session()

        headers = {
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        payload = {
            "message": message,
            "name": name,
            "wakeMode": "now",
            "deliver": self.deliver,
        }

        # In isolated mode, tell OpenClaw to spawn a separate session
        if self.session_mode == "isolated":
            payload["isolated"] = True
            if self.isolated_model:
                payload["model"] = self.isolated_model

        try:
            async with session.post(
                self.url, 
                json=payload, 
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 202:
                    run_id = None
                    try:
                        body = await resp.json()
                        run_id = body.get("runId")
                    except Exception:
                        pass
                    mode_str = f"isolated" if self.session_mode == "isolated" else "main"
                    logger.info(
                        f"Webhook accepted (202) — mode={mode_str}"
                        + (f", runId={run_id}" if run_id else "")
                    )
                    return True
                else:
                    body = await resp.text()
                    logger.warning(
                        f"Webhook returned {resp.status}: {body[:200]}"
                    )
                    return False

        except aiohttp.ClientError as e:
            logger.error(f"Webhook connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Webhook unexpected error: {e}")
            return False

    async def wake(self, text: str) -> bool:
        """
        Send a wake event (lighter than full agent turn).
        Uses /hooks/wake instead of /hooks/agent.
        """
        from urllib.parse import urlparse
        session = await self._get_session()
        parsed = urlparse(self.url)
        wake_url = f"{parsed.scheme}://{parsed.netloc}/hooks/wake"

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        payload = {"text": text, "mode": "now"}

        try:
            async with session.post(
                wake_url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Wake error: {e}")
            return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
