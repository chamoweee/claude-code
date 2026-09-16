"""A very small HTTP helper.

Standard library only, so the agent keeps its zero-dependency runtime. It exists
to put retries, timeouts and a user agent in one place, and to make every fetch
loggable and mockable in tests.

Tests never call this. They feed recorded JSON to the parsers directly.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

USER_AGENT = "Mozilla/5.0 (compatible; OpportunityRadar/0.1; personal research agent)"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3


class FetchError(RuntimeError):
    """A fetch that failed after exhausting retries."""

    def __init__(self, url: str, attempts: int, last_error: BaseException):
        self.url = url
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"{url} failed after {attempts} attempt(s): "
                         f"{type(last_error).__name__}: {last_error}")


def fetch_text(url: str, *, timeout: float = DEFAULT_TIMEOUT,
               retries: int = DEFAULT_RETRIES,
               sleep: Callable[[float], None] = time.sleep) -> str:
    """GET a URL, retrying transient failures with exponential backoff.

    ``urllib`` reads ``HTTPS_PROXY`` from the environment on its own, so this
    works unchanged behind a proxy.
    """
    last_error: BaseException = RuntimeError("no attempt made")
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 4xx other than 429 will not become true by trying again.
            if exc.code != 429 and 400 <= exc.code < 500:
                raise FetchError(url, attempt, exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < retries:
            sleep(2.0 ** (attempt - 1))
    raise FetchError(url, retries, last_error)


def fetch_json(url: str, **kwargs: Any) -> Any:
    text = fetch_text(url, **kwargs)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FetchError(url, 1, exc) from exc
