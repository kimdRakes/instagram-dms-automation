import json
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

class InstagramAPIError(RuntimeError):
    """Raised when Instagram API returns an error or unexpected response."""

class InstagramClient:
    """
    Minimal Instagram web client using a sessionid cookie.

    This client relies on Instagram's web endpoints and may break if Instagram
    changes their APIs. Use responsibly and in line with Instagram's terms.
    """

    BASE_WEB_URL = "https://www.instagram.com"
    BASE_API_URL = "https://www.instagram.com/api/v1"

    def __init__(
        self,
        session_id: str,
        proxies: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty.")

        self.session = requests.Session()
        self.session.cookies.set("sessionid", session_id, domain=".instagram.com")
        self.session.headers.update(
            {
                "User-Agent": user_agent
                or (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": self.BASE_WEB_URL,
                "Referer": f"{self.BASE_WEB_URL}/",
                "X-IG-App-ID": "936619743392459",  # common web app id
            }
        )
        if proxies:
            self.session.proxies.update(proxies)
        self.timeout = timeout

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        logger.debug("Requesting %s %s", method, url)
        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                params=params,
                data=data,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error("Network error while calling Instagram: %s", exc)
            raise InstagramAPIError(f"Network error: {exc}") from exc

        if not response.ok:
            body_preview = response.text[:300]
            logger.error(
                "Instagram responded with HTTP %s: %s", response.status_code, body_preview
            )
            raise InstagramAPIError(
                f"Instagram HTTP {response.status_code}: {body_preview}"
            )
        return response

    def get_user_id(self, username: str) -> str:
        """
        Resolve a username into a numeric Instagram user ID using web profile info.
        """
        username = username.strip().lstrip("@")
        if not username:
            raise ValueError("Username must not be empty.")

        url = f"{self.BASE_API_URL}/users/web_profile_info/"
        params = {"username": username}
        resp = self._request("GET", url, params=params)
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:  # noqa: PERF203
            logger.error("Failed to parse JSON while resolving username %s: %s", username, exc)
            raise InstagramAPIError("Invalid JSON while resolving username.") from exc

        user_data = payload.get("data", {}).get("user")
        if not user_data or "id" not in user_data:
            logger.error("Could not find user ID for username '%s': %s", username, payload)
            raise InstagramAPIError(f"Could not resolve user ID for username '{username}'.")

        user_id = str(user_data["id"])
        logger.debug("Resolved username '%s' to user_id '%s'.", username, user_id)
        return user_id

    def send_direct_text(self, user_id: str, message: str) -> Dict[str, Any]:
        """
        Send a DM to a user by numeric user ID.

        Returns a dict with data such as thread_id and status.

        Note: This relies on an internal endpoint and might change at any time.
        """
        if not user_id:
            raise ValueError("user_id must not be empty.")
        if not message:
            raise ValueError("message must not be empty.")

        url = f"{self.BASE_API_URL}/direct_v2/threads/broadcast/text/"
        # The 'recipient_users' field typically needs nested array JSON.
        data = {
            "recipient_users": json.dumps([[str(user_id)]]),
            "action": "send_item",
            "text": message,
        }

        resp = self._request("POST", url, data=data)
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:  # noqa: PERF203
            logger.error("Failed to parse JSON after sending DM to %s: %s", user_id, exc)
            raise InstagramAPIError("Invalid JSON while sending DM.") from exc

        status = payload.get("status")
        if status != "ok":
            logger.error("Instagram returned non-ok status while sending DM: %s", payload)
            raise InstagramAPIError(f"Instagram returned status '{status}' while sending DM.")

        thread_id = None
        try:
            thread_id = (
                payload.get("payload", {})
                .get("threads", [{}])[0]
                .get("thread_id")
            )
        except Exception:  # noqa: BLE001
            thread_id = None

        result = {
            "user_id": user_id,
            "thread_id": thread_id,
            "status": "success",
            "raw": payload,
        }
        logger.info("Successfully sent DM to user_id=%s, thread_id=%s", user_id, thread_id)
        return result