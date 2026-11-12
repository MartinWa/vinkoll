"""Opt-in, read-only Stage 0 checks. Never run in CI or save upstream credentials.

The evidence file contains bounded product/store observations, not HTTP headers,
page scripts, credentials or user cellar records. It belongs in ignored test-results.
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

WEBSITE = "https://www.systembolaget.se"
API = "https://api-extern.systembolaget.se/sb-api-ecommerce/v1"
MAX_BYTES = 4 * 1024 * 1024


def fetch(url, key=None):
    headers = {"Accept": "application/json", "User-Agent": "Vinkoll-stage0-validation/0.1"}
    if key:
        headers.update({"Origin": WEBSITE, "Ocp-Apim-Subscription-Key": key})
    request = urllib.request.Request(url, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return {"status": "oversized", "elapsed": round(time.monotonic() - start, 2)}
            return {
                "status": response.status,
                "body": body,
                "cache_control": response.headers.get("Cache-Control", ""),
                "elapsed": round(time.monotonic() - start, 2),
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "elapsed": round(time.monotonic() - start, 2)}
    except urllib.error.URLError, TimeoutError:
        return {"status": "unavailable", "elapsed": round(time.monotonic() - start, 2)}


def discover_key():
    home = fetch(WEBSITE)
    if home.get("status") != 200:
        return None, {"status": home["status"], "phase": "homepage"}
    chunks = list(
        dict.fromkeys(re.findall(rb'src="(/_next/static/chunks/[^"?]+\.js)"', home["body"]))
    )
    deadline = time.monotonic() + 60
    for index, chunk in enumerate(chunks[:40]):
        if time.monotonic() >= deadline:
            break
        result = fetch(WEBSITE + chunk.decode())
        match = re.search(rb'NEXT_PUBLIC_API_KEY_APIM:"([^"\s]+)"', result.get("body", b""))
        if match:
            return match[1].decode(), {"status": "discovered", "chunks_checked": index + 1}
    return None, {"status": "not_discovered", "phase": "script_chunks", "chunks_found": len(chunks)}


def json_result(url, key=None):
    result = fetch(url, key)
    body = result.pop("body", None)
    if body is not None:
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Expected an object response.")
            result["data"] = data
        except ValueError, UnicodeDecodeError:
            result["status"] = "malformed_json"
    return result


def product_summary(product):
    fields = [
        "productId",
        "productNumber",
        "productNumberShort",
        "productNameBold",
        "productNameThin",
        "producerName",
        "categoryLevel1",
        "categoryLevel2",
        "volume",
        "vintage",
        "grapes",
        "price",
    ]
    return {field: product[field] for field in fields if field in product}


def search(query, key, page=1):
    url = (
        API
        + "/productsearch/search?"
        + urllib.parse.urlencode(
            {
                "textQuery": query,
                "size": 10,
                "page": page,
            }
        )
    )
    result = json_result(url, key)
    data = result.pop("data", {})
    result.update(
        {
            "query": query,
            "page": page,
            "metadata": data.get("metadata", {}),
            "products": [product_summary(p) for p in data.get("products", [])],
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proxy", help="Loopback-only URL for the isolated stock proxy under test."
    )
    parser.add_argument("--output", type=Path, default=Path("test-results/stage0-live.json"))
    args = parser.parse_args()
    if args.proxy and urllib.parse.urlparse(args.proxy).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("The diagnostic proxy must be a loopback test listener.")
    evidence = {"retrieved_at": datetime.now(UTC).isoformat(), "lookups": [], "searches": []}
    for article in ["512301", "5123", "777000000000"]:
        result = json_result("https://susbolaget.emrik.org/v1/product/" + article)
        data = result.pop("data", None)
        if isinstance(data, dict):
            result["product"] = product_summary(data)
        result["article"] = article
        evidence["lookups"].append(result)
    key, evidence["authentication"] = discover_key()
    if key:
        for query in [
            "Masi Campofiorin",
            "5123",
            "512301",
            "Riesling",
            "Prosecco",
            "vinkoll_no_such_wine_777000000000",
        ]:
            evidence["searches"].append(search(query, key))
        evidence["searches"].append(search("Riesling", key, page=2))
        evidence["without_authentication"] = search("512301", None)
        store = json_result(
            API + "/sitesearch/site?q=F%C3%A4lt%C3%B6versten&includePredictions=false", key
        )
        data = store.pop("data", {})
        store["stores"] = [
            {k: row.get(k) for k in ["siteId", "displayName", "city"]}
            for row in data.get("siteSearchResults", [])
        ]
        evidence["store_search"] = store
        evidence["stock"] = []
        evidence["store_products"] = json_result(
            API
            + "/productsearch/search?"
            + urllib.parse.urlencode(
                {
                    "size": 2,
                    "page": 1,
                    "categoryLevel1": "Vin",
                    "storeId": "0102",
                    "isInStoreAssortmentSearch": "true",
                }
            ),
            key,
        )
        store_data = evidence["store_products"].pop("data", {})
        store_products = store_data.get("products", [])
        evidence["store_products"]["products"] = [product_summary(p) for p in store_products]
        selected = next(
            (
                item
                for result in evidence["searches"]
                for item in result["products"]
                if item.get("productNumber") == "512301"
            ),
            {},
        )
        identifiers = list(
            dict.fromkeys(
                str(v)
                for v in [
                    selected.get("productId"),
                    "512301",
                    "5123",
                    "777000000000",
                    *(
                        value
                        for p in store_products
                        for value in [p["productId"], p["productNumber"]]
                    ),
                ]
                if v
            )
        )
        for identifier in identifiers:
            result = json_result(API + f"/stockbalance/store/0102/{identifier}/", key)
            result["requested_identifier"] = identifier
            evidence["stock"].append(result)
        if args.proxy:
            evidence["proxy"] = []
            for identifier in identifiers:
                result = json_result(
                    args.proxy.rstrip("/") + f"/api/v1/stores/0102/products/{identifier}"
                )
                data = result.get("data")
                if isinstance(data, dict):
                    result["data"] = {k: data.get(k) for k in ["stock", "shelf", "number", "title"]}
                result["requested_identifier"] = identifier
                evidence["proxy"].append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
