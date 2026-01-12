# contextual_enricher.py
"""
LLM-based Contextual Embedding Enricher voor AI-3.

Gebruikt llama3.1:8b met parallel processing (6 workers) voor snelle context 
generatie per chunk voordat deze wordt geëmbed. 

Performance: ~6x sneller dan 70B sequentieel, met minimaal kwaliteitsverlies.
Quality: 8B is zeer capabel voor context extraction van 1-2 zinnen.
"""

from __future__ import annotations

import logging
import os
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

logger = logging.getLogger(__name__)

# Configuratie
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Multi-GPU Ollama: gebruik meerdere instances op verschillende poorten
OLLAMA_MULTI_GPU = os.getenv("OLLAMA_MULTI_GPU", "false").lower() == "true"
OLLAMA_BASE_PORT = int(os.getenv("OLLAMA_BASE_PORT", "11434"))
OLLAMA_NUM_INSTANCES = int(os.getenv("OLLAMA_NUM_INSTANCES", "6"))
# Gebruik 8B voor snelle parallel context generatie (6x sneller met 6 GPU's!)
CONTEXT_MODEL = os.getenv("CONTEXT_MODEL", "llama3.1:8b")
CONTEXT_TIMEOUT = float(os.getenv("CONTEXT_TIMEOUT", "60"))
CONTEXT_ENABLED = os.getenv("CONTEXT_ENABLED", "true").lower() == "true"
# 6 workers = 6 GPU's parallel, laat 2 vrij voor andere taken
CONTEXT_MAX_WORKERS = int(os.getenv("CONTEXT_MAX_WORKERS", "6"))


def get_ollama_url_for_worker(worker_id: int) -> str:
    """
    Haal Ollama URL op voor een specifieke worker.
    Bij multi-GPU mode: round-robin over instances (poorten 11434-11439).
    """
    if not OLLAMA_MULTI_GPU:
        return OLLAMA_BASE_URL
    
    # Round-robin over beschikbare instances
    instance_idx = worker_id % OLLAMA_NUM_INSTANCES
    port = OLLAMA_BASE_PORT + instance_idx
    return f"http://localhost:{port}"


CONTEXT_SYSTEM_PROMPT = """Je bent een document-context expert. Je taak is om in 1-2 zinnen de context en relevantie van een tekstpassage te beschrijven.

Regels:
- Maximaal 2 zinnen
- Beschrijf WAT de passage behandelt
- Noem relevante entiteiten of cijfers
- Gebruik dezelfde taal als de input (Nederlands of Engels)
- Geef ALLEEN de contextbeschrijving, geen uitleg of commentaar"""


