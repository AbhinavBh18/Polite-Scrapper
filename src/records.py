"""Normalize scraped data and validate the final JSON record."""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fetch import HOST, write_atomic

PRICE_PATTERN = re.compile(r"£([0-9]+\.[0-9]{2})")
ORIGIN = re.escape(f"https://{HOST}")


class Book(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

    title: str = Field(min_length=1)
    product_url: str = Field(pattern=rf"^{ORIGIN}/catalogue/[a-zA-Z0-9_-]+_[0-9]+/index\.html$")
    price_text: str = Field(min_length=1)
    availability_text: str = Field(min_length=1)
    rating_text: Literal["One", "Two", "Three", "Four", "Five"]
    description: str | None = Field(default=None, min_length=1)
    source_page: str = Field(pattern=rf"^{ORIGIN}/catalogue/page-[1-3]\.html$")
    fetched_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    price_gbp: float = Field(ge=0)


def normalize_price(price_text: str | None) -> float:
    price = PRICE_PATTERN.fullmatch(price_text or "")
    if price is None:
        raise ValueError("Expected a GBP price such as £51.77")
    return float(price[1])


def validate_book(raw: dict) -> Book:
    return Book.model_validate({**raw, "price_gbp": normalize_price(raw["price_text"])})


def write_json(path: Path, value: object) -> None:
    body = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
    write_atomic(path, (body + "\n").encode("utf-8"))
