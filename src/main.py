"""Entry point for the Books to Scrape assignment."""

import json
from pathlib import Path

import requests

from catalogue import discover
from extract import extract_book
from fetch import DEFAULT_AGENT, Fetcher

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    with requests.Session() as session:
        fetcher = Fetcher(ROOT / 'cache', session, DEFAULT_AGENT)
        books, pages, discovered = discover(fetcher)
        print(f"catalogue_pages={pages} discovered={discovered} unique_urls={len(books)}")
        records = []
        for product_url, source_page in books.items():
            html, fetched_at = fetcher.get(product_url)
            records.append(extract_book(html, product_url, source_page, fetched_at))
        if records:
            print(json.dumps(records[0], indent=2, ensure_ascii=False))
        print(f"detail_pages={len(records)}")
