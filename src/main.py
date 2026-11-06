"""Entry point for the Books to Scrape assignment."""

from pathlib import Path

import requests

from catalogue import discover
from fetch import DEFAULT_AGENT, Fetcher

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    with requests.Session() as session:
        books, pages, discovered = discover(Fetcher(ROOT / "cache", session, DEFAULT_AGENT))
        print(f"catalogue_pages={pages} discovered={discovered} unique_urls={len(books)}")
