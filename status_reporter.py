"""
Status Reporter - Stuurt webhooks naar AI-4 bij status changes.

Rapporteert de voortgang van document processing naar AI-4 zodat
de admin UI real-time updates kan tonen.
"""

from __future__ import annotations

import os
import logging
import asyncio
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

import httpx
import threading

logger = logging.getLogger(__name__)


class ProcessingStage(Enum):
    """Verwerkingsfases voor document processing."""
    RECEIVED = "received"           # Document ontvangen
    QUEUED = "queued"              # In queue voor verwerking
    ANALYZING = "analyzing"         # LLM document analyse
    CHUNKING = "chunking"          # Tekst in chunks splitsen
    ENRICHING = "enriching"        # LLM context enrichment per chunk
    EMBEDDING = "embedding"         # Embeddings genereren
    STORING = "storing"            # Opslaan in vector store
    RERANKING = "reranking"        # Reranking van resultaten
    SEARCHING = "searching"        # Vector search
    COMPLETED = "completed"        # Verwerking afgerond
    FAILED = "failed"              # Verwerking gefaald


@dataclass
class StatusUpdate:
    """Status update payload."""
    doc_id: str
    stage: ProcessingStage
    progress_pct: Optional[int] = None
    message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "ai3"


# Configuration
AI4_WEBHOOK_URL = os.getenv(
    "AI4_WEBHOOK_URL",
    "http://10.0.1.227:5001/api/webhook/ai3-status"
)
AI4_WEBHOOK_SECRET = os.getenv("AI4_WEBHOOK_SECRET", "")
WEBHOOK_TIMEOUT = float(os.getenv("WEBHOOK_TIMEOUT", "5.0"))
WEBHOOK_ENABLED = os.getenv("WEBHOOK_ENABLED", "true").lower() == "true"

# In productie wil je dat webhooks nooit je ingest/search blokkeren.
# Als true: fire-and-forget via background thread.
WEBHOOK_FIRE_AND_FORGET = os.getenv("WEBHOOK_FIRE_AND_FORGET", "true").lower() == "true"

# Hergebruik één client voor connection pooling (scheelt latency).
_async_client: httpx.AsyncClient | None = None


def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient()
    return _async_client

# Track recent updates voor deduplicatie
_recent_updates: Dict[str, StatusUpdate] = {}


async def send_status_async(update: StatusUpdate) -> bool:
    """
    Stuur status update naar AI-4 via webhook (async).
    
    Args:
        update: StatusUpdate object
    
    Returns:
        True als webhook succesvol verzonden
    """
    if not WEBHOOK_ENABLED:
        logger.debug(f"[StatusReporter] Webhook disabled, skipping: {update.stage.value}")
        return True
    
    payload = {
        "source": update.source,
        "timestamp": update.timestamp,
        "doc_id": update.doc_id,
        "stage": update.stage.value,
        "progress_pct": update.progress_pct,
        "message": update.message,
        "metadata": update.metadata,
        "error": update.error,
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Source": "ai3-pipeline",
    }
    if AI4_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = AI4_WEBHOOK_SECRET
    
    try:
        client = _get_async_client()
        resp = await client.post(
            AI4_WEBHOOK_URL,
            json=payload,
            headers=headers,
            timeout=WEBHOOK_TIMEOUT,
        )

        if resp.status_code == 200:
            logger.debug(f"[StatusReporter] Webhook sent: {update.stage.value} for {update.doc_id}")
            return True
        else:
            logger.warning(
                f"[StatusReporter] Webhook failed: {resp.status_code} - {resp.text[:100]}"
            )
            return False
                
    except httpx.ConnectError:
        logger.warning(f"[StatusReporter] Cannot connect to AI-4 at {AI4_WEBHOOK_URL}")
        return False
    except httpx.TimeoutException:
        logger.warning(f"[StatusReporter] Webhook timeout to AI-4")
        return False
    except Exception as e:
        logger.warning(f"[StatusReporter] Webhook error: {e}")
        return False