def generate_context_for_chunk(
    chunk_text: str,
    document_metadata: Dict[str, Any],
    timeout: float = CONTEXT_TIMEOUT,
    worker_id: int = 0
) -> Optional[str]:
    """
    Genereer context voor een enkele chunk via Ollama.
    
    Args:
        chunk_text: De tekst van de chunk
        document_metadata: Metadata over het hele document
            - filename
            - document_type
            - main_topics
            - main_entities
        worker_id: Worker ID voor multi-GPU load balancing
    
    Returns:
        Context string of None bij fout
    """
    if not CONTEXT_ENABLED:
        return None
    
    # Bouw de prompt
    doc_type = document_metadata.get("document_type", "onbekend")
    filename = document_metadata.get("filename", "onbekend")
    topics = document_metadata.get("main_topics", [])
    entities = document_metadata.get("main_entities", [])
    
    topics_str = ", ".join(topics[:5]) if topics else "niet gespecificeerd"
    entities_str = ", ".join(entities[:5]) if entities else "niet gespecificeerd"
    
    user_prompt = f"""Document informatie:
- Bestand: {filename}
- Type: {doc_type}
- Onderwerpen: {topics_str}
- Entiteiten: {entities_str}

Passage:
\"\"\"{chunk_text[:1500]}\"\"\"

Beschrijf de context van deze passage in 1-2 zinnen:"""

    payload = {
        "model": CONTEXT_MODEL,
        "messages": [
            {"role": "system", "content": CONTEXT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        # Houd model geladen voor volgende chunks (veel sneller!)
        "keep_alive": "30m",
        "options": {
            "temperature": 0.1,
            "num_predict": 150,  # Kort antwoord
        },
    }
    
    try:
        # Get Ollama URL for this worker (load balancing)
        ollama_url = get_ollama_url_for_worker(worker_id)
        
        # Gebruik Ollama's native API endpoint
        resp = httpx.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["message"]["content"].strip()
        return content
    except Exception as e:
        logger.warning(f"Context generation failed (worker {worker_id}): {e}")
        return None


def enrich_chunk_with_context(
    chunk_text: str,
    context: Optional[str],
    document_metadata: Dict[str, Any]
) -> str:
    """
    Combineer chunk tekst met context en metadata.
    
    Returns:
        Verrijkte chunk tekst klaar voor embedding
    """
    doc_type = document_metadata.get("document_type", "")
    filename = document_metadata.get("filename", "")
    
    parts = []
    
    # Document header
    if filename:
        parts.append(f"[Document: {filename}]")
    if doc_type:
        parts.append(f"[Type: {doc_type}]")
    
    # LLM-generated context
    if context:
        parts.append(f"[Context: {context}]")
    
    parts.append("")  # Lege regel voor de content
    parts.append(chunk_text)
    
    return "\n".join(parts)


def enrich_chunks_batch(
    chunks: List[str],
    document_metadata: Dict[str, Any],
    max_workers: int = CONTEXT_MAX_WORKERS
) -> List[str]:
    """
    Verrijk een batch chunks met context (parallel processing).
    
    Args:
        chunks: Lijst van chunk teksten
        document_metadata: Metadata voor alle chunks
        max_workers: Aantal parallelle LLM calls
    
    Returns:
        Lijst van verrijkte chunk teksten
    """
    if not CONTEXT_ENABLED or not chunks:
        # Fallback: alleen metadata toevoegen, geen LLM
        return [
            enrich_chunk_with_context(chunk, None, document_metadata)
            for chunk in chunks
        ]
    
    enriched_chunks = [None] * len(chunks)
    total_chunks = len(chunks)
    completed_chunks = 0
    
    def process_chunk(idx: int, chunk: str) -> tuple:
        # Use chunk index as worker_id for load balancing
        context = generate_context_for_chunk(chunk, document_metadata, worker_id=idx)
        enriched = enrich_chunk_with_context(chunk, context, document_metadata)
        return idx, enriched
    
    # Parallel processing met progress tracking
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_chunk, i, chunk): i 
            for i, chunk in enumerate(chunks)
        }
        
        for future in as_completed(futures):
            try:
                idx, enriched = future.result()
                enriched_chunks[idx] = enriched
                completed_chunks += 1
                
                # Progress logging elke 10 chunks of bij voltooiing
                if completed_chunks % 10 == 0 or completed_chunks == total_chunks:
                    pct = int(completed_chunks * 100 / total_chunks)
                    print(f"[ENRICHMENT] Progress: {completed_chunks}/{total_chunks} chunks ({pct}%)")
                    
            except Exception as e:
                # Fallback bij fout
                idx = futures[future]
                enriched_chunks[idx] = enrich_chunk_with_context(
                    chunks[idx], None, document_metadata
                )
                completed_chunks += 1
                logger.warning(f"Chunk {idx} enrichment failed: {e}")
    
    return enriched_chunks


def check_context_model_available() -> bool:
    """Check of het context model beschikbaar is in Ollama."""
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        
        # Check of model aanwezig is
        for model in models:
            if CONTEXT_MODEL in model:
                return True
        
        logger.warning(f"Context model '{CONTEXT_MODEL}' niet gevonden in Ollama")
        return False
    except Exception as e:
        logger.warning(f"Ollama check failed: {e}")
        return False


# Test functie
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Contextual Enricher Test ===")
    print(f"Model: {CONTEXT_MODEL}")
    print(f"Enabled: {CONTEXT_ENABLED}")
    print(f"Max workers: {CONTEXT_MAX_WORKERS}")
    
    # Check model
    if check_context_model_available():
        print("✅ Context model beschikbaar")
    else:
        print("❌ Context model NIET beschikbaar")
        print(f"   Run: ollama pull {CONTEXT_MODEL}")
    
    # Test met sample chunk
    test_chunk = """
    Balans per 31 december 2024
    
    Activa:
    - Vaste activa: €100.000
    - Vlottende activa: €50.000
    
    Totaal: €150.000
    """
    
    test_metadata = {
        "filename": "jaarrekening_2024.pdf",
        "document_type": "jaarrekening",
        "main_topics": ["financieel rapport", "balans"],
        "main_entities": ["DaSol B.V."],
    }
    
    print("\n--- Test Chunk ---")
    print(test_chunk[:200])
    
    print("\n--- Generating Context ---")
    context = generate_context_for_chunk(test_chunk, test_metadata)
    print(f"Context: {context}")
    
    print("\n--- Enriched Chunk ---")
    enriched = enrich_chunk_with_context(test_chunk, context, test_metadata)
    print(enriched)
