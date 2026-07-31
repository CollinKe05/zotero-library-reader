"""Small standard-library client for Scite public citation endpoints."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = "https://api.scite.ai"
USER_AGENT = "zotero-local-reader/0.2"


def normalize_doi(value: str) -> str:
    doi = value.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip()


def _request_json(
    path: str,
    payload: Any | None = None,
    timeout: int = 15,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        method="POST" if payload is not None else "GET",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"Scite HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Scite request failed: {exc}") from exc


def enrich_doi(doi: str, timeout: int = 15) -> dict[str, Any]:
    normalized = normalize_doi(doi)
    if not normalized:
        raise ValueError("DOI cannot be empty")
    encoded = quote(normalized, safe="/")
    tally = _request_json(f"/tallies/{encoded}", timeout=timeout)
    paper = _request_json(f"/papers/{encoded}", timeout=timeout)
    notices = (paper or {}).get("editorialNotices", [])
    return {
        "doi": normalized,
        "found": tally is not None or paper is not None,
        "title": (paper or {}).get("title"),
        "supporting": (tally or {}).get("supporting", 0),
        "contrasting": (tally or {}).get("contradicting", 0),
        "mentioning": (tally or {}).get("mentioning", 0),
        "total": (tally or {}).get("total"),
        "citingPublications": (tally or {}).get("citingPublications"),
        "editorialNotices": notices,
        "reportUrl": f"https://scite.ai/reports/{normalized}",
    }


def enrich_items(
    items: list[dict[str, Any]],
    timeout: int = 15,
) -> dict[str, Any]:
    doi_items: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        doi = normalize_doi(str(item.get("DOI") or ""))
        if doi:
            doi_items.setdefault(doi.lower(), []).append(item)

    if not doi_items:
        return {
            "itemCount": len(items),
            "doiCount": 0,
            "coveredCount": 0,
            "flaggedCount": 0,
            "items": [],
        }

    dois = [records[0]["DOI"] for records in doi_items.values()]
    tallies: dict[str, Any] = {}
    papers: dict[str, Any] = {}
    for offset in range(0, len(dois), 500):
        chunk = [normalize_doi(doi) for doi in dois[offset : offset + 500]]
        tally_response = _request_json("/tallies", chunk, timeout=timeout) or {}
        paper_response = _request_json("/papers", chunk, timeout=timeout) or {}
        tallies.update(
            {
                key.lower(): value
                for key, value in tally_response.get("tallies", {}).items()
            }
        )
        papers.update(
            {
                key.lower(): value
                for key, value in paper_response.get("papers", {}).items()
            }
        )

    result: list[dict[str, Any]] = []
    for lower_doi, records in doi_items.items():
        tally = tallies.get(lower_doi, {})
        paper = papers.get(lower_doi, {})
        notices = paper.get("editorialNotices", [])
        for item in records:
            result.append(
                {
                    "key": item.get("key"),
                    "title": item.get("title"),
                    "DOI": normalize_doi(item.get("DOI", "")),
                    "found": bool(tally or paper),
                    "supporting": tally.get("supporting", 0),
                    "contrasting": tally.get("contradicting", 0),
                    "mentioning": tally.get("mentioning", 0),
                    "total": tally.get("total"),
                    "citingPublications": tally.get("citingPublications"),
                    "editorialNotices": notices,
                    "reportUrl": (
                        f"https://scite.ai/reports/"
                        f"{normalize_doi(item.get('DOI', ''))}"
                    ),
                }
            )

    return {
        "itemCount": len(items),
        "doiCount": len(doi_items),
        "coveredCount": sum(1 for item in result if item["found"]),
        "flaggedCount": sum(1 for item in result if item["editorialNotices"]),
        "items": result,
    }
