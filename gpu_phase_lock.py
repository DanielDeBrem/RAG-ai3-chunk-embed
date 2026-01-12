"""
gpu_phase_lock.py - Dummy/No-op version

NOTA: Deze module is verwijderd tijdens cleanup (zie app.py regel 30-31).
De functionaliteit is vervangen door eenvoudigere GPU management.

Deze file bestaat alleen om import errors te voorkomen in legacy code
die nog steeds probeert te importeren.

Voor nieuwe code: GEBRUIK DIT NIET. Gebruik gpu_manager.py in plaats daarvan.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


@contextmanager
def gpu_exclusive_lock(
    phase: str,
    doc_id: Optional[str] = None,
    timeout_sec: int = 900,
    lock_path: Optional[str] = None,
):
    """
    Dummy GPU lock - doet niets (no-op).
    
    Deze functie bestaat alleen voor backwards compatibility.
    De echte locking is verwijderd omdat app.py nu single-GPU gebruikt
    met CUDA_VISIBLE_DEVICES per service.
    
    Args:
        phase: Fase naam (bijv. "embedding", "rerank")
        doc_id: Document ID
        timeout_sec: Timeout (genegeerd)
        lock_path: Lock file path (genegeerd)
    
    Yields:
        None
    """
    # Log warning eerste keer
    if not hasattr(gpu_exclusive_lock, '_warned'):
        logger.warning(
            "[gpu_phase_lock] DEPRECATED: This is a no-op dummy function. "
            "Real GPU management is handled by gpu_manager.py and CUDA_VISIBLE_DEVICES. "
            "Consider removing this import."
        )
        gpu_exclusive_lock._warned = True  # type: ignore
    
    # Yield without doing anything - no actual locking
    yield


class GPUExclusiveLock:
    """Dummy class for backwards compatibility."""
    
    def __init__(self, *args, **kwargs):
        pass
    
    def acquire(self) -> bool:
        return True
    
    def release(self):
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
