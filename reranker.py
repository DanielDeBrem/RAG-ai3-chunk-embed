# reranker.py
"""
Cross-encoder reranker op AI-3.

Model: BAAI/bge-reranker-v2-m3 (multilingual, goed voor NL/EN).
"""

from __future__ import annotations

import logging
import os
from typing import List

from sentence_transformers import CrossEncoder

from rerank_schemas import RerankItem, RerankedItem


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class RerankerSettings:
    def __init__(self) -> None:
        self.MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        # 'cuda' dwingt GPU; val terug op 'cpu' als je wilt testen
        self.DEVICE = os.getenv("RERANK_DEVICE", "cuda")


settings = RerankerSettings()


class BGEReranker:
    def __init__(self) -> None:
        logger.info("Loading reranker model %s on %s", settings.MODEL_NAME, settings.DEVICE)
        self.model = CrossEncoder(settings.MODEL_NAME, device=settings.DEVICE)

    def rerank(self, query: str, items: List[RerankItem], top_k: int = 10) -> List[RerankedItem]:
        if not items:
            return []

        pairs = [(query, it.text) for it in items]
        scores = self.model.predict(pairs)

        scored = []
        for it, score in zip(items, scores):
            scored.append(
                RerankedItem(
                    id=it.id,
                    text=it.text,
                    score=float(score),
                    metadata=it.metadata,
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)

        if top_k and top_k > 0:
            scored = scored[:top_k]

        return scored
