"""Managed AdverseMediaPort: the Hrz3 knowledge base's adverse-media collection.

The client is imported lazily inside the method, so the offline profiles bind this adapter and
construct it with no cloud SDK installed. Each hit maps to an item carrying the document id and
passage locator as its Citation, and ``relevance`` is read from the FEED's own field: entity
resolution is not inferred here, because a fuzzy name match is the classic adverse-media false
positive and this repo must not be the place it happens.

A hit with no resolvable locator is DROPPED rather than carried, because an item that cannot be
cited cannot be scored. An unconfigured knowledge-base URL RAISES.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from ...config import Settings
from ...domain.kernel import Citation
from ...domain.models import AdverseNewsItem, NewsCategory, NewsRelevance

_ENDPOINT_ENV = "CREDITEWS_KNOWLEDGE_BASE_URL"


class Hrz3AdverseMedia:
    """Retrieve adverse media for one obligor from the shared knowledge base."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def items(
        self, obligor_id: str, *, tenant: str, as_of: date, lookback_days: int
    ) -> tuple[AdverseNewsItem, ...]:
        base = self._settings.knowledge_base_url.strip()
        if not base:
            raise RuntimeError(
                f"{_ENDPOINT_ENV} is not configured, so adverse media cannot be retrieved. It "
                "refuses rather than returning an empty result, because an unconfigured feed "
                "and an obligor with no coverage must not look the same."
            )
        query = urllib.parse.urlencode(
            {
                "obligor_id": obligor_id,
                "tenant": tenant,
                "as_of": as_of.isoformat(),
                "lookback_days": lookback_days,
                "collection": "adverse-media",
            }
        )
        body = self._get(base.rstrip("/") + "/v1/search?" + query)
        items = [_item_from_hit(hit, obligor_id) for hit in body.get("hits", [])]
        # An item with no locator is dropped, not carried: the engine would raise on it, and
        # dropping it here keeps the refusal where the evidence is, not where the score is.
        return tuple(item for item in items if item is not None)

    def _get(self, url: str) -> Any:
        # Lazy import: every profile binds this adapter and must construct with no SDK present.
        import google.auth.transport.requests
        from google.oauth2 import id_token

        request = google.auth.transport.requests.Request()
        token = str(id_token.fetch_id_token(request, url.split("/v1/")[0]))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310 - fixed base
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:  # pragma: no cover - needs a live knowledge base
            return {}


def _item_from_hit(hit: Any, obligor_id: str) -> AdverseNewsItem | None:
    document_id = str(hit.get("document_id", "")).strip()
    passage_ref = str(hit.get("passage_ref", "")).strip()
    if not document_id:
        return None
    published = str(hit.get("published_on", "")).strip()
    try:
        published_on = date.fromisoformat(published)
    except ValueError:
        return None
    return AdverseNewsItem(
        item_id=str(hit.get("item_id") or document_id),
        obligor_id=obligor_id,
        headline=str(hit.get("headline", "")),
        published_on=published_on,
        citation=Citation(
            source_id=f"kb:{document_id}",
            title=str(hit.get("source_name", "Adverse media")),
            snippet=passage_ref or str(hit.get("snippet", "")),
        ),
        relevance=NewsRelevance(str(hit.get("relevance", "unconfirmed"))),
        category=NewsCategory(str(hit.get("category", "unclear"))),
        classified_by=str(hit.get("classified_by", "")),
        snippet=str(hit.get("snippet", "")),
        source_ref=passage_ref,
    )
