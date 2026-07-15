"""Per-portal fetch adapters behind a unified PortalFetcher protocol.

Three implementations:
  OpenDataSoftClient — for SPEN and ENWL (OpenDataSoft v2.1 API)
  CkanClient         — for SSEN (CKAN API)
  NgedPortalClient   — for NGED (National Grid / Western Power own portal)

All adapters:
  - Respect rate limits (configurable RPS)
  - Retry with exponential backoff
  - Cache responses in the portal_cache SQLite table
  - Return raw records as list[dict] for normalisation
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .config import PortalConfig, config
from .db import cache_get, cache_put


class PortalFetcher(ABC):
    """Protocol for all portal fetch adapters."""

    portal_id: str
    pcfg: PortalConfig

    def __init__(self, portal_id: str, pcfg: PortalConfig):
        self.portal_id = portal_id
        self.pcfg = pcfg
        self._last_request_time: float = 0.0
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # Rate limiting + retry
    # ------------------------------------------------------------------

    def _rate_limit_wait(self) -> None:
        """Sleep if needed to respect rate limit."""
        if self.pcfg.rate_limit_rps <= 0:
            return
        min_interval = 1.0 / self.pcfg.rate_limit_rps
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def _get_client(self) -> httpx.Client:
        """Return a reusable httpx.Client, creating it lazily on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self.pcfg.timeout_seconds)
        return self._client

    def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None and not self._client.is_closed:
            self._client.close()
        self._client = None

    def __enter__(self) -> "PortalFetcher":
        """Support context manager usage."""
        return self

    def __exit__(self, *args) -> None:
        """Close the client on context exit."""
        self.close()

    def _fetch_with_retry(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """HTTP GET with rate limiting, retry, and exponential backoff."""
        last_error: Exception | None = None
        for attempt in range(self.pcfg.max_retries + 1):
            self._rate_limit_wait()
            try:
                client = self._get_client()
                resp = client.get(url, params=params)
                self._last_request_time = time.monotonic()
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_error = e
                if attempt < self.pcfg.max_retries:
                    wait = 2 ** attempt
                    time.sleep(wait)
        raise RuntimeError(
            f"Failed to fetch {url} after {self.pcfg.max_retries + 1} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _get_cached(self) -> list[dict[str, Any]] | None:
        """Return cached data if available, else None."""
        cached = cache_get(self.portal_id)
        if cached is not None:
            return cached["data"]
        return None

    def _put_cache(self, data: list[dict[str, Any]], url: str) -> None:
        """Store fetched data in cache."""
        cache_put(self.portal_id, url, data)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def _fetch_raw(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch raw records from the portal. Must be implemented by subclasses."""
        ...

    def fetch(
        self,
        dataset_id: str | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Public entry point: fetch data, using cache if available."""
        if use_cache:
            cached = self._get_cached()
            if cached is not None:
                return cached
        data = self._fetch_raw(dataset_id)
        self._put_cache(data, self.pcfg.base_url)
        return data

    def fetch_fields(self, dataset_id: str) -> list[str]:
        """Return the field names for a dataset (if the portal supports it)."""
        return []  # Override in subclasses


# ---------------------------------------------------------------------------
# OpenDataSoft v2.1 (SPEN, ENWL)
# ---------------------------------------------------------------------------

class OpenDataSoftClient(PortalFetcher):
    """OpenDataSoft v2.1 API client.

    API docs: https://help.opendatasoft.com/apis/ods-explore-v2/
    """

    def __init__(self, portal_id: str, pcfg: PortalConfig):
        super().__init__(portal_id, pcfg)
        self._api_base = pcfg.api_url or f"{pcfg.base_url}/api/v2"

    def _fetch_raw(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch all records from an ODS dataset, paginating if needed."""
        if not dataset_id:
            raise ValueError("OpenDataSoft requires a dataset_id")

        all_records: list[dict[str, Any]] = []
        offset = 0
        limit = 100  # ODS default max per page

        while True:
            url = f"{self._api_base}/catalog/datasets/{dataset_id}/exports/json"
            params = {"offset": offset, "limit": limit}
            resp = self._fetch_with_retry(url, params)

            if isinstance(resp, list):
                records = resp
            elif isinstance(resp, dict) and "results" in resp:
                records = resp["results"]
            else:
                records = [resp] if resp else []

            if not records:
                break

            all_records.extend(records)
            if len(records) < limit:
                break
            offset += limit

        return all_records

    def fetch_fields(self, dataset_id: str) -> list[str]:
        """Get field names from ODS dataset metadata."""
        url = f"{self._api_base}/catalog/datasets/{dataset_id}"
        resp = self._fetch_with_retry(url)
        fields = resp.get("dataset", {}).get("fields", [])
        return [f.get("name", "") for f in fields]

    def list_datasets(self, query: str = "flexibility") -> list[dict[str, Any]]:
        """Search for datasets on the portal."""
        url = f"{self._api_base}/catalog/datasets"
        params = {"q": query, "limit": 20}
        resp = self._fetch_with_retry(url, params)
        datasets = resp.get("datasets", [])
        return [
            {
                "id": d.get("dataset", {}).get("dataset_id", ""),
                "title": d.get("dataset", {}).get("metas", {}).get("default", {}).get("title", ""),
                "record_count": d.get("dataset", {}).get("metas", {}).get("default", {}).get("records_count"),
            }
            for d in datasets
        ]


# ---------------------------------------------------------------------------
# CKAN (SSEN)
# ---------------------------------------------------------------------------

class CkanClient(PortalFetcher):
    """CKAN API client for SSEN data portal.

    API docs: https://docs.ckan.org/en/2.9/api/
    """

    def __init__(self, portal_id: str, pcfg: PortalConfig):
        super().__init__(portal_id, pcfg)
        self._api_base = pcfg.api_url or f"{pcfg.base_url}/api/3/action"

    def _fetch_raw(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch all records from a CKAN resource."""
        if not dataset_id:
            raise ValueError("CKAN requires a dataset_id (resource_id or package name)")

        # First, try as a resource_id directly
        url = f"{self._api_base}/datastore_search"
        params: dict[str, Any] = {"resource_id": dataset_id, "limit": 100}

        all_records: list[dict[str, Any]] = []
        offset = 0
        max_pages = self.pcfg.max_pages
        page = 0

        while page < max_pages:
            params["offset"] = offset
            resp = self._fetch_with_retry(url, params)
            result = resp.get("result", {})
            records = result.get("records", [])

            if not records:
                break

            all_records.extend(records)
            total = result.get("total", 0)
            offset += len(records)
            page += 1
            if offset >= total:
                break

        return all_records

    def fetch_fields(self, dataset_id: str) -> list[str]:
        """Get field names from CKAN datastore info."""
        url = f"{self._api_base}/datastore_search"
        params = {"resource_id": dataset_id, "limit": 1}
        resp = self._fetch_with_retry(url, params)
        fields = resp.get("result", {}).get("fields", [])
        return [f["id"] for f in fields if f["id"] != "_id"]

    def list_datasets(self, query: str = "flexibility") -> list[dict[str, Any]]:
        """Search for packages on the CKAN portal."""
        url = f"{self._api_base}/package_search"
        params = {"q": query, "rows": 20}
        resp = self._fetch_with_retry(url, params)
        packages = resp.get("result", {}).get("results", [])
        return [
            {
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "resources": [
                    {"id": r.get("id", ""), "name": r.get("name", "")}
                    for r in p.get("resources", [])
                ],
            }
            for p in packages
        ]


# ---------------------------------------------------------------------------
# NGED Portal (National Grid / Western Power)
# ---------------------------------------------------------------------------

class NgedPortalClient(PortalFetcher):
    """NGED portal client — uses their connected data portal API.

    NGED exposes data via connecteddata.nationalgrid.co.uk and
    dataportal2.westernpower.co.uk. The API shape is ODS-like but
    we treat it separately since it may diverge.
    """

    def __init__(self, portal_id: str = "nged", pcfg: PortalConfig | None = None):
        super().__init__(portal_id, pcfg or config.portal("nged"))
        self._api_base = self.pcfg.api_url or f"{self.pcfg.base_url}/api/v2"

    def _fetch_raw(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch records from NGED connected data portal.

        NGED's portal is ODS-compatible, so we use the same approach
        as OpenDataSoftClient but keep it separate for future divergence.
        """
        if not dataset_id:
            raise ValueError("NGED portal requires a dataset_id")

        all_records: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            url = f"{self._api_base}/catalog/datasets/{dataset_id}/exports/json"
            params = {"offset": offset, "limit": limit}
            resp = self._fetch_with_retry(url, params)

            records = resp if isinstance(resp, list) else []
            if not records:
                break

            all_records.extend(records)
            if len(records) < limit:
                break
            offset += limit

        return all_records

    def fetch_fields(self, dataset_id: str) -> list[str]:
        url = f"{self._api_base}/catalog/datasets/{dataset_id}"
        resp = self._fetch_with_retry(url)
        fields = resp.get("dataset", {}).get("fields", [])
        return [f.get("name", "") for f in fields]

    def list_datasets(self, query: str = "flexibility") -> list[dict[str, Any]]:
        url = f"{self._api_base}/catalog/datasets"
        params = {"q": query, "limit": 20}
        resp = self._fetch_with_retry(url, params)
        datasets = resp.get("datasets", [])
        return [
            {
                "id": d.get("dataset", {}).get("dataset_id", ""),
                "title": d.get("dataset", {}).get("metas", {}).get("default", {}).get("title", ""),
            }
            for d in datasets
        ]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_fetcher(portal_id: str) -> PortalFetcher:
    """Get the appropriate fetcher for a portal ID."""
    fetchers: dict[str, type[PortalFetcher]] = {
        "nged": NgedPortalClient,
        "nged_params": NgedPortalClient,
        "spen": OpenDataSoftClient,
        "enwl": OpenDataSoftClient,
        "ssen": CkanClient,
    }
    cls = fetchers.get(portal_id)
    if cls is None:
        raise KeyError(f"No fetcher for portal '{portal_id}'. Available: {list(fetchers.keys())}")
    if cls is NgedPortalClient:
        return cls(portal_id, config.portal(portal_id))
    return cls(portal_id, config.portal(portal_id))
