"""Speculation handling utilities for LocalDevDriver.

This module provides factory functions for creating speculation response
handlers that control how speculative scraping behaves when encountering
non-2xx responses.

The main factory function ``create_speculation_handler`` creates a handler that:

- Always returns True for speculative_ids below the threshold
- Returns True for the first N "speculation" attempts above the threshold
- Returns False after the speculation attempts are exhausted

This is useful for:

- Speculative ID scanning (e.g., case IDs from 1 to N)
- Pagination probing
- Any scenario where you want to try a few extra requests beyond known data
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Import FlowControl from data_types and re-export for backward compatibility
from juriscraper.scraper_driver.data_types import FlowControl

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from juriscraper.scraper_driver.data_types import Response

# Re-export for backward compatibility
__all__ = [
    "FlowControl",
    "SpeculationConfig",
    "SpeculationState",
    "SpeculationTracker",
    "create_speculation_handler",
    "create_speculation_handler_with_tracking",
]

logger = logging.getLogger(__name__)


@dataclass
class SpeculationConfig:
    """Configuration for speculation handling per continuation.

    Attributes:
        threshold: Speculative IDs below this value always continue (return True).
        speculation: Number of attempts to try above the threshold before stopping.
    """

    threshold: int = 0
    speculation: int = 5


@dataclass
class SpeculationState:
    """Tracks speculation state for a single continuation.

    Attributes:
        attempts_above_threshold: Count of non-2xx responses seen above threshold.
        last_success_id: Last speculative_id that returned 2xx (for threshold adjustment).
    """

    attempts_above_threshold: int = 0
    last_success_id: int = 0


@dataclass
class SpeculationTracker:
    """Tracks speculation state across all continuations.

    This class maintains per-continuation state to support multiple
    speculative steps within a single scraper run.
    """

    configs: dict[str, SpeculationConfig] = field(default_factory=dict)
    states: dict[str, SpeculationState] = field(
        default_factory=lambda: defaultdict(SpeculationState)
    )

    def should_continue(
        self,
        continuation_name: str,
        speculative_id: int,
        response: Response | None = None,
    ) -> FlowControl:
        """Determine if speculation should continue.

        This method can be called in two scenarios:

        1. Early check (response=None): Called when a SpeculativeRequest is first
           yielded to determine if we can make a decision without the HTTP response.
        2. Full check (response provided): Called after receiving the HTTP response.

        Args:
            continuation_name: Name of the continuation method.
            speculative_id: The speculative ID being processed.
            response: The HTTP response, or None for early check.

        Returns:
            FlowControl indicating how to proceed:
            - CONTINUE: Continue speculation (below threshold or attempts remaining)
            - STOP: Stop speculation (attempts exhausted)
            - AWAIT_MORE_INFO: Need response to decide (above threshold, no response yet)
        """
        config = self.configs.get(continuation_name)
        if config is None:
            # No config for this continuation - use default behavior (stop)
            return FlowControl.STOP

        # Below threshold: always continue (can decide without response)
        if speculative_id <= config.threshold:
            return FlowControl.CONTINUE

        # Above threshold: need response to make decision
        if response is None:
            return FlowControl.AWAIT_MORE_INFO

        # We have a response - check if successful (2xx)
        is_success = 200 <= response.status_code < 300
        state = self.states[continuation_name]

        if is_success:
            # Success resets the counter, continue
            state.attempts_above_threshold = 0
            return FlowControl.CONTINUE

        # Non-2xx above threshold: use speculation attempts
        state.attempts_above_threshold += 1

        if state.attempts_above_threshold <= config.speculation:
            logger.debug(
                f"Speculation [{continuation_name}] id={speculative_id}: "
                f"attempt {state.attempts_above_threshold}/{config.speculation} "
                f"(above threshold {config.threshold})"
            )
            return FlowControl.CONTINUE

        logger.info(
            f"Speculation [{continuation_name}] id={speculative_id}: "
            f"exhausted {config.speculation} attempts above threshold {config.threshold}"
        )
        return FlowControl.STOP

    def record_success(
        self, continuation_name: str, speculative_id: int
    ) -> None:
        """Record a successful (2xx) response for a speculative ID.

        This resets the attempts counter and updates the last success ID.

        Args:
            continuation_name: Name of the continuation method.
            speculative_id: The speculative ID that succeeded.
        """
        state = self.states[continuation_name]
        state.last_success_id = max(state.last_success_id, speculative_id)
        # Reset attempts counter on success
        state.attempts_above_threshold = 0


def create_speculation_handler(
    config_map: dict[str, dict[str, int]],
) -> Callable[[Response | None, str, int], Awaitable[FlowControl]]:
    """Create a speculation response handler from a configuration map.

    The configuration map specifies threshold and speculation values per
    continuation name::

        {
            "start_docket_scraping": {"threshold": 89000, "speculation": 10},
            "parse_listing": {"threshold": 0, "speculation": 5},
        }

    The handler:

    - For speculative_id <= threshold: returns CONTINUE (can decide without response)
    - For speculative_id > threshold with no response: returns AWAIT_MORE_INFO
    - For speculative_id > threshold with response: returns CONTINUE for first N
      non-2xx responses, then STOP

    The handler may be called twice for a single speculative request:

    1. First call with response=None to check if early decision possible
    2. Second call with response if AWAIT_MORE_INFO was returned

    Args:
        config_map: Dict mapping continuation_name to {"threshold": int, "speculation": int}.
            If a continuation is not in the map, the handler returns STOP.

    Returns:
        Async callback suitable for on_speculation_response parameter.

    Example::

        handler = create_speculation_handler({
            "start_docket_scraping": {"threshold": 89000, "speculation": 10},
        })

        driver = LocalDevDriver(
            scraper=scraper,
            db=sql_manager,
            on_speculation_response=handler,
        )
    """
    tracker = SpeculationTracker()

    # Convert config_map to SpeculationConfig objects
    for continuation_name, config_dict in config_map.items():
        tracker.configs[continuation_name] = SpeculationConfig(
            threshold=config_dict.get("threshold", 0),
            speculation=config_dict.get("speculation", 5),
        )

    async def handler(
        response: Response | None, continuation_name: str, speculative_id: int
    ) -> FlowControl:
        """Speculation response handler callback.

        Args:
            response: The HTTP response, or None for early check.
            continuation_name: Name of the continuation method.
            speculative_id: The speculative ID being processed.

        Returns:
            FlowControl indicating how to proceed.
        """
        return tracker.should_continue(
            continuation_name, speculative_id, response
        )

    return handler


def create_speculation_handler_with_tracking(
    config_map: dict[str, dict[str, int]],
) -> tuple[
    Callable[[Response | None, str, int], Awaitable[FlowControl]],
    SpeculationTracker,
]:
    """Create a speculation handler and return the tracker for inspection.

    This is useful for testing or when you need to inspect the speculation
    state during or after a run.

    Args:
        config_map: Dict mapping continuation_name to {"threshold": int, "speculation": int}.

    Returns:
        Tuple of (handler, tracker) where tracker can be inspected for state.
    """
    tracker = SpeculationTracker()

    for continuation_name, config_dict in config_map.items():
        tracker.configs[continuation_name] = SpeculationConfig(
            threshold=config_dict.get("threshold", 0),
            speculation=config_dict.get("speculation", 5),
        )

    async def handler(
        response: Response | None, continuation_name: str, speculative_id: int
    ) -> FlowControl:
        return tracker.should_continue(
            continuation_name, speculative_id, response
        )

    return handler, tracker
