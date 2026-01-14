"""
AI-3 DataFactory v1 - Persistent RAG Ingest/Index Service

P0 Production Features:
- Persistent storage (SQLite + FAISS on disk)
- Idempotent upserts (doc_id deduplication)
- Document deletion with rebuild
- Atomic FAISS index swapping
- Persistent job queue
- Crash-safe operations
"""
import os
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Import existing functionality
from app import (
    embed_texts, chunk_text_with_strategy, extract_text_from_file,
    classify_document_type, _normalize_text_for_hash, _chunk_hash,
    EMBED_MODEL_NAME, CONTEXT_ENABLED
)

# Import new persistent components
from models import init_db, get_session, Document, Chunk, IndexMetadata
from index_manager import IndexManager
from job_queue import job_queue, register_job_handler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Environment configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ai3_rag.db")
INDEX_DIR = os.getenv("INDEX_DIR", "./faiss_indices")
EMBEDDING_VERSION = os.getenv("EMBEDDING_VERSION", EMBED_MODEL_NAME)

# Initialize components
app = FastAPI(title="AI-3 DataFactory v1", version="1.0.0")
index_manager = IndexManager(index_dir=INDEX_DIR)


# ============================================
# Schemas for v1 API
# ============================================

class DocUpsertRequest(BaseModel):
    """Request to upsert a document."""
    tenant_id: str
    namespace: str  # e.g., project_id or document_type
    doc_id: str
    source: Optional[str] = None
    text: str
    metadata: Optional[Dict[str, Any]] = None
    policy_id: Optional[str] = None
    chunk_strategy: Optional[str] = None
    chunk_overlap: int = 0
    enrich_context: bool = True


class DocUpsertResponse(BaseModel):
    """Response from document upsert."""
    accepted: int
    upserted_docs: int
    skipped_docs: int
    chunks_created: int
    job_id: Optional[str] = None


class DocsUpsertRequest(BaseModel):
    """Request to upsert multiple documents."""
    docs: List[DocUpsertRequest]
    async_mode: bool = False  # If True, return job_id immediately


class DocDeleteResponse(BaseModel):
    """Response from document deletion."""
    deleted: bool
    doc_id: str
    chunks_deleted: int
    job_id: Optional[str] = None


class IndexRebuildRequest(BaseModel):
    """Request to rebuild index."""
    tenant_id: str
    namespace: str
    embedding_version: Optional[str] = None
    reembed: bool = False
    new_embedding_version: Optional[str] = None


class IndexRebuildResponse(BaseModel):
    """Response from rebuild request."""
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    type: str
    status: str
    progress: int
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    ok: bool
    db_ok: bool
    index_store_ok: bool
    jobqueue_ok: bool
    build_info: Dict[str, Any]


# ============================================
# Helper Functions
# ============================================

def compute_doc_hash(text: str) -> str:
    """Compute SHA256 hash of document content."""
    normalized = _normalize_text_for_hash(text)
    return hashlib.sha256(normalized.encode('utf-8', errors='ignore')).hexdigest()


