from typing import Dict, Optional
from urllib.parse import urlparse

def build_proxy_dict(proxy_url: str) -> Optional[Dict[str, str]]:
    """
    Build a requests-compatible proxy dict from a single proxy URL.

    Example:
        http://user:pass@host:port
        socks5://user:pass@host:port
    """
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid proxy URL: {proxy_url}")

    proxy_str = proxy_url
    # requests expects full URLs per scheme
    return {
        "http": proxy_str,
        "https": proxy_str,
    }