"""Discover book detail URLs from catalogue pages."""

from urllib.parse import urljoin, urlsplit

from fetch import BASE_URL, PRODUCT_PATH, FetchError, Fetcher, cache_key

CATALOGUE_LIMIT = 3


def catalogue_links(html: bytes) -> tuple[list[str], str | None]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser", from_encoding="utf-8")
    books = [str(link["href"]) for link in soup.select("article.product_pod h3 a[href]")]
    if not books:
        raise ValueError("Catalogue page has no book links")
    next_link = soup.select_one("li.next a[href]")
    return books, str(next_link["href"]) if next_link else None


def resolve_link(page_url: str, href: str) -> str:
    # The fragment changes where a browser scrolls, not the page requested.
    return urlsplit(urljoin(page_url, href))._replace(fragment="").geturl()


def discover(fetcher: Fetcher, errors: list[dict]) -> tuple[dict[str, str], int, int]:
    books = {}
    discovered = 0
    catalogue_pages = 0
    page_url = BASE_URL

    for number in range(1, CATALOGUE_LIMIT + 1):
        try:
            html, _ = fetcher.get(page_url)
            links, next_link = catalogue_links(html)
        except (FetchError, ValueError) as exc:
            errors.append({"stage": "catalogue", "url": page_url, "reason": str(exc)})
            break

        catalogue_pages += 1
        discovered += len(links)
        for href in links:
            try:
                product_url = resolve_link(page_url, href)
                cache_key(product_url)
                if not PRODUCT_PATH.fullmatch(urlsplit(product_url).path):
                    raise ValueError("Expected a book detail link")
            except ValueError as exc:
                errors.append({"stage": "link", "url": href, "source_page": page_url, "reason": str(exc)})
                continue
            books.setdefault(product_url, page_url)

        if number == CATALOGUE_LIMIT:
            break

        try:
            if not next_link:
                raise ValueError("Missing next catalogue link")
            next_url = resolve_link(page_url, next_link)
            cache_key(next_url)
            if urlsplit(next_url).path != f"/catalogue/page-{number + 1}.html":
                raise ValueError(f"Unexpected next catalogue page: {next_url}")
        except ValueError as exc:
            errors.append({"stage": "pagination", "url": page_url, "reason": str(exc)})
            break
        page_url = next_url

    return books, catalogue_pages, discovered