def upsert_document_sync(req: DocUpsertRequest) -> Dict[str, Any]:
    """
    Synchronously upsert a document.
    
    Returns dict with stats: chunks_created, was_update
    """
    session = get_session()
    try:
        doc_hash = compute_doc_hash(req.text)
        
        # Check if document exists
        existing_doc = session.query(Document).filter_by(doc_id=req.doc_id).first()
        
        was_update = False
        if existing_doc:
            # Check if content changed
            if existing_doc.doc_hash == doc_hash and existing_doc.deleted_at is None:
                # Identical content, skip
                logger.info(f"Document {req.doc_id} unchanged, skipping")
                return {'chunks_created': 0, 'was_update': False, 'skipped': True}
            
            # Content changed or was deleted, mark old chunks as deleted
            if existing_doc.deleted_at is None:
                for chunk in existing_doc.chunks:
                    chunk.deleted_at = datetime.utcnow()
                
                # Mark index dirty for rebuild
                index_manager.mark_dirty(
                    req.tenant_id,
                    req.namespace,
                    existing_doc.embedding_version
                )
            
            # Update document
            existing_doc.doc_hash = doc_hash
            existing_doc.tenant_id = req.tenant_id
            existing_doc.namespace = req.namespace
            existing_doc.source = req.source
            existing_doc.embedding_model_id = EMBED_MODEL_NAME
            existing_doc.embedding_version = EMBEDDING_VERSION
            existing_doc.policy_id = req.policy_id
            existing_doc.updated_at = datetime.utcnow()
            existing_doc.deleted_at = None  # Undelete if was deleted
            existing_doc.set_metadata(req.metadata or {})
            
            doc = existing_doc
            was_update = True
        else:
            # Create new document
            doc = Document(
                doc_id=req.doc_id,
                tenant_id=req.tenant_id,
                namespace=req.namespace,
                source=req.source,
                doc_hash=doc_hash,
                embedding_model_id=EMBED_MODEL_NAME,
                embedding_version=EMBEDDING_VERSION,
                policy_id=req.policy_id
            )
            doc.set_metadata(req.metadata or {})
            session.add(doc)
        
        session.flush()
        
        # Chunk text
        chunks_text = chunk_text_with_strategy(
            text=req.text,
            strategy=req.chunk_strategy,
            document_type=req.namespace,
            overlap=req.chunk_overlap
        )
        
        if not chunks_text:
            session.commit()
            return {'chunks_created': 0, 'was_update': was_update, 'skipped': False}
        
        # Apply enrichment if enabled
        if req.enrich_context and CONTEXT_ENABLED:
            # Import here to avoid circular dependency
            from contextual_enricher import enrich_chunks_batch
            
            doc_metadata = {
                "filename": (req.metadata or {}).get("filename", req.doc_id),
                "document_type": req.namespace,
            }
            
            embed_texts_list = enrich_chunks_batch(chunks_text, doc_metadata)
        else:
            embed_texts_list = chunks_text
        
        # Embed chunks
        embeddings = embed_texts(embed_texts_list)
        dim = embeddings.shape[1]
        
        # Load or create index
        index, index_meta = index_manager.load_index(
            tenant_id=req.tenant_id,
            namespace=req.namespace,
            embedding_version=EMBEDDING_VERSION,
            dimension=dim
        )
        
        # Create chunk records
        chunk_ids = []
        for i, (raw_text, embed_text) in enumerate(zip(chunks_text, embed_texts_list)):
            chunk_hash = _chunk_hash(raw_text)
            chunk_id = f"{req.doc_id}#c{i:04d}"
            
            chunk = Chunk(
                chunk_id=chunk_id,
                doc_id=req.doc_id,
                tenant_id=req.tenant_id,
                namespace=req.namespace,
                chunk_hash=chunk_hash,
                text=raw_text,
                embed_text=embed_text if embed_text != raw_text else None,
                meta_json=None,
                policy_id=req.policy_id,
                embedding_model_id=EMBED_MODEL_NAME,
                embedding_version=EMBEDDING_VERSION,
            )
            session.add(chunk)
            chunk_ids.append(chunk_id)
        
        session.flush()
        
        # Add vectors to FAISS and update faiss_id
        faiss_ids = index_manager.add_vectors(index, index_meta, embeddings, chunk_ids)
        
        # Save index atomically
        index_manager.save_index(index, index_meta, atomic=True)
        
        session.commit()
        
        logger.info(
            f"Upserted doc {req.doc_id}: {len(chunks_text)} chunks, "
            f"{'update' if was_update else 'new'}"
        )
        
        return {
            'chunks_created': len(chunks_text),
            'was_update': was_update,
            'skipped': False
        }
    
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to upsert document {req.doc_id}: {e}", exc_info=True)
        raise
    
    finally:
        session.close()


# ============================================
# Job Handlers
# ============================================

@register_job_handler('ingest_docs')
def handle_ingest_docs(job_id: str, payload: Dict[str, Any]):
    """Handle batch document ingestion job."""
    docs = payload.get('docs', [])
    
    total = len(docs)
    for i, doc_data in enumerate(docs):
        try:
            req = DocUpsertRequest(**doc_data)
            upsert_document_sync(req)
            
            # Update progress
            progress = int((i + 1) / total * 100)
            job_queue.update_job_status(job_id, 'running', progress=progress)
        
        except Exception as e:
            logger.error(f"Failed to ingest doc in job {job_id}: {e}", exc_info=True)
            # Continue with next doc


