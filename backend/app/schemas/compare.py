"""
ShopMate AI — Compare schemas

A side-by-side comparison of exactly two products, built from the listings' own checked facts.
"""

from typing import Optional

from pydantic import BaseModel


class CompareRequest(BaseModel):
    product_ids: list[str]  # exactly two product ids from the current results


class CompareRow(BaseModel):
    label: str  # e.g. "Price", "RAM"
    a: str  # how product A shows it ("₹1,499", "8 GB", "Not listed")
    b: str
    winner: Optional[str] = None  # "a" | "b" | "tie" | None (nothing to call, e.g. a fact is missing or neutral)


class CompareProduct(BaseModel):
    id: str
    title: str
    price: float
    url: Optional[str] = None
    imageUrl: Optional[str] = None


class CompareResponse(BaseModel):
    category: str
    a: CompareProduct
    b: CompareProduct
    rows: list[CompareRow]
    summary: list[str]  # plain sentences written by code from the rows, never by a model
    aWins: int
    bWins: int
    ties: int
    dataSource: Optional[str] = None