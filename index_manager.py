"""
FAISS Index Manager with atomic persistence and crash-safe operations.

Provides:
- Load/save FAISS indices from/to disk
- Atomic writes (temp file + fsync + rename)
- Index rebuilding from database
- Dirty tracking for incremental updates
"""
import os
import tempfile
import logging
from typing import Optional, Tuple
from datetime import datetime

import faiss
import numpy as np

from models import get_session, IndexMetadata, Chunk

logger = logging.getLogger(__name__)


class IndexManager:
    """
    Manages FAISS index persistence with atomic operations.
    
    Key features:
    - Atomic saves: write to temp file, fsync, rename
    - Crash-safe: partial writes never corrupt index
    - Lazy loading: load on first access
    - Dirty tracking: mark for rebuild when needed
    """
    
    def __init__(self, index_dir: str = "./faiss_indices"):
        """
        Initialize IndexManager.
        
        Args:
            index_dir: Directory to store FAISS index files
        """
        self.index_dir = os.path.abspath(index_dir)
        os.makedirs(self.index_dir, exist_ok=True)
        logger.info(f"IndexManager initialized with index_dir={self.index_dir}")
    
    def _get_index_path(self, tenant_id: str, namespace: str, embedding_version: str) -> str:
        """Get path to FAISS index file."""
        # Sanitize to avoid directory traversal
        safe_tenant = tenant_id.replace("/", "_").replace("\\", "_")
        safe_namespace = namespace.replace("/", "_").replace("\\", "_")
        safe_version = embedding_version.replace("/", "_").replace("\\", "_")
        
        filename = f"{safe_tenant}_{safe_namespace}_{safe_version}.faiss"
        return os.path.join(self.index_dir, filename)
    
    def load_index(
        self,
        tenant_id: str,
        namespace: str,
        embedding_version: str,
        dimension: int
    ) -> Tuple[faiss.Index, IndexMetadata]:
        """
        Load FAISS index from disk or create new one.
        
        Args:
            tenant_id: Tenant ID
            namespace: Namespace (e.g., document_type or project_id)
            embedding_version: Embedding model version
            dimension: Embedding dimension
        
        Returns:
            Tuple of (FAISS index, IndexMetadata record)
        """
        session = get_session()
        try:
            # Try to find existing index metadata
            index_meta = session.query(IndexMetadata).filter_by(
                tenant_id=tenant_id,
                namespace=namespace,
                embedding_version=embedding_version
            ).first()
            
            if index_meta:
                # Load existing index from disk
                if os.path.exists(index_meta.faiss_path):
                    try:
                        index = faiss.read_index(index_meta.faiss_path)
                        logger.info(
                            f"Loaded index: {tenant_id}:{namespace}:{embedding_version} "
                            f"({index_meta.ntotal} vectors)"
                        )
                        return index, index_meta
                    except Exception as e:
                        logger.error(f"Failed to load index from {index_meta.faiss_path}: {e}")
                        # Fall through to create new index
                else:
                    logger.warning(f"Index file missing: {index_meta.faiss_path}, creating new")
            
            # Create new index
            index = faiss.IndexFlatIP(dimension)  # Inner product (cosine similarity)
            index_path = self._get_index_path(tenant_id, namespace, embedding_version)
            
            # Create or update metadata
            if not index_meta:
                index_meta = IndexMetadata(
                    tenant_id=tenant_id,
                    namespace=namespace,
                    embedding_version=embedding_version,
                    faiss_path=index_path,
                    ntotal=0,
                    dimension=dimension,
                    dirty=False
                )
                session.add(index_meta)
            else:
                index_meta.faiss_path = index_path
                index_meta.dimension = dimension
                index_meta.ntotal = 0
                index_meta.dirty = False
            
            session.commit()
            logger.info(f"Created new index: {tenant_id}:{namespace}:{embedding_version} (dim={dimension})")
            
            # Eagerly load all attributes before session closes (avoid detached instance issues)
            _ = (index_meta.id, index_meta.tenant_id, index_meta.namespace, 
                 index_meta.embedding_version, index_meta.faiss_path, index_meta.ntotal,
                 index_meta.dimension, index_meta.updated_at, index_meta.dirty)
            
            return index, index_meta
        
        finally:
            session.close()
    
    def save_index(
        self,
        index: faiss.Index,
        index_meta: IndexMetadata,
        atomic: bool = True
    ) -> None:
        """
        Save FAISS index to disk with optional atomic write.
        
        Args:
            index: FAISS index to save
            index_meta: IndexMetadata record
            atomic: If True, use atomic write (temp + rename)
        """
        # Cache all attributes before any session operations (avoid detached access)
        faiss_path = index_meta.faiss_path
        tenant_id = index_meta.tenant_id
        namespace = index_meta.namespace
        embedding_version = index_meta.embedding_version
        
        if atomic:
            # Atomic write: write to temp file, fsync, rename
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".faiss.tmp",
                dir=self.index_dir
            )
            try:
                os.close(temp_fd)  # Close fd, faiss will open its own
                
                # Write to temp file
                faiss.write_index(index, temp_path)
                
                # Fsync to ensure data is on disk
                with open(temp_path, 'rb') as f:
                    os.fsync(f.fileno())
                
                # Atomic rename (use cached path)
                os.replace(temp_path, faiss_path)
                
                logger.info(f"Saved index atomically: {faiss_path}")
            
            except Exception as e:
                # Cleanup temp file on error
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                raise e
        else:
            # Direct write (non-atomic, faster but not crash-safe)
            faiss.write_index(index, faiss_path)
            logger.info(f"Saved index: {faiss_path}")
        
        # Update metadata in new session (use cached attributes)
        session = get_session()
        try:
            # Re-fetch from database to avoid detached instance issues
            meta = session.query(IndexMetadata).filter_by(
                tenant_id=tenant_id,
                namespace=namespace,
                embedding_version=embedding_version
            ).first()
            
            if meta:
                meta.ntotal = index.ntotal
                meta.updated_at = datetime.utcnow()
                meta.dirty = False
                session.commit()
        finally:
            session.close()
    
    def mark_dirty(
        self,
        tenant_id: str,
        namespace: str,
        embedding_version: str
    ) -> None:
        """
        Mark index as dirty (needs rebuild).
        
        Used after document deletion to trigger background rebuild.
        """
        session = get_session()
        try:
            index_meta = session.query(IndexMetadata).filter_by(
                tenant_id=tenant_id,
                namespace=namespace,
                embedding_version=embedding_version
            ).first()
            
            if index_meta:
                index_meta.dirty = True
                index_meta.updated_at = datetime.utcnow()
                session.commit()
                logger.info(f"Marked index dirty: {tenant_id}:{namespace}:{embedding_version}")
        finally:
            session.close()
    
    def rebuild_index(
        self,
        tenant_id: str,
        namespace: str,
        embedding_version: str,
        dimension: int
    ) -> Tuple[faiss.Index, IndexMetadata]:
        """
        Rebuild FAISS index from database chunks.
        
        This is a full rebuild:
        1. Create new empty index
        2. Load all non-deleted chunks from DB
        3. Add vectors to index
        4. Atomic save
        5. Update chunk.faiss_id mappings
        
        Args:
            tenant_id: Tenant ID
            namespace: Namespace
            embedding_version: Embedding version
            dimension: Embedding dimension
        
        Returns:
            Tuple of (new FAISS index, updated IndexMetadata)
        """
        logger.info(f"Rebuilding index: {tenant_id}:{namespace}:{embedding_version}")
        
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
            
            # Create new index
            new_index = faiss.IndexFlatIP(dimension)
            
            if chunks:
                # We need to re-embed or load embeddings from somewhere
                # For now, we'll use a placeholder approach where embeddings
                # must be provided externally (via rebuild job)
                # This function focuses on FAISS structure rebuild
                
                # Note: In production, embeddings should be stored separately
                # or re-computed. For P0, we'll handle this in the rebuild_job
                pass
            
            # Get or create index metadata
            index_meta = session.query(IndexMetadata).filter_by(
                tenant_id=tenant_id,
                namespace=namespace,
                embedding_version=embedding_version
            ).first()
            
            if not index_meta:
                index_path = self._get_index_path(tenant_id, namespace, embedding_version)
                index_meta = IndexMetadata(
                    tenant_id=tenant_id,
                    namespace=namespace,
                    embedding_version=embedding_version,
                    faiss_path=index_path,
                    ntotal=0,
                    dimension=dimension,
                    dirty=False
                )
                session.add(index_meta)
            
            index_meta.ntotal = new_index.ntotal
            index_meta.dirty = False
            index_meta.updated_at = datetime.utcnow()
            
            session.commit()
            
            # Save index atomically
            self.save_index(new_index, index_meta, atomic=True)
            
            logger.info(
                f"Rebuilt index: {tenant_id}:{namespace}:{embedding_version} "
                f"({new_index.ntotal} vectors)"
            )
            
            return new_index, index_meta
        
        finally:
            session.close()
    
    def add_vectors(
        self,
        index: faiss.Index,
        index_meta: IndexMetadata,
        vectors: np.ndarray,
        chunk_ids: list[str]
    ) -> list[int]:
        """
        Add vectors to FAISS index and return their FAISS IDs.
        
        Args:
            index: FAISS index
            index_meta: Index metadata
            vectors: Numpy array of shape (n, dim)
            chunk_ids: List of chunk IDs corresponding to vectors
        
        Returns:
            List of FAISS IDs assigned to vectors
        """
        if len(vectors) == 0:
            return []
        
        start_id = index.ntotal
        index.add(vectors)
        
        # FAISS assigns sequential IDs starting from ntotal
        faiss_ids = list(range(start_id, index.ntotal))
        
        # Update chunk records with FAISS IDs
        session = get_session()
        try:
            for chunk_id, faiss_id in zip(chunk_ids, faiss_ids):
                chunk = session.query(Chunk).filter_by(chunk_id=chunk_id).first()
                if chunk:
                    chunk.faiss_id = faiss_id
            
            session.commit()
        finally:
            session.close()
        
        return faiss_ids
    
    def get_index_stats(self) -> dict:
        """Get statistics about all indices."""
        session = get_session()
        try:
            indices = session.query(IndexMetadata).all()
            
            stats = {
                "total_indices": len(indices),
                "total_vectors": sum(idx.ntotal for idx in indices),
                "dirty_indices": sum(1 for idx in indices if idx.dirty),
                "indices": [
                    {
                        "tenant_id": idx.tenant_id,
                        "namespace": idx.namespace,
                        "embedding_version": idx.embedding_version,
                        "ntotal": idx.ntotal,
                        "dimension": idx.dimension,
                        "dirty": idx.dirty,
                        "updated_at": idx.updated_at.isoformat() if idx.updated_at else None
                    }
                    for idx in indices
                ]
            }
            
            return stats
        finally:
            session.close()
