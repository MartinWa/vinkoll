# Stage 0 integration validation

Validated on 11 November 2026, approximately 17:35–17:40 UTC. These are observations of changeable website-facing services, not a supported API guarantee. Stage 0 establishes contracts and an implementation choice; the application search/import and stock workflows remain Stages 3 and 4.

**Result:** product search, individual lookup and direct store-stock requests work. Use direct backend adapters for search, store search and stock. Do not make the released v5 stock proxy a production dependency: its search ambiguity and outage behavior failed validation.

## Search and product lookup

| Operation | Observed contract |
| --- | --- |
| Search | `GET https://api-extern.systembolaget.se/sb-api-ecommerce/v1/productsearch/search?textQuery=…&size=10&page=1` |
| Pagination | One-based pages; `metadata.nextPage == -1` means the end. Riesling pages 1 and 2 returned different results and valid previous/next page values. |
| Individual lookup | `GET https://susbolaget.emrik.org/v1/product/{full_product_number}` |
| Store search | `GET https://api-extern.systembolaget.se/sb-api-ecommerce/v1/sitesearch/site?q=…&includePredictions=false`; results in `siteSearchResults`, identity in string `siteId` |
| Stock | `GET https://api-extern.systembolaget.se/sb-api-ecommerce/v1/stockbalance/store/{store_id}/{internal_product_id}/` |

Name/producer search and short/full article search returned HTTP 200. A name query included 375, 750 and 1500 ml packages. Short article searches also returned partial matches, including beer. Full article `512301` returned one exact package in this sample; do not assume all numeric queries are unambiguous. Rank exact matches, filter supported wine categories and require package selection.

Single-product lookup returned 200 for the full article number, and 404 for the short number and an invented nonexistent number. No bulk catalogue download was needed. A genuine discontinued product was not independently identified; not-found behavior was verified and missing metadata is covered synthetically.

Observed wine data included grape blends, null vintages, omitted/empty grape lists and different sizes. Source vintage is a suggestion for later bottle entry, never an assertion about bottles owned. A null or missing vintage alone does not distinguish unknown vintage from non-vintage. Keep internal `productId`, full `productNumber` and short `productNumberShort` as separate strings.

## Upstream authentication

The website loads JavaScript chunks containing `NEXT_PUBLIC_API_KEY_APIM`. The released client fetches the homepage, enumerates its `/_next/static/chunks/…js` scripts and extracts that value. This was reproduced successfully; 18 chunks were checked in the observed build. Search without the header returned 401.

Send `Ocp-Apim-Subscription-Key` and `Origin: https://www.systembolaget.se` from the backend. No personal Systembolaget account, login or credentials were used. The diagnostic keeps the discovered value only in memory; no headers, page scripts or keys appear in evidence or fixtures.

The released helper discovers once at startup and does not renew automatically. The Vinkoll adapter must bound discovery, cache the value privately in memory, invalidate it on 401 and attempt one rediscovery/retry. If discovery fails, report unavailable and preserve local forms/cached observations. Automatic renewal is an implementation requirement for Stage 3; a real credential rotation was not induced during validation.

## Stock identity and website comparison

Store IDs preserve leading zeroes; the public test store was `0102`, Fältöversten in Stockholm. It is a test example, not the user's configured preferred store.

Two products selected from the store-filtered wine search returned positive stock using their internal product IDs. The website's “Hitta varan i butik” panel independently showed **7** and **4**, matching the direct API and the helper when given those internal IDs. Website screenshots and live response summaries remain in ignored `test-results/`.

For those same products, the **full article number returned HTTP 200 and zero stock**. An invented product ID also returned HTTP 200/zero with the requested ID echoed back. Therefore HTTP success and echoed IDs cannot validate product identity. Resolve and retain the intended internal ID from the selected product before calling stock. Never treat an unverified article lookup as a valid zero observation.

The direct stock response includes `productId`, `storeId`, integer `stock`, nullable `shelf`, and boolean `isInStoreAssortment`. A validated zero is a reported zero observation, not an outage and not a guarantee about the vintage available.

## Released helper evaluation

