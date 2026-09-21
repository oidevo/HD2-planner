# Catalog importer

The importer is a maintainer tool. Ordinary profile and context commands never use the network.

It queries the Helldivers Wiki Cargo API first and then performs batched MediaWiki revision lookups. Tightly scoped manual overrides in `overrides/` fill structured-source gaps and are marked with independent provenance. It deliberately does not crawl general HTML or copy wiki prose.

After every table is imported, `normalize.py` adds deterministic cross-catalog IDs and typed values derived from structured fields. Raw values are preserved, and every derived field records its source field paths. The normalizer can also be run against an accepted snapshot for a reviewed additive migration.

Run `python hd2.py catalog fetch --output catalog-staging --catalog-version YYYY.MM.DD.N`, then `python hd2.py catalog compare catalog catalog-staging --output catalog-review`. Inspect the review before replacing the accepted snapshot.

The client identifies itself, serializes requests, retries HTTP 429 responses with backoff, and stores retrieval timestamps and revision IDs.