@register_job_handler('rebuild_index')
def handle_rebuild_index(job_id: str, payload: Dict[str, Any]):
    """Handle index rebuild job."""
    tenant_id = payload['tenant_id']
    namespace = payload['namespace']
    embedding_version = payload.get('embedding_version', EMBEDDING_VERSION)
    reembed = payload.get('reembed', False)
    new_embedding_version = payload.get('new_embedding_version')
    
    logger.info(
        f"Rebuilding index: {tenant_id}:{namespace}:{embedding_version} "
        f"(reembed={reembed})"
    )
    
    job_queue.update_job_status(job_id, 'running', progress=10)
    
    session = get_session()
    try:
        # Load all non-deleted chunks
        chunks = session.query(Chunk).filter_by(
            tenant_id=tenant_id,
            namespace=namespace,
            embedding_version=embedding_version,
            deleted_at=None
        ).all()
        
        logger.info(f"Found {len(chunks)} chunks to rebuild")
        job_queue.update_job_status(job_id, 'running', progress=20)
        
        if not chunks:
            # Empty index
            index_manager.rebuild_index(
                tenant_id, namespace, embedding_version, 1024
            )
            return
        
        # Determine dimension from first chunk or reembed
        if reembed:
            # Re-embed all chunks
            texts = [c.text for c in chunks]
            embeddings = embed_texts(texts)
            dim = embeddings.shape[1]
            
            # Update embedding version if provided
            target_version = new_embedding_version or EMBEDDING_VERSION
            
            for chunk, emb in zip(chunks, embeddings):
                chunk.embedding_version = target_version
                chunk.embedding_model_id = EMBED_MODEL_NAME
        else:
            # Use existing embeddings (need to reload from somewhere)
            # For P0, we assume embeddings can be recomputed
            texts = [c.embed_text or c.text for c in chunks]
            embeddings = embed_texts(texts)
            dim = embeddings.shape[1]
            target_version = embedding_version
        
        job_queue.update_job_status(job_id, 'running', progress=60)
        
        # Create new index
        import faiss
        new_index = faiss.IndexFlatIP(dim)
        new_index.add(embeddings)
        
        # Get or create index metadata
        index_meta = session.query(IndexMetadata).filter_by(
            tenant_id=tenant_id,
            namespace=namespace,
            embedding_version=target_version
        ).first()
        
        if not index_meta:
            index_path = index_manager._get_index_path(
                tenant_id, namespace, target_version
            )
            index_meta = IndexMetadata(
                tenant_id=tenant_id,
                namespace=namespace,
                embedding_version=target_version,
                faiss_path=index_path,
                ntotal=0,
                dimension=dim,
                dirty=False
            )
            session.add(index_meta)
        
        # Update chunk faiss_ids
        for i, chunk in enumerate(chunks):
            chunk.faiss_id = i
        
        session.commit()
        
        job_queue.update_job_status(job_id, 'running', progress=80)
        
        # Save index atomically
        index_manager.save_index(new_index, index_meta, atomic=True)
        
        logger.info(
            f"Rebuilt index {tenant_id}:{namespace}:{target_version}: "
            f"{new_index.ntotal} vectors"
        )
    
    finally:
        session.close()


# ============================================
# v1 API Endpoints
# ============================================

@app.post("/v1/docs/upsert", response_model=DocUpsertResponse)
def v1_docs_upsert_single(req: DocUpsertRequest):
    """
    Upsert a single document (synchronous).
    
    Idempotent: same doc_id with same content = skip, different content = update
    """
    try:
        result = upsert_document_sync(req)
        
        return DocUpsertResponse(
            accepted=1,
            upserted_docs=0 if result['skipped'] else 1,
            skipped_docs=1 if result['skipped'] else 0,
            chunks_created=result['chunks_created'],
            job_id=None
        )
    
    except Exception as e:
        logger.error(f"Upsert failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/docs/upsert/batch", response_model=DocUpsertResponse)
