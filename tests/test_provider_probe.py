"""Offline checks for the diagnostic contracts; no provider calls are made in CI."""

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import probe_systembolaget as probe

FIXTURES = Path(__file__).parent / "fixtures" / "systembolaget"


class Response(io.BytesIO):
    status = 200
    headers = {"Cache-Control": "max-age=600"}


def test_synthetic_search_contract_retains_identifiers_variants_and_missing_fields():
    first = json.loads((FIXTURES / "search_page1.json").read_text(encoding="utf-8"))
    second = json.loads((FIXTURES / "search_page2.json").read_text(encoding="utf-8"))
    with patch.object(probe, "json_result", return_value={"status": 200, "data": first}):
        page = probe.search("99001", "synthetic-key")
    assert page["metadata"]["nextPage"] == 2
    assert [p["volume"] for p in page["products"][:2]] == [750, 1500]
    assert page["products"][0]["productId"] != page["products"][0]["productNumber"]
    assert page["products"][1]["vintage"] is None
    assert page["products"][0]["grapes"] == ["Corvina", "Rondinella"]
    assert page["products"][2]["categoryLevel1"] == "Öl"
    assert "vintage" not in second["products"][0]


def test_synthetic_stock_and_proxy_contract():
    positive = json.loads((FIXTURES / "stock_positive.json").read_text())
    zero = json.loads((FIXTURES / "stock_zero.json").read_text())
    proxy = json.loads((FIXTURES / "proxy_positive.json").read_text())
    assert positive["storeId"] == zero["storeId"] == "0102"
    assert positive["stock"] == proxy["stock"] == 7
    assert zero["stock"] == 0 and zero["shelf"] is None


@pytest.mark.parametrize("code", [401, 404, 429, 500, 503])
def test_http_failures_remain_failures_and_never_look_like_zero_stock(code):
    error = urllib.error.HTTPError("https://example.invalid", code, "synthetic", {}, None)
    with patch.object(probe.urllib.request, "urlopen", side_effect=error):
        result = probe.json_result("https://example.invalid")
    assert result["status"] == code and "data" not in result


@pytest.mark.parametrize("error", [urllib.error.URLError("offline"), TimeoutError()])
def test_outages_and_timeouts_are_distinct_from_zero_stock(error):
    with patch.object(probe.urllib.request, "urlopen", side_effect=error):
        result = probe.json_result("https://example.invalid")
    assert result["status"] == "unavailable" and "data" not in result


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null"])
def test_malformed_json_is_explicit(body):
    with patch.object(probe.urllib.request, "urlopen", return_value=Response(body)):
        result = probe.json_result("https://example.invalid")
    assert result["status"] == "malformed_json" and "body" not in result


def test_response_limit_and_timeout():
    with (
        patch.object(probe, "MAX_BYTES", 3),
        patch.object(probe.urllib.request, "urlopen", return_value=Response(b"1234")) as open_url,
    ):
        result = probe.fetch("https://example.invalid")
    assert result["status"] == "oversized" and "body" not in result
    assert open_url.call_args.kwargs["timeout"] == 12


def test_credentials_are_never_in_probe_output_or_query():
    key = "synthetic-credential-never-log"
    with patch.object(
        probe.urllib.request, "urlopen", return_value=Response(b'{"products": []}')
    ) as call:
        result = probe.json_result(probe.API + "/productsearch/search", key)
    assert key not in json.dumps(result)
    assert key not in call.call_args.args[0].full_url
    assert call.call_args.args[0].get_header("Ocp-apim-subscription-key") == key
