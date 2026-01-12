"""
Parent-Child Chunking Module

Hierarchische chunking strategie:
- Child chunks (klein, 400 chars) → embedden en indexeren (precisie)
- Parent chunks (groot, 1200 chars) → retourneren bij match (context)

Dit geeft best of both worlds: precisie in retrieval, context in generation.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParentChildChunk:
    """
    Parent-child chunk pair.
    
    Child is indexed for search (small, precise).
    Parent is returned for context (large, informative).
    """
    parent_id: str
    child_id: str
    parent_text: str
    child_text: str
    child_index: int  # Position of child within parent
    metadata: Dict


class ParentChildChunker:
    """
    Chunk text hierarchically into parent-child pairs.
    
    Benefits:
    - Better precision: Small child chunks match queries precisely
    - Better context: Large parent chunks provide enough context for LLM
    - No information loss: Parent contains complete context around match
    """
    
    def __init__(
        self,
        parent_max_chars: int = 1200,
        child_max_chars: int = 400,
        parent_overlap: int = 200,
        child_overlap: int = 50
    ):
        """
        Initialize parent-child chunker.
        
        Args:
            parent_max_chars: Max chars per parent chunk
            child_max_chars: Max chars per child chunk
            parent_overlap: Overlap between parent chunks
            child_overlap: Overlap between child chunks within parent
        """
        self.parent_max_chars = parent_max_chars
        self.child_max_chars = child_max_chars
        self.parent_overlap = parent_overlap
        self.child_overlap = child_overlap
        
        logger.info(
            f"[ParentChild] Initialized (parent={parent_max_chars}, "
            f"child={child_max_chars})"
        )
    
    def chunk(self, text: str, doc_id: str) -> List[ParentChildChunk]:
        """
        Chunk text into parent-child pairs.
        
        Args:
            text: Text to chunk
            doc_id: Document ID
        
        Returns:
            List of ParentChildChunk objects
        """
        # Step 1: Create parent chunks
        parents = self._chunk_with_overlap(
            text,
            max_chars=self.parent_max_chars,
            overlap=self.parent_overlap
        )
        
        logger.info(f"[ParentChild] Created {len(parents)} parent chunks")
        
        # Step 2: For each parent, create child chunks
        all_pairs = []
        parent_idx = 0
        
        for parent_text in parents:
            parent_id = f"{doc_id}#p{parent_idx:04d}"
            
            # Chunk parent into children
            children = self._chunk_with_overlap(
                parent_text,
                max_chars=self.child_max_chars,
                overlap=self.child_overlap
            )
            
            # Create parent-child pairs
            for child_idx, child_text in enumerate(children):
                child_id = f"{parent_id}_c{child_idx:02d}"
                
                pair = ParentChildChunk(
                    parent_id=parent_id,
                    child_id=child_id,
                    parent_text=parent_text,
                    child_text=child_text,
                    child_index=child_idx,
                    metadata={
                        "doc_id": doc_id,
                        "parent_idx": parent_idx,
                        "child_idx": child_idx,
                        "total_children": len(children),
                        "parent_chars": len(parent_text),
                        "child_chars": len(child_text)
                    }
                )
                all_pairs.append(pair)
            
            parent_idx += 1
        
        logger.info(
            f"[ParentChild] Created {len(all_pairs)} parent-child pairs "
            f"({len(parents)} parents × ~{len(all_pairs)/len(parents):.1f} children avg)"
        )
        
        return all_pairs
    
    def _chunk_with_overlap(
        self,
        text: str,
        max_chars: int,
        overlap: int
    ) -> List[str]:
        """
        Chunk text with overlap, respecting sentence boundaries.
        
        Args:
            text: Text to chunk
            max_chars: Max characters per chunk
            overlap: Overlap between chunks
        
        Returns:
            List of chunk texts
        """
        if len(text) <= max_chars:
            return [text]
        
        # Split into sentences (simple approach)
        sentences = self._split_sentences(text)
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            
            if current_length + sentence_length > max_chars and current_chunk:
                # Save current chunk
                chunk_text = " ".join(current_chunk)
                chunks.append(chunk_text)
                
                # Start new chunk with overlap
                overlap_sentences = []
                overlap_length = 0
                
                # Take sentences from end for overlap
                for sent in reversed(current_chunk):
                    if overlap_length + len(sent) <= overlap:
                        overlap_sentences.insert(0, sent)
                        overlap_length += len(sent)
                    else:
                        break
                
                current_chunk = overlap_sentences
                current_length = overlap_length
            
            current_chunk.append(sentence)
            current_length += sentence_length
        
        # Add final chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append(chunk_text)
        
        return chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences (simple approach).
        
        TODO: Use better sentence splitter like spaCy for production.
        """
        import re
        
        # Simple sentence splitting on . ! ? followed by space/newline
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        # Filter empty
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return sentences


# Module test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Parent-Child Chunking Test ===\n")
    
    # Sample text
    text = """
    This is the first paragraph. It discusses the introduction to the topic. 
    The topic is very interesting and worth exploring in detail.
    
    The second paragraph goes deeper. It provides examples and use cases. 
    Each example is carefully chosen to illustrate the point.
    We want to make sure the reader understands fully.
    
    The third paragraph concludes. It summarizes the key points discussed earlier.
    This helps reinforce the message. The conclusion is important for retention.
    Finally, we end with a call to action.
    """
    
    # Initialize chunker
    chunker = ParentChildChunker(
        parent_max_chars=200,  # Small for demo
        child_max_chars=80,
        parent_overlap=50,
        child_overlap=20
    )
    
    # Chunk
    pairs = chunker.chunk(text, doc_id="test_doc")
    
    print(f"Created {len(pairs)} parent-child pairs\n")
    
    # Show first few pairs
    for i, pair in enumerate(pairs[:5], 1):
        print(f"Pair {i}:")
        print(f"  Parent ID: {pair.parent_id}")
        print(f"  Child ID: {pair.child_id}")
        print(f"  Parent text ({len(pair.parent_text)} chars): {pair.parent_text[:80]}...")
        print(f"  Child text ({len(pair.child_text)} chars): {pair.child_text[:60]}...")
        print()
    
    if len(pairs) > 5:
        print(f"... and {len(pairs) - 5} more pairs")
