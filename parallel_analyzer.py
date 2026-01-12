"""
Parallel Document Analyzer - Analyseert grote documenten over meerdere GPU's.

Split documenten per pagina en verdeelt werk over beschikbare GPU's
om thermal throttling te voorkomen.

Strategie:
1. Document > 3MB → split in pagina's
2. Check welke GPU's vrij zijn (temp < 80°C, >6GB vrij)
3. Verdeel pagina's in batches per GPU
4. Analyseer per batch op rotererende GPU's
5. Aggregeer resultaten naar één DocumentAnalysis
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from analyzer_schemas import DocumentAnalysis
from gpu_manager import gpu_manager
from gpu_phase_lock import gpu_exclusive_lock
from status_reporter import report_analyzing, report_failed, report_status, ProcessingStage

logger = logging.getLogger(__name__)

# Config
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:70b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

# Multi-GPU Ollama config
# Als OLLAMA_MULTI_GPU=true, dan draaien er meerdere Ollama instances:
# - GPU 0 -> port 11434
# - GPU 1 -> port 11435
# - GPU 2 -> port 11436, etc.
# Multi-GPU: elke GPU heeft eigen Ollama instance
# GPU 0-3 voor Ollama (LLM), GPU 4-7 vrij voor embedding
OLLAMA_MULTI_GPU = os.getenv("OLLAMA_MULTI_GPU", "true").lower() == "true"
OLLAMA_BASE_PORT = int(os.getenv("OLLAMA_BASE_PORT", "11434"))
OLLAMA_NUM_INSTANCES = int(os.getenv("OLLAMA_NUM_INSTANCES", "4"))  # 4 instances op GPU 0-3

# Thresholds
SIZE_THRESHOLD_MB = float(os.getenv("PARALLEL_SIZE_THRESHOLD_MB", "3"))  # 3MB
PAGES_PER_BATCH = int(os.getenv("PAGES_PER_BATCH", "5"))  # 5 pagina's per GPU batch
MAX_GPU_TEMP = int(os.getenv("MAX_GPU_TEMP", "75"))  # Max 75°C
MIN_FREE_GPU_MB = int(os.getenv("MIN_FREE_GPU_MB", "6000"))  # 6GB vrij nodig


def get_ollama_url_for_gpu(gpu_index: int) -> str:
    """
    Krijg Ollama URL voor specifieke GPU.
    
    Als OLLAMA_MULTI_GPU=true:
        GPU 0 -> http://localhost:11434
        GPU 1 -> http://localhost:11435
        etc.
    Anders:
        Altijd OLLAMA_BASE_URL
    """
    if OLLAMA_MULTI_GPU:
        port = OLLAMA_BASE_PORT + (gpu_index % OLLAMA_NUM_INSTANCES)
        return f"http://localhost:{port}"
    return OLLAMA_BASE_URL


@dataclass
class PartialAnalysis:
    """Analyse van een deel van het document."""
    page_range: str  # bijv. "1-10"
    gpu_index: int
    duration_sec: float
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    domain: str = ""
    document_type: str = ""
    has_tables: bool = False
    has_images: bool = False
    error: Optional[str] = None


def should_use_parallel_analysis(text: str, filename: Optional[str] = None) -> bool:
    """
    Bepaal of parallel analyse nodig is.
    
    Criteria:
    - Grootte > 3MB
    - Of > 50 pagina's
    """
    size_mb = len(text.encode('utf-8')) / (1024 * 1024)
    page_count = text.count("[PAGE ")
    
    if size_mb > SIZE_THRESHOLD_MB:
        logger.info(f"[ParallelAnalyzer] Document {size_mb:.1f}MB > {SIZE_THRESHOLD_MB}MB → parallel")
        return True
    
    if page_count > 50:
        logger.info(f"[ParallelAnalyzer] Document {page_count} pagina's > 50 → parallel")
        return True
    
    return False


def split_document_by_pages(text: str) -> List[str]:
    """
    Split document op [PAGE X] markers.
    
    Returns:
        Lijst van pagina teksten
    """
    # Zoek pagina markers
    pages = re.split(r'\[PAGE \d+\]', text)
    pages = [p.strip() for p in pages if p.strip()]
    
    if not pages:
        # Geen pagina markers, split op paragraphs
        paragraphs = text.split('\n\n')
        # Groepeer in chunks van ~2000 chars
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) > 2000:
                if current:
                    chunks.append(current)
                current = p
            else:
                current = f"{current}\n\n{p}" if current else p
        if current:
            chunks.append(current)
        return chunks
    
    logger.info(f"[ParallelAnalyzer] Document gesplit in {len(pages)} pagina's")
    return pages


def create_page_batches(pages: List[str], batch_size: int = PAGES_PER_BATCH) -> List[List[str]]:
    """
    Groepeer pagina's in batches.
    
    Args:
        pages: Lijst van pagina teksten
        batch_size: Pagina's per batch
    
    Returns:
        Lijst van batches (elke batch is een lijst van pagina's)
    """
    batches = []
    for i in range(0, len(pages), batch_size):
        batches.append(pages[i:i + batch_size])
    
    logger.info(f"[ParallelAnalyzer] {len(pages)} pagina's → {len(batches)} batches")
    return batches


def analyze_batch(
    batch: List[str],
    batch_index: int,
    gpu_index: int,
    filename: Optional[str] = None,
) -> PartialAnalysis:
    """
    Analyseer één batch pagina's.
    
    Args:
        batch: Lijst van pagina teksten
        batch_index: Index van deze batch
        gpu_index: GPU om te gebruiken (voor logging)
        filename: Bestandsnaam
    
    Returns:
        PartialAnalysis met gevonden entities, topics, etc.
    """
    start_time = time.time()
    page_start = batch_index * PAGES_PER_BATCH + 1
    page_end = page_start + len(batch) - 1
    page_range = f"{page_start}-{page_end}"
    
    # Combineer batch tekst
    combined_text = "\n\n---\n\n".join(batch)[:8000]  # Max 8K chars voor LLM
    
    # Bouw prompt
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Je bent een document-analyzer. Analyseer de gegeven tekst en "
                    "geef een JSON met:\n"
                    "- entities: lijst van max 5 belangrijke entiteiten (namen/organisaties)\n"
                    "- topics: lijst van max 5 onderwerpen\n"
                    "- domain: kort domeinwoord (finance, sales, legal, tech, general)\n"
                    "- document_type: type document (jaarrekening, offerte, rapport, etc.)\n"
                    "- has_tables: true/false\n"
                    "Antwoord ALLEEN met JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Bestandsnaam: {filename or 'onbekend'}\n"
                    f"Pagina's: {page_range}\n\n"
                    f"TEKST:\n{combined_text}\n\n"
                    "Geef JSON analyse:"
                ),
            },
        ],
        "stream": False,
        "keep_alive": "0",  # Unload model direct
        "options": {
            "temperature": 0.1,
        },
    }
    
    try:
        # Gebruik GPU-specifieke Ollama instance
        ollama_url = get_ollama_url_for_gpu(gpu_index)
        logger.info(f"[ParallelAnalyzer] Batch {batch_index} (p{page_range}) → GPU {gpu_index} ({ollama_url})")
        
        # Ollama native endpoint is /api/chat
        # Global GPU lock: 70B/LLM fase claimt alle GPU's
        with gpu_exclusive_lock("ollama_parallel_batch", doc_id=filename or "", timeout_sec=3600):
            url = f"{ollama_url}/api/chat"
            resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"]  # Ollama format, niet OpenAI
        
        # Parse JSON - robuust: vind eerste complete JSON object
        import json
        raw = content.strip()
        
        # Probeer eerste JSON object te vinden
        parsed = None
        
        # Methode 1: Direct parsen
        if raw.startswith("{"):
            try:
                # Vind het einde van het eerste JSON object
                brace_count = 0
                end_idx = 0
                for i, char in enumerate(raw):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i + 1
                            break
                parsed = json.loads(raw[:end_idx])
            except json.JSONDecodeError:
                pass
        
        # Methode 2: Zoek JSON in tekst
        if parsed is None:
            m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        
        # Methode 3: Probeer hele content
        if parsed is None:
            try:
                parsed = json.loads(raw.split('\n')[0])  # Eerste regel
            except json.JSONDecodeError:
                parsed = {}
                logger.warning(f"[ParallelAnalyzer] Batch {batch_index}: could not parse JSON, using defaults")
        
        duration = time.time() - start_time
        
        return PartialAnalysis(
            page_range=page_range,
            gpu_index=gpu_index,
            duration_sec=duration,
            entities=parsed.get("entities", [])[:5],
            topics=parsed.get("topics", [])[:5],
            domain=parsed.get("domain", "general"),
            document_type=parsed.get("document_type", ""),
            has_tables=parsed.get("has_tables", False),
        )
        
    except Exception as e:
        duration = time.time() - start_time
        logger.warning(f"[ParallelAnalyzer] Batch {batch_index} failed: {e}")
        return PartialAnalysis(
            page_range=page_range,
            gpu_index=gpu_index,
            duration_sec=duration,
            error=str(e),
        )


def aggregate_analyses(
    partials: List[PartialAnalysis],
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> DocumentAnalysis:
    """
    Combineer partial analyses tot één DocumentAnalysis.
    
    Args:
        partials: Lijst van PartialAnalysis objecten
        filename: Originele bestandsnaam
        mime_type: MIME type
    
    Returns:
        Gecombineerde DocumentAnalysis
    """
    # Verzamel alle entities en topics
    all_entities = []
    all_topics = []
    domains = []
    doc_types = []
    has_tables = False
    total_duration = 0.0
    errors = []
    
    for p in partials:
        if p.error:
            errors.append(f"{p.page_range}: {p.error}")
            continue
        
        all_entities.extend(p.entities)
        all_topics.extend(p.topics)
        if p.domain:
            domains.append(p.domain)
        if p.document_type:
            doc_types.append(p.document_type)
        if p.has_tables:
            has_tables = True
        total_duration += p.duration_sec
    
    # Dedupliceer en neem top items
    unique_entities = list(dict.fromkeys(all_entities))[:10]
    unique_topics = list(dict.fromkeys(all_topics))[:10]
    
    # Bepaal dominant domain en type
    def most_common(items: List[str], default: str = "") -> str:
        if not items:
            return default
        counts = {}
        for item in items:
            counts[item] = counts.get(item, 0) + 1
        return max(counts, key=counts.get)
    
    final_domain = most_common(domains, "general")
    final_doc_type = most_common(doc_types, "document")
    
    # Bepaal chunking strategy
    if final_doc_type in ["jaarrekening", "annual_report", "financieel_rapport"]:
        chunk_strategy = "page_plus_table_aware"
    elif final_doc_type in ["offerte", "aanbieding", "contract"]:
        chunk_strategy = "semantic_sections"
    elif has_tables:
        chunk_strategy = "table_aware"
    else:
        chunk_strategy = "default"
    
    # Bouw extra info
    extra = {
        "parallel_analysis": True,
        "batches_processed": len([p for p in partials if not p.error]),
        "batches_failed": len([p for p in partials if p.error]),
        "total_duration_sec": round(total_duration, 2),
        "domain": final_domain,
    }
    if errors:
        extra["errors"] = errors[:5]  # Max 5 errors tonen
    
    logger.info(
        f"[ParallelAnalyzer] Aggregated: {len(unique_entities)} entities, "
        f"{len(unique_topics)} topics, domain={final_domain}, type={final_doc_type}"
    )
    
    return DocumentAnalysis(
        document_type=final_doc_type,
        mime_type=mime_type,
        language="nl",  # Assume NL, kan later verbeterd
        page_count=len(partials) * PAGES_PER_BATCH,
        has_tables=has_tables,
        has_images=False,
        main_entities=unique_entities,
        main_topics=unique_topics,
        suggested_chunk_strategy=chunk_strategy,
        suggested_embed_model="BAAI/bge-m3",
        extra=extra,
    )


def parallel_analyze_document(
    text: str,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
    doc_id: Optional[str] = None,  # Voor status reporting
) -> DocumentAnalysis:
    """
    Analyseer een groot document parallel over meerdere GPU's.
    
    Flow:
    1. Split document in pagina's
    2. Maak batches van pagina's
    3. Check welke GPU's vrij zijn
    4. Analyseer elke batch parallel over GPU's
    5. Aggregeer resultaten
    
    Args:
        text: Document tekst
        filename: Bestandsnaam
        mime_type: MIME type
        doc_id: Document ID voor status reporting naar AI-4
    
    Returns:
        DocumentAnalysis
    """
    logger.info(f"[ParallelAnalyzer] Starting parallel analysis for {filename}")
    start_time = time.time()
    
    # Report start naar AI-4
    if doc_id:
        report_status(doc_id, ProcessingStage.ANALYZING, 
                     progress_pct=5, 
                     message=f"Starting parallel analysis ({OLLAMA_MODEL})",
                     metadata={"model": OLLAMA_MODEL, "multi_gpu": OLLAMA_MULTI_GPU})
    
    # Step 1: Split document
    pages = split_document_by_pages(text)
    
    # Step 2: Create batches
    batches = create_page_batches(pages, PAGES_PER_BATCH)
    
    # Step 3: Get available GPUs
    free_gpus = gpu_manager.get_free_gpus(min_free_mb=MIN_FREE_GPU_MB, max_temp=MAX_GPU_TEMP)
    
    if not free_gpus:
        logger.warning("[ParallelAnalyzer] Geen vrije GPU's, wacht op cooldown...")
        # Probeer koelste GPU
        coolest = gpu_manager.get_coolest_gpu(min_free_mb=MIN_FREE_GPU_MB)
        if coolest >= 0:
            gpu_manager.wait_for_gpu_cooldown(coolest, max_temp=MAX_GPU_TEMP)
            free_gpus = [coolest]
        else:
            free_gpus = [0]  # Fallback naar GPU 0
    
    logger.info(f"[ParallelAnalyzer] Beschikbare GPU's: {free_gpus}")
    
    # Step 4: Analyse batches PARALLEL over alle GPU's!
    partials: List[PartialAnalysis] = []
    completed_count = 0
    failed_count = 0
    
    # Gebruik ThreadPoolExecutor voor echte parallelle verwerking
    max_workers = min(len(batches), len(free_gpus))
    logger.info(f"[ParallelAnalyzer] Starting {len(batches)} batches parallel over {max_workers} GPU's")
    
    # Report batch start
    if doc_id:
        report_status(doc_id, ProcessingStage.ANALYZING,
                     progress_pct=10,
                     message=f"Analyzing {len(batches)} batches over {max_workers} GPU's",
                     metadata={"batches": len(batches), "gpus_used": max_workers})
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit alle batches tegelijk
            futures = {}
            for batch_idx, batch in enumerate(batches):
                # Round-robin over beschikbare GPU's
                gpu_idx = free_gpus[batch_idx % len(free_gpus)]
                future = executor.submit(analyze_batch, batch, batch_idx, gpu_idx, filename)
                futures[future] = (batch_idx, gpu_idx)
            
            # Collect resultaten met status updates
            for future in as_completed(futures):
                batch_idx, gpu_idx = futures[future]
                try:
                    partial = future.result()
                    partials.append(partial)
                    
                    if partial.error:
                        failed_count += 1
                    else:
                        completed_count += 1
                    
                    # Report progress
                    progress = 10 + int((completed_count + failed_count) / len(batches) * 80)
                    if doc_id:
                        report_status(doc_id, ProcessingStage.ANALYZING,
                                     progress_pct=progress,
                                     message=f"Batch {completed_count + failed_count}/{len(batches)} done (GPU {gpu_idx})",
                                     metadata={"completed": completed_count, "failed": failed_count})
                    
                    logger.info(
                        f"[ParallelAnalyzer] Batch {batch_idx + 1}/{len(batches)} done "
                        f"(GPU {gpu_idx}, {partial.duration_sec:.1f}s)"
                    )
                except Exception as e:
                    logger.error(f"[ParallelAnalyzer] Batch {batch_idx} exception: {e}")
                    failed_count += 1
                    partials.append(PartialAnalysis(
                        page_range=f"{batch_idx * PAGES_PER_BATCH + 1}-?",
                        gpu_index=gpu_idx,
                        duration_sec=0,
                        error=str(e),
                    ))
        
        # Sorteer resultaten op batch_index voor consistentie
        partials.sort(key=lambda p: int(p.page_range.split("-")[0]))
        
        # Step 5: Aggregate
        result = aggregate_analyses(partials, filename, mime_type)
        
        total_duration = time.time() - start_time
        result.extra["total_parallel_duration"] = round(total_duration, 2)
        
        # Check if too many failures - trigger GPU cleanup
        if failed_count > len(batches) * 0.5:  # >50% failures
            logger.warning(f"[ParallelAnalyzer] High failure rate ({failed_count}/{len(batches)}), cleaning GPU's...")
            gpu_manager.full_cleanup()
            if doc_id:
                report_failed(doc_id, f"Too many batch failures: {failed_count}/{len(batches)}", "parallel_analysis")
        
        logger.info(
            f"[ParallelAnalyzer] Complete: {len(batches)} batches in {total_duration:.1f}s "
            f"(success: {completed_count}, failed: {failed_count})"
        )
        
        return result
        
    except Exception as e:
        # Critical failure - cleanup GPU's
        logger.error(f"[ParallelAnalyzer] Critical failure: {e}")
        gpu_manager.full_cleanup()
        if doc_id:
            report_failed(doc_id, str(e), "parallel_analysis")
        raise


# Test functie
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Parallel Analyzer Test ===")
    
    # Simuleer groot document met pagina markers
    test_pages = []
    for i in range(20):
        test_pages.append(f"[PAGE {i+1}]\nDit is pagina {i+1} van het testdocument.\n" * 10)
    
    test_text = "\n".join(test_pages)
    
    print(f"Test document: {len(test_text)} chars, {len(test_pages)} pagina's")
    print(f"Should use parallel: {should_use_parallel_analysis(test_text)}")
    
    # Check GPU status
    print("\nGPU Status:")
    temps = gpu_manager.get_gpu_temperatures()
    free = gpu_manager.get_free_gpus()
    print(f"  Temperaturen: {temps}")
    print(f"  Vrije GPU's: {free}")
