import logging
import random
import time
from typing import Tuple

logger = logging.getLogger(__name__)

class DelayManager:
    """
    Handles randomized delays between actions to mimic human behavior.
    """

    def __init__(self, min_delay_seconds: float = 45.0, max_delay_seconds: float = 60.0) -> None:
        if min_delay_seconds <= 0 or max_delay_seconds <= 0:
            raise ValueError("Delay values must be positive.")
        if max_delay_seconds < min_delay_seconds:
            raise ValueError("max_delay_seconds must be >= min_delay_seconds.")
        self.min_delay_seconds = float(min_delay_seconds)
        self.max_delay_seconds = float(max_delay_seconds)

    def _get_next_delay(self) -> float:
        """
        Get a randomized delay between min and max, with slight jitter.
        """
        base = random.uniform(self.min_delay_seconds, self.max_delay_seconds)
        jitter = random.uniform(-1.0, 1.0)
        delay = max(1.0, base + jitter)
        return delay

    def plan_delays_for_batch(self, count: int) -> Tuple[float, ...]:
        """
        Precompute delays for a given number of operations.
        """
        if count <= 0:
            return tuple()
        return tuple(self._get_next_delay() for _ in range(count))

    def sleep_between_messages(self, index: int, total: int) -> None:
        """
        Sleep for a randomized interval between messages and log the delay.
        """
        if index >= total:
            # After the last message, you might want to return immediately.
            return

        delay = self._get_next_delay()
        logger.info(
            "Sleeping for %.2f seconds before next message (%d/%d).",
            delay,
            index,
            total,
        )
        try:
            time.sleep(delay)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Interrupted while sleeping between messages: %s", exc)