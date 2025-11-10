import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.instagram_client import InstagramClient, InstagramAPIError
from utils.delay_manager import DelayManager

logger = logging.getLogger(__name__)

class MessageSender:
    """
    High-level orchestrator for sending DMs to a list of usernames.
    """

    def __init__(
        self,
        client: InstagramClient,
        delay_manager: DelayManager,
        dry_run: bool = False,
    ) -> None:
        self.client = client
        self.delay_manager = delay_manager
        self.dry_run = dry_run

    def _build_message_for_target(
        self,
        target: Dict[str, Any],
        template: str,
    ) -> str:
        # If the target explicitly specifies a message, prefer that.
        if "message" in target and target["message"]:
            return str(target["message"])

        username = str(target.get("username", "")).strip().lstrip("@")
        variables = {"username": username}
        # Merge any additional fields to allow {field} in template
        variables.update(target)

        try:
            return template.format(**variables)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to format message template for username '%s': %s. Falling back.",
                username,
                exc,
            )
            return template.replace("{username}", username)

    def send_messages(
        self,
        targets: List[Dict[str, Any]],
        message_template: str,
        output_path: Path,
    ) -> List[Dict[str, Any]]:
        """
        Send messages to a list of targets.

        Each target is a dict that must contain 'username', and may optionally
        include a custom 'message' and other fields.
        """
        results: List[Dict[str, Any]] = []

        for index, target in enumerate(targets, start=1):
            username_raw = target.get("username", "")
            username = str(username_raw).strip().lstrip("@")
            if not username:
                logger.warning("Skipping target with missing username: %s", target)
                continue

            logger.info("Processing target %d/%d: @%s", index, len(targets), username)

            message = self._build_message_for_target(target, message_template)

            if self.dry_run:
                logger.info(
                    "[DRY-RUN] Would send DM to @%s: %s", username, message[:80] + "..."
                    if len(message) > 80
                    else message
                )
                result = {
                    "username": username,
                    "user_id": "dry_run",
                    "thread_id": f"dry_run_thread_{index}",
                    "status": "dry_run",
                    "message": message,
                }
                results.append(result)
                # Still sleep between operations to approximate timing behavior
                self.delay_manager.sleep_between_messages(index, len(targets))
                continue

            # Real sending path
            try:
                user_id = self.client.get_user_id(username)
            except InstagramAPIError as exc:
                logger.error("Failed to resolve user_id for @%s: %s", username, exc)
                results.append(
                    {
                        "username": username,
                        "user_id": None,
                        "thread_id": None,
                        "status": "failed",
                        "error": f"resolve_user_id: {exc}",
                        "message": message,
                    }
                )
                self.delay_manager.sleep_between_messages(index, len(targets))
                continue

            try:
                dm_response = self.client.send_direct_text(user_id, message)
                thread_id = dm_response.get("thread_id")
                status = dm_response.get("status", "unknown")
                results.append(
                    {
                        "username": username,
                        "user_id": user_id,
                        "thread_id": thread_id,
                        "status": status,
                        "message": message,
                    }
                )
            except InstagramAPIError as exc:
                logger.error("Failed to send DM to @%s: %s", username, exc)
                results.append(
                    {
                        "username": username,
                        "user_id": user_id,
                        "thread_id": None,
                        "status": "failed",
                        "error": f"send_dm: {exc}",
                        "message": message,
                    }
                )

            self.delay_manager.sleep_between_messages(index, len(targets))

        try:
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            logger.info("Wrote results for %d targets to %s", len(results), output_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write results to %s: %s", output_path, exc)
            raise

        return results