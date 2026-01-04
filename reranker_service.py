# reranker_service.py
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from rerank_schemas import RerankRequest, RerankResponse
from reranker import BGEReranker


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI-3 Reranker Service", version="0.1.0")

reranker = BGEReranker()


@app.get("/health")
def health():
    return {"status": "ok", "service": "reranker", "model": "BAAI/bge-reranker-v2-m3"}


@app.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest):
    try:
        items = reranker.rerank(req.query, req.items, req.top_k)
        return RerankResponse(items=items)
    except Exception as e:
        logger.exception("Rerank failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
