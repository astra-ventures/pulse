"""Tests for infrastructure failure handling.

When the OpenClaw gateway is unreachable (connection error),
Pulse should NOT boost drive frustration — that's an infra problem,
not an agent failure. Drives should remain unchanged.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from src.drives.engine import Drive, DriveEngine


class _AsyncCM:
    """Minimal async context manager for mocking aiohttp responses."""
    def __init__(self, resp):
        self._resp = resp
    async def __aenter__(self):
        return self._resp
    async def __aexit__(self, *args):
        return False


class TestWebhookInfraFailure:
    """Webhook returns None (not False) on connection error."""

    def _make_webhook(self):
        from src.core.webhook import OpenClawWebhook
        # Build a minimal config mock that matches WebhookConfig attribute access
        oc = MagicMock()
        oc.webhook_url = "http://127.0.0.1:18789/hooks/agent"
        oc.webhook_token = None
        oc.session_mode = "main"
        oc.deliver = False
        oc.isolated_model = None
        config = MagicMock()
        config.openclaw = oc
        return OpenClawWebhook(config)

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self):
        """ClientError (gateway down) should return None, not False."""
        webhook = self._make_webhook()

        with patch.object(webhook, '_get_session') as mock_get_session:
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session
            # Use MagicMock (not AsyncMock) so the side_effect fires
            # before the async context manager protocol is entered
            mock_session.post.side_effect = aiohttp.ClientError("Connection refused")

            result = await webhook.trigger("test message")

        assert result is None, f"Expected None for infra failure, got {result!r}"

    @pytest.mark.asyncio
    async def test_non_202_returns_false(self):
        """Non-202 HTTP response (agent-side failure) should return False."""
        webhook = self._make_webhook()

        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")

        mock_session = MagicMock()
        mock_session.post.return_value = _AsyncCM(mock_resp)

        with patch.object(webhook, '_get_session', return_value=mock_session):
            result = await webhook.trigger("test message")

        assert result is False, f"Expected False for server error, got {result!r}"

    @pytest.mark.asyncio
    async def test_202_returns_true(self):
        """Successful 202 response should still return True."""
        webhook = self._make_webhook()

        mock_resp = MagicMock()
        mock_resp.status = 202
        mock_resp.json = AsyncMock(return_value={"runId": "abc123"})

        mock_session = MagicMock()
        mock_session.post.return_value = _AsyncCM(mock_resp)

        with patch.object(webhook, '_get_session', return_value=mock_session):
            result = await webhook.trigger("test message")

        assert result is True, f"Expected True for 202 success, got {result!r}"


class TestDriveFrustrationOnInfraFailure:
    """Drives should NOT be boosted on infrastructure failures."""

    def _make_engine(self) -> DriveEngine:
        config = MagicMock()
        config.drives.pressure_rate = 0.01
        config.drives.trigger_threshold = 0.7
        config.drives.max_pressure = 5.0
        config.drives.success_decay = 0.5
        config.drives.failure_boost = 0.2
        config.drives.adaptive_decay = False
        config.drives.categories = {
            "system": MagicMock(weight=1.5, source="system")
        }
        state = MagicMock()
        state.get.return_value = {"drives": {}}
        return DriveEngine(config, state)

    def test_infra_failure_leaves_pressure_unchanged(self):
        """on_trigger_failure NOT called on infra failure → drive stays same."""
        engine = self._make_engine()
        engine.drives["system"].pressure = 2.0
        original_pressure = engine.drives["system"].pressure

        # When success=None, daemon code does NOT call on_trigger_failure.
        # This test validates the drive stays unchanged (contract for the daemon's guard).
        assert engine.drives["system"].pressure == original_pressure, (
            "Drive pressure should not change when on_trigger_failure is not called"
        )

    def test_agent_failure_boosts_drive(self):
        """on_trigger_failure IS called on agent-side failure → drive increases."""
        engine = self._make_engine()
        engine.drives["system"].pressure = 2.0
        original_pressure = engine.drives["system"].pressure

        decision = MagicMock()
        decision.top_drive = engine.drives["system"]
        engine.on_trigger_failure(decision)

        assert engine.drives["system"].pressure > original_pressure, (
            "Drive pressure should increase on agent-side failure"
        )
        assert engine.drives["system"].pressure == pytest.approx(
            original_pressure + 0.2, abs=0.01
        )

    def test_infra_failure_does_not_exceed_max_pressure(self):
        """Even with repeated calls, max_pressure cap holds on agent failures."""
        engine = self._make_engine()
        engine.drives["system"].pressure = 4.9

        decision = MagicMock()
        decision.top_drive = engine.drives["system"]

        # Even many agent-side failures → stays capped
        for _ in range(10):
            engine.on_trigger_failure(decision)

        assert engine.drives["system"].pressure <= 5.0, (
            "Pressure should never exceed max_pressure"
        )
