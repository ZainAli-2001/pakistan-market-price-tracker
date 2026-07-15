"""
Generic HTTP transport: session creation, retries, backoff, rate-limit
handling. Returns a plain requests.Response — knows nothing about
JSON, HTML, or which scraper is calling it.
"""

import logging
import time

import requests

from utils.config import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BASE_DELAY, BACKOFF_FACTOR

log = logging.getLogger(__name__)

# Separate from the timeout/5xx backoff — a 429 means the server explicitly
# asked us to slow down, which warrants a longer wait than a dropped connection.
_RATE_LIMIT_BASE_DELAY = 10


def create_session(headers: dict = None) -> requests.Session:
    session = requests.Session()
    if headers:
        session.headers.update(headers)
    return session


def _backoff_delay(attempt: int) -> float:
    return RETRY_BASE_DELAY * (BACKOFF_FACTOR ** attempt)


def _rate_limit_delay(attempt: int, response: requests.Response) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass  # Retry-After can also be an HTTP date — not handled here
    return _RATE_LIMIT_BASE_DELAY * (BACKOFF_FACTOR ** attempt)


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
):
    """
    GET with retry + backoff. Returns a Response, or None if every
    attempt failed.

    Retries: Timeout/ConnectionError and 5xx use _backoff_delay();
    429 uses _rate_limit_delay() (respects Retry-After if present).
    Other 4xx errors fail immediately — retrying won't help a
    malformed request or a genuine 404.
    """
    for attempt in range(max_retries):
        is_last_attempt = attempt == max_retries - 1

        try:
            response = session.get(url, params=params, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if is_last_attempt:
                log.error("  FAILED (attempt %d/%d) %s: %s", attempt + 1, max_retries, url, e)
                return None
            delay = _backoff_delay(attempt)
            log.warning(
                "  Request error (attempt %d/%d) %s: %s — retrying in %.0fs",
                attempt + 1, max_retries, url, e, delay
            )
            time.sleep(delay)
            continue
        
        if response.status_code == 403:
            if is_last_attempt:
                log.error("  BLOCKED (anti-bot, attempt %d/%d) %s", attempt + 1, max_retries, url)
                return None
            delay = _rate_limit_delay(attempt, response)
            log.warning(
                "  Possible anti-bot block (attempt %d/%d) %s — retrying in %.0fs",
                attempt + 1, max_retries, url, delay
            )
            time.sleep(delay)
            continue

        if response.status_code == 429:
            if is_last_attempt:
                log.error("  FAILED (rate limited, attempt %d/%d) %s", attempt + 1, max_retries, url)
                return None
            delay = _rate_limit_delay(attempt, response)
            log.warning(
                "  Rate limited 429 (attempt %d/%d) %s — retrying in %.0fs",
                attempt + 1, max_retries, url, delay
            )
            time.sleep(delay)
            continue

        if response.status_code >= 500:
            if is_last_attempt:
                log.error(
                    "  FAILED (HTTP %d, attempt %d/%d) %s",
                    response.status_code, attempt + 1, max_retries, url
                )
                return None
            delay = _backoff_delay(attempt)
            log.warning(
                "  Server error %d (attempt %d/%d) %s — retrying in %.0fs",
                response.status_code, attempt + 1, max_retries, url, delay
            )
            time.sleep(delay)
            continue

        if response.status_code >= 400:
            log.error("  Client error %d (not retrying) %s", response.status_code, url)
            return None

        return response

    return None
