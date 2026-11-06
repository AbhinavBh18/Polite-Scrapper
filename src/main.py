"""Entry point for the Books to Scrape assignment."""

from pathlib import Path

import requests

from fetch import BASE_URL, DEFAULT_AGENT, Fetcher

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    with requests.Session() as session:
        Fetcher(ROOT / "cache", session, DEFAULT_AGENT).get(BASE_URL)