def v1_docs_upsert_batch(req: DocsUpsertRequest):
    """
    Upsert multiple documents.
    
    If async_mode=True, returns job_id immediately.
    Otherwise processes synchronously.
    """
    if req.async_mode:
        # Create job
        job_id = job_queue.create_job(
            job_type='ingest_docs',
            payload={'docs': [doc.dict() for doc in req.docs]}
        )
        
        return DocUpsertResponse(
            accepted=len(req.docs),
            upserted_docs=0,
            skipped_docs=0,
            chunks_created=0,
            job_id=job_id
        )
    else:
        # Process synchronously
        total_chunks = 0
        upserted = 0
        skipped = 0
        
        for doc in req.docs:
            try:
                result = upsert_document_sync(doc)
                total_chunks += result['chunks_created']
                if result['skipped']:
                    skipped += 1
                else:
                    upserted += 1
            except Exception as e:
                logger.error(f"Failed to upsert {doc.doc_id}: {e}")
        
        return DocUpsertResponse(
            accepted=len(req.docs),
            upserted_docs=upserted,
            skipped_docs=skipped,
            chunks_created=total_chunks,
            job_id=None
        )


@app.delete("/v1/docs/{doc_id}", response_model=DocDeleteResponse)
def v1_docs_delete(doc_id: str, tenant_id: str, namespace: str):
    """
    Delete a document (soft delete).
    
    Marks document and chunks as deleted, triggers async rebuild.
    """
    session = get_session()
    try:
        doc = session.query(Document).filter_by(doc_id=doc_id).first()
        
        if not doc or doc.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Soft delete document and chunks
        doc.deleted_at = datetime.utcnow()
        chunks_deleted = 0
        
        for chunk in doc.chunks:
            if chunk.deleted_at is None:
                chunk.deleted_at = datetime.utcnow()
                chunks_deleted += 1
        
        session.commit()
        
        # Mark index dirty
        index_manager.mark_dirty(doc.tenant_id, doc.namespace, doc.embedding_version)
        
        # Create rebuild job
        job_id = job_queue.create_job(
            job_type='rebuild_index',
            payload={
                'tenant_id': doc.tenant_id,
                'namespace': doc.namespace,
                'embedding_version': doc.embedding_version,
                'reembed': False
            }
        )
        
        logger.info(f"Deleted doc {doc_id}: {chunks_deleted} chunks, rebuild job {job_id}")
        
        return DocDeleteResponse(
            deleted=True,
            doc_id=doc_id,
            chunks_deleted=chunks_deleted,
            job_id=job_id
        )
    
    finally:
        session.close()


@app.post("/v1/index/rebuild", response_model=IndexRebuildResponse)
def v1_index_rebuild(req: IndexRebuildRequest):
    """
    Trigger index rebuild.
    
    Returns job_id for async processing.
    """
    job_id = job_queue.create_job(
        job_type='rebuild_index',
        payload={
            'tenant_id': req.tenant_id,
            'namespace': req.namespace,
            'embedding_version': req.embedding_version or EMBEDDING_VERSION,
            'reembed': req.reembed,
            'new_embedding_version': req.new_embedding_version
        }
    )
    
    return IndexRebuildResponse(
        job_id=job_id,
        status='pending'
    )


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
def v1_jobs_status(job_id: str):
    """Get job status."""
    job = job_queue.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatusResponse(**job)


@app.get("/v1/health", response_model=HealthResponse)
def v1_health():
    """Health check."""
    db_ok = False
    index_store_ok = False
    jobqueue_ok = False
    
    # Check database
    try:
        session = get_session()
        session.execute("SELECT 1")
        session.close()
        db_ok = True
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
    
    # Check index directory
    try:
        os.makedirs(INDEX_DIR, exist_ok=True)
        test_file = os.path.join(INDEX_DIR, ".health_check")
        with open(test_file, 'w') as f:
            f.write("ok")
        os.unlink(test_file)
        index_store_ok = True
    except Exception as e:
        logger.error(f"Index store health check failed: {e}")
    
    # Check job queue
    try:
        stats = job_queue.get_queue_stats()
        jobqueue_ok = True
    except Exception as e:
        logger.error(f"Job queue health check failed: {e}")
    
    ok = db_ok and index_store_ok and jobqueue_ok
    
    return HealthResponse(
        ok=ok,
        db_ok=db_ok,
        index_store_ok=index_store_ok,
        jobqueue_ok=jobqueue_ok,
        build_info={
            'version': '1.0.0',
            'embedding_model': EMBED_MODEL_NAME,
            'embedding_version': EMBEDDING_VERSION,
            'database_url': DATABASE_URL,
            'index_dir': INDEX_DIR,
        }
    )