def send_status_sync(update: StatusUpdate) -> bool:
    """
    Stuur status update naar AI-4 via webhook (sync).
    
    Non-blocking: als er al een event loop draait, schedule als task.
    """
    if not WEBHOOK_ENABLED:
        return True
    
    # In sync routes willen we niet blokkeren op webhooks.
    # In async context schedule we een task; anders gebruiken we (optioneel) een background thread.
    try:
        asyncio.get_running_loop()
        asyncio.create_task(send_status_async(update))
        return True
    except RuntimeError:
        if WEBHOOK_FIRE_AND_FORGET:
            def _runner():
                try:
                    asyncio.run(send_status_async(update))
                except Exception:
                    # silent: status updates mogen nooit de pipeline breken
                    pass

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            return True

        # Blocking fallback (debug)
        try:
            return asyncio.run(send_status_async(update))
        except Exception as e:
            logger.warning(f"[StatusReporter] Sync webhook failed: {e}")
            return False


def report_status(
    doc_id: str,
    stage: ProcessingStage,
    progress_pct: Optional[int] = None,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> bool:
    """
    Hoofdfunctie om status te rapporteren.
    
    Args:
        doc_id: Document ID
        stage: Verwerkingsfase
        progress_pct: Percentage compleet (0-100)
        message: Optioneel status bericht
        metadata: Extra metadata (chunks_count, model_used, etc.)
        error: Error message bij FAILED stage
    
    Returns:
        True als webhook verzonden (of disabled)
    
    Voorbeeld:
        report_status("doc123", ProcessingStage.EMBEDDING, 
                     progress_pct=50, 
                     message="Embedding 75/150 chunks")
    """
    update = StatusUpdate(
        doc_id=doc_id,
        stage=stage,
        progress_pct=progress_pct,
        message=message,
        metadata=metadata or {},
        error=error,
    )
    
    # Log lokaal ook
    if stage == ProcessingStage.FAILED:
        logger.error(f"[Status] {doc_id}: {stage.value} - {error}")
    else:
        logger.info(f"[Status] {doc_id}: {stage.value} ({progress_pct}%) - {message}")
    
    # Update recent cache
    _recent_updates[doc_id] = update
    
    return send_status_sync(update)


def get_recent_status(doc_id: str) -> Optional[StatusUpdate]:
    """Haal meest recente status op voor een document."""
    return _recent_updates.get(doc_id)


def clear_status(doc_id: str):
    """Verwijder status voor een document uit cache."""
    if doc_id in _recent_updates:
        del _recent_updates[doc_id]


# Convenience functies per stage
def report_received(doc_id: str, filename: str = None, size_bytes: int = None):
    """Rapporteer dat document ontvangen is."""
    meta = {}
    if filename:
        meta["filename"] = filename
    if size_bytes:
        meta["size_bytes"] = size_bytes
    return report_status(doc_id, ProcessingStage.RECEIVED, 
                        progress_pct=0, 
                        message=f"Document received: {filename or doc_id}",
                        metadata=meta)


def report_analyzing(doc_id: str, model: str = "llama3.1:70b"):
    """Rapporteer dat analyse gestart is."""
    return report_status(doc_id, ProcessingStage.ANALYZING,
                        progress_pct=10,
                        message=f"Analyzing document with {model}",
                        metadata={"model": model})


def report_chunking(doc_id: str, strategy: str = None):
    """Rapporteer dat chunking gestart is."""
    return report_status(doc_id, ProcessingStage.CHUNKING,
                        progress_pct=25,
                        message=f"Chunking with strategy: {strategy or 'auto'}",
                        metadata={"chunk_strategy": strategy})


def report_enriching(doc_id: str, chunks_count: int, current: int = 0):
    """Rapporteer context enrichment voortgang."""
    pct = 30 + int((current / max(chunks_count, 1)) * 20)  # 30-50%
    return report_status(doc_id, ProcessingStage.ENRICHING,
                        progress_pct=pct,
                        message=f"Enriching chunk {current}/{chunks_count}",
                        metadata={"chunks_total": chunks_count, "chunks_done": current})


def report_embedding(doc_id: str, chunks_count: int, current: int = 0, model: str = "BAAI/bge-m3"):
    """Rapporteer embedding voortgang."""
    pct = 50 + int((current / max(chunks_count, 1)) * 30)  # 50-80%
    return report_status(doc_id, ProcessingStage.EMBEDDING,
                        progress_pct=pct,
                        message=f"Embedding chunk {current}/{chunks_count}",
                        metadata={"chunks_total": chunks_count, "chunks_done": current, "model": model})


def report_storing(doc_id: str, chunks_count: int):
    """Rapporteer opslaan in vector store."""
    return report_status(doc_id, ProcessingStage.STORING,
                        progress_pct=85,
                        message=f"Storing {chunks_count} chunks in vector database",
                        metadata={"chunks_count": chunks_count})


def report_completed(doc_id: str, chunks_stored: int = 0, duration_sec: float = None):
    """Rapporteer succesvolle afronding."""
    meta = {"chunks_stored": chunks_stored}
    if duration_sec:
        meta["duration_sec"] = round(duration_sec, 2)
    return report_status(doc_id, ProcessingStage.COMPLETED,
                        progress_pct=100,
                        message=f"Completed: {chunks_stored} chunks stored",
                        metadata=meta)


def report_failed(doc_id: str, error: str, stage: str = None):
    """Rapporteer fout."""
    return report_status(doc_id, ProcessingStage.FAILED,
                        progress_pct=None,
                        message=f"Failed at {stage or 'unknown'}: {error[:100]}",
                        error=error)


def report_searching(doc_id: str, query: str = None):
    """Rapporteer dat search gestart is."""
    return report_status(doc_id, ProcessingStage.SEARCHING,
                        message="Searching vector database",
                        metadata={"query_preview": (query or "")[:50]})


def report_reranking(doc_id: str, candidates: int, top_k: int):
    """Rapporteer reranking."""
    return report_status(doc_id, ProcessingStage.RERANKING,
                        message=f"Reranking {candidates} candidates to top {top_k}",
                        metadata={"candidates": candidates, "top_k": top_k})


class StatusReporter:
    """
    Context manager voor automatische status reporting.
    
    Gebruik:
        with StatusReporter("doc123") as reporter:
            reporter.analyzing()
            # doe analyse
            reporter.chunking(strategy="semantic")
            # doe chunking
    """
    
    def __init__(self, doc_id: str, filename: str = None):
        self.doc_id = doc_id
        self.filename = filename
        self.start_time = None
        self._chunks_count = 0
    
    def __enter__(self):
        self.start_time = datetime.utcnow()
        report_received(self.doc_id, filename=self.filename)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else None
        
        if exc_type is not None:
            # Er was een exception
            report_failed(self.doc_id, str(exc_val), stage="processing")
            return False  # Don't suppress exception
        
        # Geen exception, maar completed moeten we expliciet aanroepen
        return False
    
    def analyzing(self, model: str = "llama3.1:70b"):
        report_analyzing(self.doc_id, model)
    
    def chunking(self, strategy: str = None):
        report_chunking(self.doc_id, strategy)
    
    def enriching(self, total: int, current: int = 0):
        self._chunks_count = total
        report_enriching(self.doc_id, total, current)
    
    def embedding(self, total: int = None, current: int = 0, model: str = "BAAI/bge-m3"):
        if total:
            self._chunks_count = total
        report_embedding(self.doc_id, self._chunks_count, current, model)
    
    def storing(self, chunks_count: int = None):
        report_storing(self.doc_id, chunks_count or self._chunks_count)
    
    def completed(self, chunks_stored: int = None):
        duration = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else None
        report_completed(self.doc_id, chunks_stored or self._chunks_count, duration)
    
    def failed(self, error: str, stage: str = None):
        report_failed(self.doc_id, error, stage)


# Test functie
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Status Reporter Test ===")
    print(f"Webhook URL: {AI4_WEBHOOK_URL}")
    print(f"Webhook Enabled: {WEBHOOK_ENABLED}")
    
    # Test met context manager
    print("\n--- Testing StatusReporter context manager ---")
    with StatusReporter("test_doc_001", filename="test.pdf") as reporter:
        print("Testing analyzing...")
        reporter.analyzing()
        
        print("Testing chunking...")
        reporter.chunking(strategy="semantic_sections")
        
        print("Testing enriching...")
        reporter.enriching(total=10, current=5)
        
        print("Testing embedding...")
        reporter.embedding(current=8)
        
        print("Testing storing...")
        reporter.storing()
        
        print("Testing completed...")
        reporter.completed(chunks_stored=10)
    
    print("\n--- Test complete ---")
    print(f"Recent status: {get_recent_status('test_doc_001')}")
