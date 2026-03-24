"""
Mercari Japan adapter — calls api.mercari.jp/v2/entities:search directly.

NOTE: This wraps the Mercari Japan API (jp.mercari.com). Mercari US has no
maintained public API. Prices are in JPY (¥).

The API uses DPOP JWT authentication — a fresh EC P-256 key pair is generated
per request. Mercari's implementation only validates that the signature matches
the embedded public key; it does not check key identity across requests.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from time import time

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.mercari.jp/v2/entities:search"
_PRODUCT_URL = "https://jp.mercari.com/item/"


def _to_b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _int_to_b64url(n: int) -> str:
    return _to_b64url(n.to_bytes((n.bit_length() + 7) // 8, byteorder="big"))


def _generate_dpop(method: str, url: str) -> str:
    """Generate a Mercari-compatible DPOP JWT signed with a fresh EC P-256 key."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    nums = public_key.public_numbers()

    header = {
        "typ": "dpop+jwt",
        "alg": "ES256",
        "jwk": {"crv": "P-256", "kty": "EC",
                 "x": _int_to_b64url(nums.x), "y": _int_to_b64url(nums.y)},
    }
    payload = {"iat": int(time()), "jti": str(uuid.uuid4()), "htu": url, "htm": method.upper()}

    data = (
        f"{_to_b64url(json.dumps(header).encode())}"
        f".{_to_b64url(json.dumps(payload).encode())}"
    )
    sig = private_key.sign(data.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(sig)
    r_bytes = r.to_bytes((r.bit_length() + 7) // 8, byteorder="big")
    s_bytes = s.to_bytes((s.bit_length() + 7) // 8, byteorder="big")
    return f"{data}.{_to_b64url(r_bytes + s_bytes)}"


class MercariUSAdapter(BaseAdapter):
    source_type = "shopping"

    def __init__(self) -> None:
        self._last_failed: bool = False

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        self._last_failed = False
        terms = source_config.terms or [topic.name]
        results: list[Result] = []

        for term in terms:
            try:
                items = self._search(term)
            except Exception as exc:
                logger.warning("Mercari search failed for '%s': %s", term, exc)
                self._last_failed = True
                return []

            for item in items:
                item_id = item.get("id", "")
                price_raw = item.get("price")
                try:
                    price = f"¥{int(price_raw):,}" if price_raw is not None else None
                except (TypeError, ValueError):
                    price = str(price_raw) if price_raw is not None else None

                results.append(
                    Result(
                        url=f"{_PRODUCT_URL}{item_id}",
                        title=item.get("name", ""),
                        snippet="",
                        source="mercari",
                        source_type=self.source_type,
                        topic_name=topic.name,
                        fetched_at=datetime.now(timezone.utc),
                        price=price,
                        raw=item,
                    )
                )

        return results

    def _search(self, keyword: str, limit: int = 30) -> list[dict]:
        body = json.dumps(
            {
                "userId": f"MERCARI_BOT_{uuid.uuid4()}",
                "pageSize": limit,
                "pageToken": "v1:0",
                "searchSessionId": f"MERCARI_BOT_{uuid.uuid4()}",
                "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
                "searchCondition": {
                    "keyword": keyword,
                    "sort": "SORT_CREATED_TIME",
                    "order": "ORDER_DESC",
                    "status": ["STATUS_ON_SALE"],
                    "excludeKeyword": "",
                },
                "withAuction": True,
                "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
            },
            ensure_ascii=False,
        ).encode("utf-8")

        resp = requests.post(
            _SEARCH_URL,
            headers={
                "DPOP": _generate_dpop("POST", _SEARCH_URL),
                "X-Platform": "web",
                "Accept": "*/*",
                "Accept-Encoding": "deflate, gzip",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "python-mercari",
            },
            data=body,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