@app.get("/v1/index/stats")
def v1_index_stats():
    """Get index statistics."""
    return index_manager.get_index_stats()


@app.get("/v1/queue/stats")
def v1_queue_stats():
    """Get job queue statistics."""
    return job_queue.get_queue_stats()


# ============================================
# Retrieval with Deleted Chunk Filtering
# ============================================

class SearchRequest(BaseModel):
    """Search request."""
    tenant_id: str
    namespace: str
    query: str
    top_k: int = 5
    embedding_version: Optional[str] = None


class ChunkResult(BaseModel):
    """Search result chunk."""
    doc_id: str
    chunk_id: str
    text: str
    score: float
    metadata: Dict[str, Any] = {}


class SearchResponse(BaseModel):
    """Search response."""
    chunks: List[ChunkResult]
    total_found: int


@app.post("/v1/search", response_model=SearchResponse)
def v1_search(req: SearchRequest):
    """
    Search with deleted chunk filtering.
    
    Flow:
    1. Embed query
    2. FAISS vector search
    3. Map FAISS IDs to chunk_ids
    4. Filter out deleted chunks from DB
    5. Return top_k results
    """
    embedding_version = req.embedding_version or EMBEDDING_VERSION
    
    # Load index
    try:
        index, index_meta = index_manager.load_index(
            tenant_id=req.tenant_id,
            namespace=req.namespace,
            embedding_version=embedding_version,
            dimension=1024  # Will be determined from existing index
        )
    except Exception as e:
        logger.error(f"Failed to load index: {e}")
        raise HTTPException(status_code=404, detail="Index not found")
    
    if index.ntotal == 0:
        return SearchResponse(chunks=[], total_found=0)
    
    # Embed query
    query_emb = embed_texts([req.query])
    
    # FAISS search - fetch more candidates to account for deleted chunks
    search_k = min(req.top_k * 3, index.ntotal)
    scores, faiss_ids = index.search(query_emb, search_k)
    
    # Map FAISS IDs to chunks and filter deleted
    session = get_session()
    try:
        results = []
        for score, faiss_id in zip(scores[0], faiss_ids[0]):
            if faiss_id == -1:  # FAISS returns -1 for no result
                continue
            
            # Find chunk by faiss_id
            chunk = session.query(Chunk).filter_by(
                tenant_id=req.tenant_id,
                namespace=req.namespace,
                embedding_version=embedding_version,
                faiss_id=int(faiss_id),
                deleted_at=None  # CRITICAL: Filter deleted chunks
            ).first()
            
            if chunk:
                results.append(ChunkResult(
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    score=float(score),
                    metadata=chunk.get_metadata()
                ))
            
            if len(results) >= req.top_k:
                break
        
        return SearchResponse(
            chunks=results,
            total_found=len(results)
        )
    
    finally:
        session.close()


# ============================================
# Startup
# ============================================

@app.on_event("startup")
def on_startup():
    """Initialize database and components."""
    logger.info("Starting AI-3 DataFactory v1...")
    
    # Initialize database (skip if already initialized by tests)
    from models import engine as existing_engine
    if existing_engine is None:
        init_db(DATABASE_URL)
        logger.info(f"Database initialized: {DATABASE_URL}")
    else:
        logger.info(f"Database already initialized (test mode)")
    
    # Ensure index directory exists
    os.makedirs(INDEX_DIR, exist_ok=True)
    logger.info(f"Index directory: {INDEX_DIR}")
    
    logger.info("AI-3 DataFactory v1 ready")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
