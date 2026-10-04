"""Small HTTP helper: rate limit, retry, relaxed X509-strict (chain still verified)."""
from __future__ import annotations

import ssl
import time
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter

TPE = timezone(timedelta(hours=8))
_last_call: dict[str, float] = {}


def now_tpe() -> datetime:
    return datetime.now(TPE).replace(microsecond=0)


class _RelaxedAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        # Python 3.13 enables VERIFY_X509_STRICT; TWSE/TPEx certs lack Subject Key Identifier.
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def make_session(relax_x509_strict: bool = True) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (aicup2026-research-agent)"
    if relax_x509_strict:
        s.mount("https://", _RelaxedAdapter())
    return s


def get_bytes(session: requests.Session, url: str, *, params=None, min_interval: float = 2.5,
              timeout: float = 30, retries: int = 3) -> tuple[bytes, datetime]:
    host = url.split("/")[2]
    last_err: Exception | None = None
    for attempt in range(retries):
        wait = _last_call.get(host, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = session.get(url, params=params, timeout=timeout)
            _last_call[host] = time.time()
            r.raise_for_status()
            return r.content, now_tpe()
        except Exception as e:  # noqa: BLE001
            _last_call[host] = time.time()
            last_err = e
            time.sleep(min_interval * (attempt + 2))
    raise RuntimeError(f"GET failed after {retries} tries: {url}: {last_err}")
