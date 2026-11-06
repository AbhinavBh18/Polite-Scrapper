"""Discover, extract, validate and store Books to Scrape records."""

import json
from pathlib import Path

import requests

from catalogue import discover
from extract import extract_book
from fetch import DEFAULT_AGENT, Fetcher
from records import validate_book, write_json

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    with requests.Session() as session:
        fetcher = Fetcher(ROOT / "cache", session, DEFAULT_AGENT)
        books, pages, discovered = discover(fetcher)
        print(f"catalogue_pages={pages} discovered={discovered} unique_urls={len(books)}")

        valid = []
        errors = []
        for product_url, source_page in books.items():
            html, fetched_at = fetcher.get(product_url)
            raw = extract_book(html, product_url, source_page, fetched_at)
            try:
                valid.append(validate_book(raw).model_dump())
            except ValueError as exc:
                errors.append({"reason": str(exc), "record": raw})
        if valid:
            print(json.dumps(valid[0], indent=2, ensure_ascii=False))
        print(f"detail_pages={len(books)} valid_records={len(valid)}")
        write_json(ROOT / "output" / "books.json", valid)
        write_json(ROOT / "output" / "errors.json", errors)
