"""Extract the eight raw fields from a book's detail page."""

RATINGS = {"One", "Two", "Three", "Four", "Five"}


def clean_text(element) -> str | None:
    if element is None:
        return None
    return " ".join(element.get_text(" ", strip=True).split()) or None


def extract_book(html: bytes, product_url: str, source_page: str, fetched_at: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser", from_encoding="utf-8")
    product = soup.select_one("article.product_page")
    if product is None:
        raise ValueError("Missing product article")
    main = product.select_one(".product_main")
    if main is None:
        raise ValueError("Missing product details")

    rating = main.select_one(".star-rating")
    rating_classes = rating.get("class", []) if rating else []
    rating_values = [value for value in rating_classes if value in RATINGS]
    return {
        "title": clean_text(main.select_one("h1")),
        "product_url": product_url,
        "price_text": clean_text(main.select_one(".price_color")),
        "availability_text": clean_text(main.select_one(".availability")),
        "rating_text": rating_values[0] if len(rating_values) == 1 else None,
        "description": clean_text(product.select_one("#product_description + p")),
        "source_page": source_page,
        "fetched_at": fetched_at,
    }
