"""
Hybrid Search Module - Dense (FAISS) + Sparse (BM25) Retrieval

Combineert vector similarity search met keyword matching voor betere retrieval.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import List, Dict, Tuple, Optional
from rank_bm25 import BM25Okapi
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Single search result with combined score."""
    chunk_id: str
    text: str
    dense_score: float
    sparse_score: float
    combined_score: float
    metadata: Dict


class HybridRetriever:
    """
    Hybrid retriever combining dense (FAISS) and sparse (BM25) search.
    
    Dense search is good for semantic similarity.
    Sparse search is good for exact keyword matches (names, codes, etc.).
    
    Combination using Reciprocal Rank Fusion (RRF).
    """
    
    def __init__(
        self,
        dense_weight: float = 0.7,
        sparse_weight: float = 0.3,
        rrf_k: int = 60
    ):
        """
        Initialize hybrid retriever.
        
        Args:
            dense_weight: Weight for dense scores (0.0-1.0)
            sparse_weight: Weight for sparse scores (0.0-1.0)
            rrf_k: RRF parameter (higher = less emphasis on top ranks)
        """
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.rrf_k = rrf_k
        
        # BM25 index
        self.bm25: Optional[BM25Okapi] = None
        self.chunk_ids: List[str] = []
        self.chunk_texts: List[str] = []
        self.chunk_metadata: List[Dict] = []
        
        logger.info(
            f"[HybridSearch] Initialized (dense={dense_weight}, sparse={sparse_weight}, rrf_k={rrf_k})"
        )
    
    def index_chunks(self, chunks: List[Dict]):
        """
        Index chunks for BM25 sparse search.
        
        Args:
            chunks: List of chunk dicts with keys: chunk_id, text, metadata
        """
        if not chunks:
            logger.warning("[HybridSearch] No chunks to index")
            return
        
        self.chunk_ids = [c["chunk_id"] for c in chunks]
        self.chunk_texts = [c["text"] for c in chunks]
        self.chunk_metadata = [c.get("metadata", {}) for c in chunks]
        
        # Tokenize for BM25 (simple whitespace + lowercase)
        tokenized = [text.lower().split() for text in self.chunk_texts]
        self.bm25 = BM25Okapi(tokenized)
        
        logger.info(f"[HybridSearch] Indexed {len(chunks)} chunks for BM25")
    
    def search(
        self,
        query: str,
        dense_results: List[Tuple[str, float]],  # [(chunk_id, score), ...]
        top_k: int = 50
    ) -> List[SearchResult]:
        """
        Hybrid search combining dense and sparse results.
        
        Args:
            query: Search query
            dense_results: Results from FAISS dense search [(chunk_id, score), ...]
            top_k: Number of results to return
        
        Returns:
            List of SearchResult objects sorted by combined score
        """
        if self.bm25 is None:
            logger.warning("[HybridSearch] BM25 not indexed, returning dense results only")
            return self._dense_only_results(dense_results, top_k)
        
        # Sparse search with BM25
        query_tokens = query.lower().split()
        bm25_scores = self.bm25.get_scores(query_tokens)
        
        # Get top sparse results
        sparse_indices = np.argsort(bm25_scores)[-top_k*2:][::-1]  # Get more for fusion
        sparse_results = [
            (self.chunk_ids[idx], float(bm25_scores[idx]))
            for idx in sparse_indices
            if bm25_scores[idx] > 0  # Filter out zero scores
        ]
        
        logger.info(
            f"[HybridSearch] Dense: {len(dense_results)} results, "
            f"Sparse: {len(sparse_results)} results"
        )
        
        # Combine using Reciprocal Rank Fusion
        combined = self._reciprocal_rank_fusion(dense_results, sparse_results)
        
        # Get full chunk data
        chunk_id_to_idx = {cid: idx for idx, cid in enumerate(self.chunk_ids)}
        results = []
        
        for chunk_id, combined_score, dense_score, sparse_score in combined[:top_k]:
            idx = chunk_id_to_idx.get(chunk_id)
            if idx is not None:
                results.append(SearchResult(
                    chunk_id=chunk_id,
                    text=self.chunk_texts[idx],
                    dense_score=dense_score,
                    sparse_score=sparse_score,
                    combined_score=combined_score,
                    metadata=self.chunk_metadata[idx]
                ))
        
        logger.info(f"[HybridSearch] Returned {len(results)} hybrid results")
        return results
    
    def _reciprocal_rank_fusion(
        self,
        dense_results: List[Tuple[str, float]],
        sparse_results: List[Tuple[str, float]]
    ) -> List[Tuple[str, float, float, float]]:
        """
        Combine dense and sparse results using Reciprocal Rank Fusion.
        
        RRF formula: score(d) = sum(1 / (k + rank(d)))
        
        Returns:
            List of (chunk_id, combined_score, dense_score, sparse_score)
        """
        scores = {}
        dense_dict = {cid: score for cid, score in dense_results}
        sparse_dict = {cid: score for cid, score in sparse_results}
        
        # All unique chunk IDs
        all_ids = set(dense_dict.keys()) | set(sparse_dict.keys())
        
        for chunk_id in all_ids:
            # Dense contribution
            dense_rank = next(
                (rank for rank, (cid, _) in enumerate(dense_results) if cid == chunk_id),
                len(dense_results)  # Not found = worst rank
            )
            dense_rrf = self.dense_weight / (self.rrf_k + dense_rank + 1)
            
            # Sparse contribution
            sparse_rank = next(
                (rank for rank, (cid, _) in enumerate(sparse_results) if cid == chunk_id),
                len(sparse_results)  # Not found = worst rank
            )
            sparse_rrf = self.sparse_weight / (self.rrf_k + sparse_rank + 1)
            
            # Combined score
            combined = dense_rrf + sparse_rrf
            
            scores[chunk_id] = (
                combined,
                dense_dict.get(chunk_id, 0.0),
                sparse_dict.get(chunk_id, 0.0)
            )
        
        # Sort by combined score
        sorted_results = sorted(
            [(cid, comb, dense, sparse) for cid, (comb, dense, sparse) in scores.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        return sorted_results
    
    def _dense_only_results(
        self,
        dense_results: List[Tuple[str, float]],
        top_k: int
    ) -> List[SearchResult]:
        """Fallback to dense-only results if BM25 not available."""
        chunk_id_to_idx = {cid: idx for idx, cid in enumerate(self.chunk_ids)}
        results = []
        
        for chunk_id, score in dense_results[:top_k]:
            idx = chunk_id_to_idx.get(chunk_id)
            if idx is not None:
                results.append(SearchResult(
                    chunk_id=chunk_id,
                    text=self.chunk_texts[idx],
                    dense_score=score,
                    sparse_score=0.0,
                    combined_score=score,
                    metadata=self.chunk_metadata[idx]
                ))
        
        return results


# Module test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Hybrid Search Test ===")
    
    # Mock chunks
    chunks = [
        {"chunk_id": "doc1#c0", "text": "Python is a programming language", "metadata": {}},
        {"chunk_id": "doc1#c1", "text": "Java is also a programming language", "metadata": {}},
        {"chunk_id": "doc1#c2", "text": "Python has great libraries for data science", "metadata": {}},
        {"chunk_id": "doc2#c0", "text": "Machine learning uses Python extensively", "metadata": {}},
        {"chunk_id": "doc2#c1", "text": "The snake Python is a reptile", "metadata": {}},
    ]
    
    # Initialize
    retriever = HybridRetriever()
    retriever.index_chunks(chunks)
    
    # Mock dense results (from FAISS)
    dense_results = [
        ("doc1#c0", 0.9),
        ("doc1#c2", 0.85),
        ("doc2#c0", 0.8),
    ]
    
    # Search
    query = "Python programming"
    results = retriever.search(query, dense_results, top_k=3)
    
    print(f"\nQuery: '{query}'")
    print(f"Results: {len(results)}\n")
    
    for i, result in enumerate(results, 1):
        print(f"{i}. {result.chunk_id} (combined={result.combined_score:.4f})")
        print(f"   Dense: {result.dense_score:.4f}, Sparse: {result.sparse_score:.4f}")
        print(f"   Text: {result.text[:60]}...")
        print()
