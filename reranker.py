# reranker.py
"""
Cross-encoder reranker op AI-3.

Model: BAAI/bge-reranker-v2-m3 (multilingual, goed voor NL/EN).

Gebruikt GPU manager voor slimme GPU selectie en cleanup.
"""

from __future__ import annotations

import logging
import os
import gc
from typing import List

import torch
from sentence_transformers import CrossEncoder

from rerank_schemas import RerankItem, RerankedItem

from gpu_phase_lock import gpu_exclusive_lock

# GPU Manager voor slimme GPU selectie
try:
    from gpu_manager import gpu_manager, get_pytorch_device, GPUTask, TaskType
    GPU_MANAGER_AVAILABLE = True
except ImportError:
    GPU_MANAGER_AVAILABLE = False


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class RerankerSettings:
    def __init__(self) -> None:
        self.MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        # Device wordt dynamisch gekozen bij model-load (voorkomt OOM als GPU0 vol zit)
        self.DEVICE = os.getenv("RERANK_DEVICE", "cuda")
        self.MIN_FREE_MB = int(os.getenv("RERANK_MIN_FREE_MB", "2500"))


settings = RerankerSettings()


def cleanup_gpu_memory():
    """Maak GPU geheugen vrij na reranking."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


class BGEReranker:
    def __init__(self) -> None:
        # Belangrijk voor 70B-first: niet bij startup al een groot torch model resident maken.
        self._device = settings.DEVICE
        self.model: CrossEncoder | None = None
        self._auto_unload = os.getenv("AUTO_UNLOAD_RERANKER", "true").lower() == "true"

    def _ensure_model(self):
        if self.model is not None:
            return
        # Kies GPU pas vlak voor load; in multi-service setups kan GPU0 bezet zijn.
        device = settings.DEVICE
        if GPU_MANAGER_AVAILABLE:
            device = get_pytorch_device(prefer_gpu=True, min_free_mb=settings.MIN_FREE_MB)
        self._device = device
        logger.info("Loading reranker model %s on %s", settings.MODEL_NAME, device)
        self.model = CrossEncoder(settings.MODEL_NAME, device=device)

    def rerank(self, query: str, items: List[RerankItem], top_k: int = 10) -> List[RerankedItem]:
        if not items:
            return []

        pairs = [(query, it.text) for it in items]
        
        # Global GPU lock: 1 GPU job tegelijk
        with gpu_exclusive_lock("rerank", doc_id=f"rerank_{len(items)}", timeout_sec=900):
            self._ensure_model()
            # Gebruik GPU task context als beschikbaar
            if GPU_MANAGER_AVAILABLE:
                with GPUTask(TaskType.PYTORCH_RERANKING, doc_id=f"rerank_{len(items)}_items"):
                    scores = self.model.predict(pairs)  # type: ignore[union-attr]
            else:
                scores = self.model.predict(pairs)  # type: ignore[union-attr]
                # Cleanup na reranking
                cleanup_gpu_memory()

            # 70B-first stabiliteit: maak reranker zo snel mogelijk vrij
            if self._auto_unload:
                self.unload()

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
    
    def get_device(self) -> str:
        """Return het device waarop de reranker draait."""
        return self._device

    def unload(self):
        """Unload reranker model (vrijgeven VRAM)."""
        if self.model is None:
            return
        try:
            del self.model
        except Exception:
            pass
        self.model = None
        cleanup_gpu_memory()
        if GPU_MANAGER_AVAILABLE:
            try:
                gpu_manager.cleanup_pytorch()
            except Exception:
                pass
