"""
Shared Socrata client for the sidewalk shed pipeline.

Every network call in this project goes through fetch_json(). That is deliberate:
the previous version of this pipeline retried only its main paginated fetch, so a
single blip on any of the PLUTO / FISP / HPD chunk loops aborted the whole nightly
run. Centralising the transport means retry, backoff, timeout and app-token
handling are applied uniformly and cannot be forgotten at a call site.
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

UA = "nyc-sidewalk-sheds/2.0 (+https://github.com/joshgreenman1973/nyc-sidewalk-sheds)"

# Socrata allows far higher throughput for requests carrying an app token, and
# throttles anonymous traffic against a shared pool. Anonymous still works; it is
# just the most likely reason a nightly run flakes.
APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN", "").strip()

MAX_ATTEMPTS = 5
BASE_BACKOFF = 2.0
TIMEOUT = 180


def has_token() -> bool:
    return bool(APP_TOKEN)


def _headers() -> dict:
    h = {"User-Agent": UA, "Accept": "application/json"}
    if APP_TOKEN:
        h["X-App-Token"] = APP_TOKEN
    return h


class SocrataError(RuntimeError):
    pass


def fetch_json(url: str, *, what: str = "request"):
    """GET a Socrata URL with retry + exponential backoff. Raises on final failure.

    Raising rather than returning a sentinel is the point: a caller that silently
    swallows an error would write a truncated dataset over good data.
    """
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(Request(url, headers=_headers()), timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except HTTPError as e:
            last = e
            # 429 = throttled, 5xx = transient upstream. Both are worth retrying.
            # 4xx other than 429 means a malformed query; retrying cannot help.
            if e.code != 429 and 400 <= e.code < 500:
                raise SocrataError(f"{what}: HTTP {e.code} (query error, not retrying): {url}") from e
            wait = BASE_BACKOFF * (2 ** (attempt - 1))
            if e.code == 429:
                wait = max(wait, 30)
            print(f"  [{what}] HTTP {e.code}, attempt {attempt}/{MAX_ATTEMPTS}, sleeping {wait:.0f}s", file=sys.stderr)
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            wait = BASE_BACKOFF * (2 ** (attempt - 1))
            print(f"  [{what}] {type(e).__name__}: {e}; attempt {attempt}/{MAX_ATTEMPTS}, sleeping {wait:.0f}s", file=sys.stderr)
        if attempt < MAX_ATTEMPTS:
            time.sleep(wait)
    raise SocrataError(f"{what}: failed after {MAX_ATTEMPTS} attempts: {last}")


def build_url(resource: str, select: str = "*", where: str | None = None,
              group: str | None = None, order: str | None = None,
              limit: int = 50000, offset: int = 0) -> str:
    parts = [f"$select={quote(select)}", f"$limit={limit}", f"$offset={offset}"]
    if where:
        parts.append(f"$where={quote(where)}")
    if group:
        parts.append(f"$group={quote(group)}")
    if order:
        parts.append(f"$order={quote(order)}")
    return f"https://data.cityofnewyork.us/resource/{resource}.json?" + "&".join(parts)


def fetch_all(resource: str, where: str | None = None, select: str = "*",
              page: int = 50000, order: str = ":id", what: str | None = None) -> list:
    """Page through a resource until exhausted."""
    label = what or resource
    out: list = []
    offset = 0
    while True:
        url = build_url(resource, select=select, where=where, order=order, limit=page, offset=offset)
        chunk = fetch_json(url, what=label)
        out.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    print(f"  {label}: {len(out):,} rows", file=sys.stderr)
    return out


def fetch_in_chunks(resource: str, field: str, values: list[str], select: str,
                    chunk_size: int = 400, what: str | None = None) -> list:
    """Fetch rows where `field` matches any of `values`, batched into IN() clauses.

    Every batch goes through fetch_json, so each one retries independently.
    """
    label = what or resource
    out: list = []
    total = len(values)
    for i in range(0, total, chunk_size):
        batch = values[i : i + chunk_size]
        in_clause = ",".join("'" + str(v).replace("'", "''") + "'" for v in batch)
        url = build_url(resource, select=select, where=f"{field} in({in_clause})", limit=50000)
        out.extend(fetch_json(url, what=f"{label} [{i}-{i+len(batch)}]"))
        if (i // chunk_size) % 10 == 0:
            print(f"  {label}: {min(i + chunk_size, total):,}/{total:,}", file=sys.stderr)
    print(f"  {label}: {len(out):,} rows", file=sys.stderr)
    return out
