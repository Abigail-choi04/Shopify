"""
ShopMate AI — Compare router

POST /compare  {"product_ids": ["flipkart-A", "flipkart-B"]}  ->  a side-by-side comparison of two products.
Errors come back as {"detail": {"code": ..., "message": ...}} like the mandate endpoints.
"""

from fastapi import APIRouter, HTTPException

from app.schemas.compare import CompareRequest, CompareResponse
from app.services import compare

router = APIRouter(prefix="/compare", tags=["compare"])


@router.post("", response_model=CompareResponse)
async def compare_two(request: CompareRequest):
    try:
        return await compare.compare_products(request.product_ids)
    except compare.CompareError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})