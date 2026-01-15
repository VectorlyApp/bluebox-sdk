"""
tests/unit/test_websockets.py

Unit tests for websockets data models.
"""

import time

import pytest
from pydantic import ValidationError

from web_hacker.data_models.websockets import (
    ParsedWebSocketClientCommand,
    WebSocketClientCommandType,
    WebSocketSnapshotResponse,
    WebSocketStatsResponse,
    WebSocketSubscribedResponse,
    WebSocketUpdateEvent,
    WebSocketUpdateResponse,
    WebSocketErrorResponse,
    WebSocketPongResponse,
    WebSocketSuccessResponse,
)


class TestParseWebsocketCommand:
    """
    Parsing behavior for client -> server websocket commands.
    """

    def test_ping(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("ping")
        assert parsed.is_valid
        assert parsed.command == WebSocketClientCommandType.PING
        assert parsed.args is None

    def test_whitespace_and_case_normalization(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("  PING  ")
        assert parsed.is_valid
        assert parsed.command == WebSocketClientCommandType.PING

    @pytest.mark.parametrize(
        "raw,expected_args",
        [
            ("subscribe", "all"),
            ("subscribe:", "all"),
            ("subscribe:all", "all"),
            (" SUBSCRIBE:ALL ", "all"),
        ],
    )
    def test_subscribe_all_variants(self, raw: str, expected_args: str) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command(raw)
        assert parsed.is_valid
        assert parsed.command == WebSocketClientCommandType.SUBSCRIBE
        assert parsed.args == expected_args
        assert parsed.subscribe_categories == set()

    def test_subscribe_specific_categories(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("subscribe:AsyncNetworkMonitor, AsyncStorageMonitor")
        assert parsed.is_valid
        assert parsed.command == WebSocketClientCommandType.SUBSCRIBE
        # args are normalized to lowercase because the parser lowercases the message
        assert parsed.args == "asyncnetworkmonitor, asyncstoragemonitor"
        assert parsed.subscribe_categories == {"asyncnetworkmonitor", "asyncstoragemonitor"}

    def test_subscribe_missing_categories_after_colon(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("subscribe:   ")
        # stripping makes this equivalent to "subscribe:", so it is treated as "all"
        assert parsed.is_valid
        assert parsed.command == WebSocketClientCommandType.SUBSCRIBE
        assert parsed.args == "all"
        assert parsed.subscribe_categories == set()

    def test_subscribe_invalid_format_without_colon(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("subscribenotvalid")
        assert not parsed.is_valid
        assert parsed.command is None
        assert "must be of the form" in (parsed.error or "").lower()

    def test_navigate_success(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("navigate:https://example.com")
        assert parsed.is_valid
        assert parsed.command == WebSocketClientCommandType.NAVIGATE
        assert parsed.navigate_url == "https://example.com"

    def test_navigate_missing_url(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("navigate:")
        assert not parsed.is_valid
        assert parsed.command is None
        assert "missing url" in (parsed.error or "").lower()

    def test_navigate_missing_colon(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("navigatehttps://example.com")
        assert not parsed.is_valid
        assert parsed.command is None
        assert "must be of the form" in (parsed.error or "").lower()

    def test_unknown_command(self) -> None:
        parsed = ParsedWebSocketClientCommand.parse_raw_websocket_command("not_a_command")
        assert not parsed.is_valid
        assert parsed.command is None
        assert "unknown command" in (parsed.error or "").lower()


class TestResponseModels:
    """
    Validation behavior for server -> client websocket responses.
    """

    def test_pong_response_has_timestamp(self) -> None:
        before = time.time()
        resp = WebSocketPongResponse()
        after = time.time()
        assert before <= resp.timestamp <= after
        assert resp.type == resp.type.PONG  # enum literal check

    def test_subscribed_response_defaults(self) -> None:
        resp = WebSocketSubscribedResponse()
        assert resp.type == resp.type.SUBSCRIBED
        assert resp.categories == "all"

    def test_error_response_round_trip(self) -> None:
        resp = WebSocketErrorResponse(message="oops")
        dumped = resp.model_dump()
        loaded = WebSocketErrorResponse(**dumped)
        assert loaded.message == "oops"
        assert loaded.type == resp.type

    def test_stats_response_requires_stats(self) -> None:
        with pytest.raises(ValidationError):
            WebSocketStatsResponse()  # type: ignore[call-arg]

    def test_success_response_requires_message(self) -> None:
        with pytest.raises(ValidationError):
            WebSocketSuccessResponse()  # type: ignore[call-arg]

    def test_snapshot_response_validation(self) -> None:
        resp = WebSocketSnapshotResponse(
            cdp_captures_id="abc123",
            stats={"total_events": 1},
        )
        assert resp.type == resp.type.SNAPSHOT
        assert resp.cdp_captures_id == "abc123"
        assert resp.stats["total_events"] == 1

    def test_update_response_requires_events(self) -> None:
        with pytest.raises(ValidationError):
            WebSocketUpdateResponse(stats={"total_events": 0})  # type: ignore[call-arg]

    def test_update_event_validation(self) -> None:
        event = WebSocketUpdateEvent(
            category="AsyncNetworkMonitor",
            summary={"foo": "bar"},
            timestamp=123.4,
        )
        assert event.category == "AsyncNetworkMonitor"
        assert event.summary == {"foo": "bar"}

    def test_update_event_missing_summary(self) -> None:
        with pytest.raises(ValidationError):
            WebSocketUpdateEvent(
                category="AsyncNetworkMonitor",
                timestamp=123.4,
            )  # type: ignore[call-arg]

    def test_update_response_round_trip(self) -> None:
        event = WebSocketUpdateEvent(
            category="AsyncNetworkMonitor",
            summary={"foo": "bar"},
            timestamp=123.4,
        )
        resp = WebSocketUpdateResponse(
            stats={"total_events": 1},
            events=[event],
        )
        dumped = resp.model_dump()
        loaded = WebSocketUpdateResponse(**dumped)
        assert loaded.events[0].category == "AsyncNetworkMonitor"
        assert loaded.stats["total_events"] == 1
