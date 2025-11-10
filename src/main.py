import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.instagram_client import InstagramClient, InstagramAPIError
from services.message_sender import MessageSender
from utils.delay_manager import DelayManager
from utils.proxy_handler import build_proxy_dict

logger = logging.getLogger(__name__)

def setup_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logger.warning("Config file %s not found, using defaults and CLI/env only.", path)
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load config from %s: %s", path, exc)
        return {}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instagram DMs Automation - send personalized DMs from a list of usernames."
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to JSON config file (defaults to src/config/settings.example.json).",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Path to input JSON file containing targets (defaults to data/input.sample.json).",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to output JSON file to store results (defaults to data/output.example.json).",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        dest="session_id",
        help="Instagram sessionid cookie. Overrides config; IG_SESSION_ID env also supported.",
    )
    parser.add_argument(
        "--message",
        type=str,
        help="Message template to send. Supports {username} placeholder.",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        dest="min_delay",
        help="Minimum delay in seconds between messages.",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        dest="max_delay",
        help="Maximum delay in seconds between messages.",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        help="Proxy URL, e.g. http://user:pass@host:port. Overrides config; IG_PROXY_URL env also supported.",
    )
    parser.add_argument(
        "--max-targets",
        type=int,
        dest="max_targets",
        help="Maximum number of users to message in this run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate sending messages without calling Instagram.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO.",
    )
    return parser.parse_args()

def get_setting(
    cli_value: Any,
    env_var: Optional[str],
    cfg: Dict[str, Any],
    cfg_key: str,
    default: Any = None,
) -> Any:
    if cli_value is not None:
        return cli_value
    if env_var is not None:
        env_value = os.getenv(env_var)
        if env_value:
            return env_value
    if cfg_key in cfg:
        return cfg[cfg_key]
    return default

def load_targets(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Input JSON must be a list of objects.")
    valid_targets: List[Dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("Skipping non-object entry at index %d in input.", idx)
            continue
        username = item.get("username")
        if not username:
            logger.warning("Skipping entry without 'username' at index %d.", idx)
            continue
        valid_targets.append(item)
    if not valid_targets:
        logger.warning("No valid targets found in input file: %s", path)
    return valid_targets

def ensure_parent_dir(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    default_config_path = project_root / "src" / "config" / "settings.example.json"
    config_path = Path(args.config) if args.config else default_config_path

    cfg = load_config(config_path)

    session_id = get_setting(
        args.session_id,
        "IG_SESSION_ID",
        cfg,
        "session_id",
        default=None,
    )
    if not session_id:
        logger.error(
            "Instagram session ID is required. Provide via --session-id, config JSON, or IG_SESSION_ID env variable."
        )
        raise SystemExit(1)

    message_template: str = get_setting(
        args.message,
        None,
        cfg,
        "default_message",
        default="Hello {username}, this is an automated message.",
    )

    min_delay: float = float(
        get_setting(args.min_delay, None, cfg, "min_delay_seconds", default=45.0)
    )
    max_delay: float = float(
        get_setting(args.max_delay, None, cfg, "max_delay_seconds", default=60.0)
    )

    if min_delay <= 0 or max_delay <= 0 or max_delay < min_delay:
        logger.error(
            "Invalid delay configuration: min_delay=%.2f, max_delay=%.2f. Ensure both > 0 and max >= min.",
            min_delay,
            max_delay,
        )
        raise SystemExit(1)

    proxy_url: Optional[str] = get_setting(
        args.proxy,
        "IG_PROXY_URL",
        cfg,
        "proxy_url",
        default=None,
    )
    proxies = build_proxy_dict(proxy_url) if proxy_url else None

    max_targets: Optional[int] = get_setting(
        args.max_targets,
        None,
        cfg,
        "max_targets",
        default=None,
    )
    dry_run: bool = bool(args.dry_run or cfg.get("dry_run", False))

    input_path_str = get_setting(
        args.input,
        None,
        cfg,
        "input_file",
        default=str(project_root / "data" / "input.sample.json"),
    )
    output_path_str = get_setting(
        args.output,
        None,
        cfg,
        "output_file",
        default=str(project_root / "data" / "output.example.json"),
    )

    input_path = Path(input_path_str)
    output_path = Path(output_path_str)

    try:
        targets = load_targets(input_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load targets: %s", exc)
        raise SystemExit(1)

    if max_targets is not None and max_targets > 0:
        targets = targets[: max_targets]

    if not targets:
        logger.warning("No targets to process. Exiting.")
        return

    delay_manager = DelayManager(min_delay_seconds=min_delay, max_delay_seconds=max_delay)
    client = InstagramClient(session_id=session_id, proxies=proxies)

    sender = MessageSender(
        client=client,
        delay_manager=delay_manager,
        dry_run=dry_run,
    )

    ensure_parent_dir(output_path)

    try:
        results = sender.send_messages(
            targets=targets,
            message_template=message_template,
            output_path=output_path,
        )
    except InstagramAPIError as api_exc:
        logger.error("Instagram API error during sending: %s", api_exc)
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error during sending: %s", exc)
        raise SystemExit(1)

    logger.info("Completed sending messages to %d targets.", len(results))

if __name__ == "__main__":
    main()