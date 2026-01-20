"""Tests for the speculation handling module."""

from __future__ import annotations

import pytest

from juriscraper.scraper_driver.driver.dev_driver.speculation import (
    FlowControl,
    SpeculationConfig,
    SpeculationState,
    SpeculationTracker,
    create_speculation_handler,
    create_speculation_handler_with_tracking,
)


class TestSpeculationConfig:
    """Tests for SpeculationConfig dataclass."""

    def test_default_values(self) -> None:
        """Test that SpeculationConfig has sensible defaults."""
        config = SpeculationConfig()
        assert config.threshold == 0
        assert config.speculation == 5

    def test_custom_values(self) -> None:
        """Test creating SpeculationConfig with custom values."""
        config = SpeculationConfig(threshold=100, speculation=10)
        assert config.threshold == 100
        assert config.speculation == 10


class TestSpeculationState:
    """Tests for SpeculationState dataclass."""

    def test_default_values(self) -> None:
        """Test that SpeculationState starts at zero."""
        state = SpeculationState()
        assert state.attempts_above_threshold == 0
        assert state.last_success_id == 0


class TestSpeculationTracker:
    """Tests for SpeculationTracker behavior."""

    def test_should_continue_below_threshold(self) -> None:
        """Test that IDs below threshold always continue (even without response)."""
        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # IDs 1-100 should all return CONTINUE (can decide without response)
        for id_val in [1, 50, 99, 100]:
            result = tracker.should_continue("parse_page", id_val, None)
            assert result == FlowControl.CONTINUE, (
                f"ID {id_val} should continue (at or below threshold 100)"
            )

    def test_should_continue_above_threshold_needs_response(self) -> None:
        """Test that IDs above threshold return AWAIT_MORE_INFO when no response."""
        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Above threshold without response should return AWAIT_MORE_INFO
        result = tracker.should_continue("parse_page", 101, None)
        assert result == FlowControl.AWAIT_MORE_INFO

    def test_should_continue_above_threshold_within_speculation(self) -> None:
        """Test that IDs above threshold continue for speculation attempts."""
        from unittest.mock import MagicMock

        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404

        # First 3 attempts above threshold should return CONTINUE
        assert (
            tracker.should_continue("parse_page", 101, mock_response)
            == FlowControl.CONTINUE
        )
        assert tracker.states["parse_page"].attempts_above_threshold == 1

        assert (
            tracker.should_continue("parse_page", 102, mock_response)
            == FlowControl.CONTINUE
        )
        assert tracker.states["parse_page"].attempts_above_threshold == 2

        assert (
            tracker.should_continue("parse_page", 103, mock_response)
            == FlowControl.CONTINUE
        )
        assert tracker.states["parse_page"].attempts_above_threshold == 3

    def test_should_continue_above_threshold_exhausted(self) -> None:
        """Test that speculation stops after attempts exhausted."""
        from unittest.mock import MagicMock

        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404

        # Use up all 3 speculation attempts
        tracker.should_continue("parse_page", 101, mock_response)
        tracker.should_continue("parse_page", 102, mock_response)
        tracker.should_continue("parse_page", 103, mock_response)

        # 4th attempt should return STOP
        assert (
            tracker.should_continue("parse_page", 104, mock_response)
            == FlowControl.STOP
        )

    def test_should_continue_unknown_continuation(self) -> None:
        """Test that unknown continuation names return STOP."""
        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Unknown continuation should return STOP
        assert (
            tracker.should_continue("unknown_step", 50, None)
            == FlowControl.STOP
        )

    def test_record_success_resets_attempts(self) -> None:
        """Test that recording a success resets the attempt counter."""
        from unittest.mock import MagicMock

        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404

        # Use 2 speculation attempts
        tracker.should_continue("parse_page", 101, mock_response)
        tracker.should_continue("parse_page", 102, mock_response)
        assert tracker.states["parse_page"].attempts_above_threshold == 2

        # Record a success
        tracker.record_success("parse_page", 103)

        # Attempts should be reset
        assert tracker.states["parse_page"].attempts_above_threshold == 0
        assert tracker.states["parse_page"].last_success_id == 103

    def test_record_success_updates_max_id(self) -> None:
        """Test that last_success_id tracks the maximum."""
        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        tracker.record_success("parse_page", 50)
        assert tracker.states["parse_page"].last_success_id == 50

        tracker.record_success("parse_page", 100)
        assert tracker.states["parse_page"].last_success_id == 100

        # Lower ID shouldn't replace higher
        tracker.record_success("parse_page", 75)
        assert tracker.states["parse_page"].last_success_id == 100

    def test_multiple_continuations_independent(self) -> None:
        """Test that different continuations have independent state."""
        from unittest.mock import MagicMock

        tracker = SpeculationTracker()
        tracker.configs["step_a"] = SpeculationConfig(
            threshold=50, speculation=2
        )
        tracker.configs["step_b"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404

        # Use up step_a's speculation
        tracker.should_continue("step_a", 51, mock_response)
        tracker.should_continue("step_a", 52, mock_response)
        assert (
            tracker.should_continue("step_a", 53, mock_response)
            == FlowControl.STOP
        )

        # step_b should still have its full speculation budget
        assert (
            tracker.should_continue("step_b", 101, mock_response)
            == FlowControl.CONTINUE
        )
        assert (
            tracker.should_continue("step_b", 102, mock_response)
            == FlowControl.CONTINUE
        )
        assert (
            tracker.should_continue("step_b", 103, mock_response)
            == FlowControl.CONTINUE
        )
        assert (
            tracker.should_continue("step_b", 104, mock_response)
            == FlowControl.STOP
        )

    def test_2xx_response_always_continues(self) -> None:
        """Test that 2xx responses always return CONTINUE."""
        from unittest.mock import MagicMock

        tracker = SpeculationTracker()
        tracker.configs["parse_page"] = SpeculationConfig(
            threshold=100, speculation=3
        )

        # Mock 200 response
        mock_response = MagicMock()
        mock_response.status_code = 200

        # Above threshold with 200 response should CONTINUE without counting attempts
        result = tracker.should_continue("parse_page", 101, mock_response)
        assert result == FlowControl.CONTINUE
        assert tracker.states["parse_page"].attempts_above_threshold == 0


class TestCreateSpeculationHandler:
    """Tests for the handler factory functions."""

    def test_create_handler_from_config_map(self) -> None:
        """Test creating a handler from a config map."""
        config_map = {
            "start_docket_scraping": {"threshold": 89000, "speculation": 10},
            "parse_listing": {"threshold": 0, "speculation": 5},
        }

        handler = create_speculation_handler(config_map)
        assert handler is not None
        assert callable(handler)

    def test_create_handler_with_tracking(self) -> None:
        """Test creating a handler that exposes its tracker."""
        config_map = {
            "parse_page": {"threshold": 100, "speculation": 3},
        }

        handler, tracker = create_speculation_handler_with_tracking(config_map)

        assert handler is not None
        assert tracker is not None
        assert "parse_page" in tracker.configs
        assert tracker.configs["parse_page"].threshold == 100
        assert tracker.configs["parse_page"].speculation == 3

    @pytest.mark.asyncio
    async def test_handler_returns_correct_values(self) -> None:
        """Test that the async handler returns correct FlowControl values."""
        config_map = {
            "parse_page": {"threshold": 100, "speculation": 2},
        }

        handler, tracker = create_speculation_handler_with_tracking(config_map)

        from unittest.mock import MagicMock

        # Mock 404 response for non-2xx tests
        mock_404 = MagicMock()
        mock_404.status_code = 404

        # Below threshold with no response: CONTINUE (early decision)
        result = await handler(None, "parse_page", 50)
        assert result == FlowControl.CONTINUE

        # Above threshold with no response: AWAIT_MORE_INFO
        result = await handler(None, "parse_page", 101)
        assert result == FlowControl.AWAIT_MORE_INFO

        # Above threshold, attempt 1 with response: CONTINUE
        result = await handler(mock_404, "parse_page", 101)
        assert result == FlowControl.CONTINUE

        # Above threshold, attempt 2: CONTINUE
        result = await handler(mock_404, "parse_page", 102)
        assert result == FlowControl.CONTINUE

        # Above threshold, attempt 3 (exhausted): STOP
        result = await handler(mock_404, "parse_page", 103)
        assert result == FlowControl.STOP

    @pytest.mark.asyncio
    async def test_handler_unknown_continuation_returns_stop(self) -> None:
        """Test that unknown continuations return STOP."""
        config_map = {
            "known_step": {"threshold": 100, "speculation": 3},
        }

        handler = create_speculation_handler(config_map)

        result = await handler(None, "unknown_step", 50)
        assert result == FlowControl.STOP

    def test_handler_uses_default_values(self) -> None:
        """Test that missing config values use defaults."""
        config_map: dict[str, dict[str, int]] = {
            "parse_page": {},  # Empty config uses defaults
        }

        _, tracker = create_speculation_handler_with_tracking(config_map)

        config = tracker.configs["parse_page"]
        assert config.threshold == 0
        assert config.speculation == 5
