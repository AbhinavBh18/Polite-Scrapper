"""Cache-first HTTP access to the Books to Scrape sandbox."""

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

import requests

HOST = "books.toscrape.com"
BASE_URL = f"https://{HOST}/catalogue/page-1.html"
DEFAULT_AGENT = "FlyRankInternship-A9/1.0 (Abhinav Bhardwaj)"
REQUEST_GAP = 0.5
TIMEOUT = 8
CATALOGUE_PATH = re.compile(r"/catalogue/(page-[1-3])\.html")
PRODUCT_PATH = re.compile(r"/catalogue/([a-zA-Z0-9_-]+_\d+)/index\.html")


class FetchError(Exception):
    """The URL could not be fetched or safely loaded from cache."""


class RetryableFetchError(FetchError):
    """A timeout or server failure that can be retried once."""


def utc_timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cache_key(url: str) -> Path:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != HOST or parsed.query or parsed.fragment:
        raise ValueError("Expected a canonical HTTPS URL on Books to Scrape")

    catalogue = CATALOGUE_PATH.fullmatch(parsed.path)
    if catalogue:
        return Path(f"catalogue-{catalogue[1]}.html")

    product = PRODUCT_PATH.fullmatch(parsed.path)
    if product:
        return Path("books") / f"{product[1]}.html"

    raise ValueError("URL is outside the three catalogue pages and book detail pages")


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = NamedTemporaryFile(dir=path.parent, delete=False)
    temp_path = Path(temp.name)
    try:
        with temp:
            temp.write(data)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


class Fetcher:
    def __init__(self, cache_dir: Path, session: requests.Session, user_agent: str):
        self.cache_dir = cache_dir
        self.session = session
        self.user_agent = user_agent
        self.cache_hits = 0
        self.pages_fetched = 0
        self.requests_sent = 0
        self.last_request_finished = None

    def get(self, url: str) -> tuple[bytes, str]:
        try:
            path = self.cache_dir / cache_key(url)
            if path.is_file():
                html = path.read_bytes()
                self.cache_hits += 1
                print(f"CACHE HIT {len(html)} bytes {url}")
            else:
                try:
                    html = self._download(url)
                except RetryableFetchError as exc:
                    print(f"RETRY {url}: {exc}")
                    html = self._download(url)
                write_atomic(path, html)
            return html, utc_timestamp(path.stat().st_mtime)
        except (OSError, ValueError) as exc:
            raise FetchError(str(exc)) from exc

    def _download(self, url: str) -> bytes:
        if self.last_request_finished is not None:
            time.sleep(max(0, REQUEST_GAP - (time.monotonic() - self.last_request_finished)))
        self.requests_sent += 1
        try:
            response = self.session.get(
                url, headers={"User-Agent": self.user_agent}, timeout=TIMEOUT, allow_redirects=False
            )
        except requests.Timeout as exc:
            raise RetryableFetchError(f"Timeout after {TIMEOUT} seconds") from exc
        except requests.RequestException as exc:
            raise FetchError(str(exc)) from exc
        finally:
            self.last_request_finished = time.monotonic()

        if 500 <= response.status_code <= 599:
            raise RetryableFetchError(f"HTTP {response.status_code}")
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code}")

        self.pages_fetched += 1
        print(f"FETCH 200 {len(response.content)} bytes {url}")
        return response.content
