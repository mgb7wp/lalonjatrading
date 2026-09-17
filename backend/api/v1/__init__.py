"""Router de la version 1 de la API."""

from __future__ import annotations

from fastapi import APIRouter

from . import auth, health, markets, rankings, screener, stocks

router = APIRouter()
router.include_router(auth.router)
router.include_router(health.router)
router.include_router(markets.router)
router.include_router(rankings.router)
router.include_router(screener.router)
router.include_router(stocks.router)
