"""Run the polite scraper and write the records and run report."""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

from catalogue import CATALOGUE_LIMIT, discover
from extract import extract_book
from fetch import BASE_URL, DEFAULT_AGENT, HOST, FetchError, Fetcher, utc_timestamp
from records import validate_book, write_json

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BOOKS = 60
SIMULATED_MISSING_URL = f"https://{HOST}/catalogue/local-missing-fixture_0/index.html"


def run(fetcher: Fetcher, output_dir: Path, through: str = "full", simulate_missing: bool = False) -> int:
    started_at = utc_timestamp(time.time())
    started = time.monotonic()
    errors = []
    valid = []
    books = {}
    pages = discovered = detail_pages = 0
    sample_raw = None

    if through == "fetch":
        try:
            fetcher.get(BASE_URL)
            pages = 1
        except FetchError as exc:
            errors.append({"stage": "catalogue", "url": BASE_URL, "reason": str(exc)})
    else:
        books, pages, discovered = discover(fetcher, errors)
        print(f"catalogue_pages={pages} discovered={discovered} unique_urls={len(books)}")

    if through in {"extract", "full"}:
        targets = books.copy()
        if simulate_missing:
            targets[SIMULATED_MISSING_URL] = BASE_URL

        for product_url, source_page in targets.items():
            try:
                if simulate_missing and product_url == SIMULATED_MISSING_URL:
                    raise FetchError("Simulated HTTP 404 (local only)")
                html, fetched_at = fetcher.get(product_url)
                raw = extract_book(html, product_url, source_page, fetched_at)
            except (FetchError, ValueError) as exc:
                errors.append({"stage": "detail", "url": product_url, "source_page": source_page, "reason": str(exc)})
                continue

            detail_pages += 1
            if sample_raw is None:
                sample_raw = raw
            if through == "full":
                try:
                    valid.append(validate_book(raw).model_dump())
                except ValueError as exc:
                    errors.append({"stage": "validation", "url": product_url, "reason": str(exc), "record": raw})

        if sample_raw is not None:
            print(json.dumps(sample_raw, indent=2, ensure_ascii=False))
        print(f"detail_pages={detail_pages}")

    if through == "full":
        write_json(output_dir / "books.json", valid)
    write_json(output_dir / "errors.json", errors)

    report = {
        "started_at": started_at,
        "duration_seconds": round(time.monotonic() - started, 3),
        "through": through,
        "simulated_missing": simulate_missing,
        "catalogue_pages": pages,
        "discovered": discovered,
        "unique_urls": len(books),
        "detail_pages": detail_pages,
        "requests_sent": fetcher.requests_sent,
        "pages_fetched": fetcher.pages_fetched,
        "cache_hits": fetcher.cache_hits,
        "valid_records": len(valid),
        "invalid_records": sum(error["stage"] == "validation" for error in errors),
        "failed_pages": sum(error["stage"] in {"catalogue", "detail"} for error in errors),
        "discovery_errors": sum(error["stage"] in {"link", "pagination"} for error in errors),
    }
    write_json(output_dir / "run-report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    for error in errors:
        reason = error["reason"].splitlines()[0]
        print(f"SKIP {error['stage']} {error['url']}: {reason}", file=sys.stderr)

    complete = {
        "fetch": pages == 1,
        "discover": pages == CATALOGUE_LIMIT and len(books) == EXPECTED_BOOKS,
        "extract": pages == CATALOGUE_LIMIT and detail_pages == EXPECTED_BOOKS,
        "full": pages == CATALOGUE_LIMIT and len(valid) == EXPECTED_BOOKS,
    }
    return int(bool(errors) or not complete[through])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=("fetch", "discover", "extract", "full"), default="full")
    parser.add_argument("--simulate-missing", action="store_true", help="Append a locally simulated 404")
    parser.add_argument("--user-agent", default=DEFAULT_AGENT, help="Set an identifying user-agent with a contact link")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "cache")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    args = parser.parse_args()
    if args.simulate_missing and args.through != "full":
        parser.error("--simulate-missing requires the full pipeline")
    if not args.user_agent.strip():
        parser.error("--user-agent must identify the scraper")
    with requests.Session() as session:
        fetcher = Fetcher(args.cache_dir, session, args.user_agent)
        return run(fetcher, args.output_dir, args.through, args.simulate_missing)


if __name__ == "__main__":
    raise SystemExit(main())