Image: `ghcr.io/alexgustafsson/systembolaget-api:5.0.0`

Verified Linux/amd64 digest: `sha256:ca13ad6d54b0e4fee4a3ce1a941d42d54c15d3afd236c79d9fa0327ca85baaba`.

The source release is tagged `v5.0.0`, but the container tag is `5.0.0`; pulling the `v5.0.0` image tag returned not-found. The image includes both binaries. Its default entry point is `systembolaget`; the HTTP helper requires `--entrypoint /usr/local/bin/proxy`, listening on port 8080.

Tests used an isolated non-root, read-only container and temporary networks:

- Online startup discovered the website key and served `/readyz` and the stock route.
- Startup with `--network none` exited with status 1 before serving. The helper cannot start during an upstream outage without a previously supplied key.
- Its route searches the supplied ID using `textQuery`, requires exactly one search result, then passes that **same supplied ID** to stock. A valid internal ID for another tested wine returned 409 because that numeric search was ambiguous. Its full article number returned 200 with a misleading zero.
- During an induced upstream outage on an internal Docker network, a request exceeded the eight-second caller budget, `/readyz` still returned 200, and `/livez` returned 500.
- After reconnecting outbound networking, the same product request recovered to 200 with the correct positive count. `/livez` continued returning 500: its failure counter never resets.

These failures justify selecting direct adapters rather than depending on this image unmodified. No helper container or temporary test network remains running after validation.

## Caching, failures and usage

Observed response cache headers were approximately 1800 seconds for search, 600 for direct stock, 300 for store search and 14400 for individual lookup; cached responses may report their remaining lifetime. The helper sends `max-age=750` despite its source comment saying 15 minutes. Respect upstream cache guidance and avoid repeated checks, bulk downloads and deliberate rate-limit triggering.

Use bounded timeouts/response sizes, explicit user-triggered actions, query/product caches and request coalescing. Preserve last successful stock separately from the last attempt status. Distinguish unavailable, malformed, stale, valid zero and positive stock. Stock failures never change personal inventory. Ordinary cellar pages remain entirely local.

No explicit numeric public request quota was found in the inspected repository README files. A source repository's availability does not establish a supported API contract or data redistribution license. Record source attribution and review integration/library/data terms before release; keep fixtures synthetic.

HTTP 401, 404, 429, 500 and 503, network failure, timeout, oversized response and malformed JSON are covered by **offline diagnostic tests**. No live 429 was deliberately induced. Stage 3 must apply these behaviors to the actual cached adapter/forms; Stage 4 must verify stale-cache presentation in the stock UI.

## Repeatable checks

Run the read-only diagnostic explicitly, outside CI:

```powershell
python tools/probe_systembolaget.py
```

Optionally pass `--proxy http://127.0.0.1:PORT` for an isolated helper test. Evidence goes to ignored `test-results/stage0-live.json`. The script discovers the website key without printing or saving it, checks bounded searches/lookups and compares internal/product-number stock responses. It does not create any Vinkoll records.

The helper can be reproduced with the standalone [Compose example](../../compose.systembolaget.example.yaml): `docker compose -f compose.systembolaget.example.yaml --profile systembolaget-test up -d`. Its port is localhost-only (8004 by default). Stop it with the same file/profile and `down`. The production application has no dependency on this diagnostic service; the planned stock adapter calls the upstream directly.

Synthetic response contracts live in `tests/fixtures/systembolaget/`. Run `uv run pytest tests/test_provider_probe.py -q` for the offline checks. The tests never contact Systembolaget or Susbolaget.

Source references: [released credentials discovery](https://github.com/AlexGustafsson/systembolaget-api/blob/v5.0.0/systembolaget/credentials.go), [search](https://github.com/AlexGustafsson/systembolaget-api/blob/v5.0.0/systembolaget/search.go), [stock](https://github.com/AlexGustafsson/systembolaget-api/blob/v5.0.0/systembolaget/stock.go), [proxy](https://github.com/AlexGustafsson/systembolaget-api/blob/v5.0.0/cmd/proxy/main.go), [Susbolaget](https://github.com/C4illin/systembolaget-data).
