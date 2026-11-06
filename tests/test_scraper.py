"""Network-free checks for the assignment checkpoints."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catalogue import catalogue_links, resolve_link
from extract import extract_book
from fetch import BASE_URL, DEFAULT_AGENT, HOST, TIMEOUT, FetchError, Fetcher
from main import run
from records import normalize_price

ORIGIN = f"https://{HOST}"
BOOK_HTML = """
<div class="price_color">£99.00</div>
<article class="product_page">
  <div class="product_main">
    <h1> Sample   <em>Book</em> </h1>
    <p class="price_color"> £12.34 </p>
    <p class="instock availability"> In stock
      (4 available)
    </p>
    <p class="star-rating Three"></p>
  </div>
</article>
"""


def response(status, content=b"test HTML"):
    return Mock(status_code=status, content=content)


def synthetic_site():
    session = Mock()

    def get(url, **kwargs):
        return response(200, urlsplit(url).path.encode())

    def links(body):
        page = int(body.decode().split("-")[-1].split(".")[0])
        return [f"test-book_{number}/index.html" for number in range(page * 20 - 19, page * 20 + 1)], f"page-{page + 1}.html"

    def extract(body, product_url, source_page, fetched_at):
        return {
            "title": body.decode().split("/")[-2].replace("test-book_", "Fixture Book "),
            "product_url": product_url,
            "price_text": "£12.34",
            "availability_text": "In stock (4 available)",
            "rating_text": "Three",
            "description": None,
            "source_page": source_page,
            "fetched_at": fetched_at,
        }

    session.get.side_effect = get
    return session, links, extract


class FetchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)
        self.session = Mock()
        self.fetcher = Fetcher(self.cache, self.session, DEFAULT_AGENT)

    def test_cache_keeps_html_and_original_timestamp(self):
        self.session.get.return_value = response(200)
        first = self.fetcher.get(BASE_URL)
        self.assertEqual(self.fetcher.get(BASE_URL), first)
        self.assertEqual(self.cache.joinpath("catalogue-page-1.html").read_bytes(), b"test HTML")
        self.session.get.assert_called_once_with(
            BASE_URL, headers={"User-Agent": DEFAULT_AGENT}, timeout=TIMEOUT, allow_redirects=False
        )

    def test_timeout_and_server_errors_retry_once_with_delay(self):
        for failed_attempt in (requests.Timeout(), response(503)):
            with self.subTest(failed_attempt=failed_attempt), tempfile.TemporaryDirectory() as temp:
                session = Mock()
                session.get.side_effect = [failed_attempt, response(200)]
                fetcher = Fetcher(Path(temp), session, DEFAULT_AGENT)
                with patch("fetch.time.monotonic", return_value=5), patch("fetch.time.sleep") as sleep:
                    fetcher.get(BASE_URL)
                sleep.assert_called_once_with(0.5)
                self.assertEqual(fetcher.requests_sent, 2)
                self.assertEqual(fetcher.pages_fetched, 1)

    def test_forbidden_and_missing_pages_are_not_retried_or_cached(self):
        for status in (403, 404):
            with self.subTest(status=status):
                self.session.reset_mock()
                self.session.get.return_value = response(status)
                with self.assertRaisesRegex(FetchError, f"HTTP {status}"):
                    self.fetcher.get(BASE_URL)
                self.session.get.assert_called_once()
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_repeated_server_error_stops_after_second_attempt(self):
        self.session.get.return_value = response(503)
        with patch("fetch.time.sleep"), self.assertRaisesRegex(FetchError, "HTTP 503"):
            self.fetcher.get(BASE_URL)
        self.assertEqual(self.session.get.call_count, 2)

    def test_off_site_url_is_rejected_before_request(self):
        with self.assertRaises(FetchError):
            self.fetcher.get("https://example.com/catalogue/book_1/index.html")
        self.session.get.assert_not_called()


class ParserTests(unittest.TestCase):
    def test_price(self):
        self.assertEqual(normalize_price("£51.77"), 51.77)
        for malformed in ("$51.77", "£51", "£-51.77", None):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                normalize_price(malformed)

    def test_resolve_relative_links_and_remove_fragments(self):
        self.assertEqual(
            resolve_link(f"{ORIGIN}/catalogue/page-2.html", "./test-book_1/index.html#top"),
            f"{ORIGIN}/catalogue/test-book_1/index.html",
        )

    @unittest.skipUnless(importlib.util.find_spec("bs4"), "Beautiful Soup must be installed")
    def test_catalogue_selectors(self):
        html = b"""
        <article class="product_pod"><h3><a href="one_1/index.html">One</a></h3></article>
        <li class="next"><a href="page-2.html">next</a></li>
        """
        self.assertEqual(catalogue_links(html), (["one_1/index.html"], "page-2.html"))

    @unittest.skipUnless(importlib.util.find_spec("bs4"), "Beautiful Soup must be installed")
    def test_missing_description_and_whitespace(self):
        raw = extract_book(BOOK_HTML.encode(), f"{ORIGIN}/catalogue/test_1/index.html", BASE_URL, "2026-11-06T00:00:00Z")
        self.assertEqual(len(raw), 8)
        self.assertEqual(raw["title"], "Sample Book")
        self.assertEqual(raw["price_text"], "£12.34")
        self.assertEqual(raw["availability_text"], "In stock (4 available)")
        self.assertEqual(raw["rating_text"], "Three")
        self.assertIsNone(raw["description"])

    @unittest.skipUnless(importlib.util.find_spec("bs4"), "Beautiful Soup must be installed")
    def test_malformed_detail_page(self):
        with self.assertRaisesRegex(ValueError, "Missing product article"):
            extract_book(b"<h1>Something went wrong</h1>", "", "", "")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name) / "cache"
        self.output = Path(temp.name) / "output"

    def read(self, name):
        return json.loads((self.output / name).read_text(encoding="utf-8"))

    def run_fixture(self, session, links, extract, **kwargs):
        with (
            patch("catalogue.catalogue_links", links),
            patch("main.extract_book", extract),
            patch("fetch.time.sleep"),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return run(Fetcher(self.cache, session, DEFAULT_AGENT), self.output, **kwargs)

    def test_full_run_cache_rerun_and_local_404(self):
        session, links, extract = synthetic_site()
        self.assertEqual(self.run_fixture(session, links, extract), 0)
        self.assertEqual(session.get.call_count, 63)
        report = self.read("run-report.json")
        self.assertEqual((report["catalogue_pages"], report["discovered"], report["unique_urls"]), (3, 60, 60))
        self.assertEqual((report["valid_records"], report["invalid_records"], report["failed_pages"]), (60, 0, 0))
        first = self.read("books.json")
        self.assertEqual(len({book["product_url"] for book in first}), 60)

        session.get.reset_mock()
        self.assertEqual(self.run_fixture(session, links, extract), 0)
        self.assertEqual(self.read("books.json"), first)
        self.assertEqual(self.read("run-report.json")["cache_hits"], 63)

        self.assertEqual(self.run_fixture(session, links, extract, simulate_missing=True), 1)
        self.assertEqual(self.read("books.json"), first)
        self.assertEqual(self.read("run-report.json")["failed_pages"], 1)
        self.assertIn("Simulated HTTP 404", self.read("errors.json")[0]["reason"])
        session.get.assert_not_called()

    def test_duplicates_are_removed_and_invalid_record_is_quarantined(self):
        session, links, extract = synthetic_site()

        def with_duplicate(body):
            urls, next_url = links(body)
            return [*urls, urls[0] + "#duplicate"], next_url

        def with_bad_price(body, *metadata):
            raw = extract(body, *metadata)
            if raw["title"] == "Fixture Book 1":
                raw["price_text"] = "$12.34"
            return raw

        self.assertEqual(self.run_fixture(session, with_duplicate, with_bad_price), 1)
        report = self.read("run-report.json")
        self.assertEqual((report["discovered"], report["unique_urls"]), (63, 60))
        self.assertEqual((report["valid_records"], report["invalid_records"], report["failed_pages"]), (59, 1, 0))
        self.assertEqual(self.read("errors.json")[0]["record"]["price_text"], "$12.34")

    def test_catalogue_failure_keeps_records_from_previous_pages(self):
        session, links, extract = synthetic_site()
        original_get = session.get.side_effect
        session.get.side_effect = lambda url, **kwargs: (
            response(404) if url.endswith("/page-2.html") else original_get(url, **kwargs)
        )

        self.assertEqual(self.run_fixture(session, links, extract), 1)
        self.assertEqual(len(self.read("books.json")), 20)
        self.assertEqual(self.read("run-report.json")["failed_pages"], 1)


if __name__ == "__main__":
    unittest.main()
