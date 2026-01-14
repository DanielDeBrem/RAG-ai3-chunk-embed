"""
Parallel Multi-GPU Embedder voor AI-3 DataFactory.

Gebruikt meerdere GPU's tegelijk om embeddings te genereren,
met automatische load balancing en GPU cleanup.

Met 8x RTX 3060 Ti kunnen we tot 8x sneller embedden!
"""

from __future__ import annotations

import gc
import os
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import threading

import numpy as np

# Probeer torch te importeren
try:
    import torch
    from sentence_transformers import SentenceTransformer
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from gpu_manager import gpu_manager, GPUInfo

logger = logging.getLogger(__name__)

# Configuration
MAX_PARALLEL_GPUS = int(os.getenv("MAX_PARALLEL_GPUS", "6"))  # Laat 2 voor Ollama
MIN_FREE_MB_FOR_EMBED = int(os.getenv("MIN_FREE_MB_FOR_EMBED", "2000"))
MAX_GPU_TEMP_EMBED = int(os.getenv("MAX_GPU_TEMP_EMBED", "75"))
BATCH_SIZE_PER_GPU = int(os.getenv("BATCH_SIZE_PER_GPU", "32"))
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")


@dataclass
class GPUWorker:
    """Een GPU worker met eigen model instance."""
    gpu_index: int
    device: str
    model: Optional[SentenceTransformer] = None
    lock: threading.Lock = None
    
    def __post_init__(self):
        if self.lock is None:
            self.lock = threading.Lock()


class ParallelEmbedder:
    """
    Parallel embedder die meerdere GPU's gebruikt.
    
    Features:
    - Automatische GPU selectie (kiest vrije GPU's)
    - Lazy model loading per GPU
    - Load balancing over beschikbare GPU's
    - GPU cleanup voor en na gebruik
    - Fallback naar single GPU/CPU bij problemen
    
    Gebruik:
        embedder = ParallelEmbedder()
        embeddings = embedder.embed(texts)  # Parallel over meerdere GPU's
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._workers: Dict[int, GPUWorker] = {}
        self._model_name = EMBED_MODEL_NAME
        self._embedding_dim: Optional[int] = None
        self._initialized = True
        
        logger.info(f"[ParallelEmbedder] Initialized with model {self._model_name}")
    
    def _get_available_gpus(self, min_free_mb: int = MIN_FREE_MB_FOR_EMBED) -> List[int]:
        """
        Krijg lijst van beschikbare GPU's voor embedding.
        
        BELANGRIJK: Prefer GPU 6-7 (dedicated embedding GPU's).
        Ollama draait op GPU 0-5, dus we willen daar NIET embedden!
        
        Returns:
            Lijst van GPU indices, gesorteerd op vrij geheugen (meeste eerst)
        """
        # Gebruik GPUManager temperature-aware selectie (voorkom 90°C kaarten)
        free_gpu_indices = gpu_manager.get_free_gpus(
            min_free_mb=min_free_mb,
            max_temp=MAX_GPU_TEMP_EMBED,
        )
        
        # PRIORITEIT: GPU 6-7 eerst (dedicated embedding GPU's)
        # Dan pas GPU 0-5 (als Ollama echt weg is)
        embedding_gpus = []
        for gpu_idx in [6, 7]:  # Prefer deze
            if gpu_idx in free_gpu_indices:
                embedding_gpus.append(gpu_idx)
        
        # Als GPU 6-7 niet genoeg zijn, voeg anderen toe
        for gpu_idx in free_gpu_indices:
            if gpu_idx not in embedding_gpus:
                embedding_gpus.append(gpu_idx)
        
        # Beperk tot MAX_PARALLEL_GPUS
        result = embedding_gpus[:MAX_PARALLEL_GPUS]

        logger.info(
            f"[ParallelEmbedder] Available GPUs (min_free={min_free_mb}MB, max_temp={MAX_GPU_TEMP_EMBED}C): {result} (preferred 6-7)"
        )
        return result
    
    def _cleanup_gpu(self, gpu_index: int):
        """Cleanup specifieke GPU."""
        if not TORCH_AVAILABLE:
            return
        
        try:
            with torch.cuda.device(gpu_index):
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as e:
            logger.warning(f"[ParallelEmbedder] Cleanup GPU {gpu_index} failed: {e}")
    
    def _cleanup_all_gpus(self):
        """Cleanup alle GPU's."""
        if not TORCH_AVAILABLE:
            return
        
        gc.collect()
        
        for i in range(torch.cuda.device_count()):
            self._cleanup_gpu(i)
        
        gc.collect()
        logger.info("[ParallelEmbedder] All GPU cleanup complete")
    
    def _load_model_on_gpu(self, gpu_index: int) -> Optional[SentenceTransformer]:
        """
        Laad model op specifieke GPU.
        
        FIX voor Blunder 4: Meta tensor error
        - Laad eerst op CPU, dan verplaats naar GPU
        - Extra garbage collection voor stabiele state
        
        Returns:
            SentenceTransformer model of None bij fout
        """
        device = f"cuda:{gpu_index}"
        
        try:
            logger.info(f"[ParallelEmbedder] Loading model on GPU {gpu_index}...")
            
            # Cleanup GPU eerst
            self._cleanup_gpu(gpu_index)
            gc.collect()
            
            # FIX: Laad model eerst op CPU om meta tensor error te voorkomen
            # Dit voorkomt "Cannot copy out of meta tensor" errors
            logger.info(f"[ParallelEmbedder] Loading model to CPU first (meta tensor fix)...")
            model = SentenceTransformer(self._model_name, device="cpu")
            
            # Verplaats naar GPU met error handling
            logger.info(f"[ParallelEmbedder] Moving model to GPU {gpu_index}...")
            try:
                model = model.to(device)
            except NotImplementedError as e:
                # Meta tensor error - probeer alternatieve methode
                if "meta tensor" in str(e).lower():
                    logger.warning(f"[ParallelEmbedder] Meta tensor error, trying to_empty()...")
                    # Gebruik to_empty voor meta tensors
                    model = model.to_empty(device=device)
                    # Re-initialiseer parameters
                    for param in model.parameters():
                        if param.device.type == 'meta':
                            param.data = torch.empty_like(param, device=device)
                else:
                    raise
            
            # Bepaal embedding dimensie
            if self._embedding_dim is None:
                test_emb = model.encode(["test"], show_progress_bar=False)
                self._embedding_dim = test_emb.shape[1]
            
            logger.info(f"[ParallelEmbedder] Model loaded on GPU {gpu_index}")
            return model
            
        except Exception as e:
            logger.error(f"[ParallelEmbedder] Failed to load model on GPU {gpu_index}: {e}")
            # Cleanup bij fout
            self._cleanup_gpu(gpu_index)
            gc.collect()
            return None
    
    def _get_or_create_worker(self, gpu_index: int) -> Optional[GPUWorker]:
        """Krijg of maak worker voor GPU."""
        if gpu_index not in self._workers:
            model = self._load_model_on_gpu(gpu_index)
            if model is None:
                return None
            
            self._workers[gpu_index] = GPUWorker(
                gpu_index=gpu_index,
                device=f"cuda:{gpu_index}",
                model=model,
            )
        
        return self._workers[gpu_index]
    
    def _embed_batch_on_gpu(
        self,
        texts: List[str],
        gpu_index: int,
        batch_size: int = BATCH_SIZE_PER_GPU
    ) -> Tuple[int, Optional[np.ndarray], Optional[str]]:
        """
        Embed batch teksten op specifieke GPU.
        
        Returns:
            Tuple van (gpu_index, embeddings of None, error message of None)
        """
        worker = self._get_or_create_worker(gpu_index)
        if worker is None:
            return (gpu_index, None, f"Failed to create worker for GPU {gpu_index}")
        
        try:
            with worker.lock:
                emb = worker.model.encode(
                    texts,
                    batch_size=batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                return (gpu_index, np.asarray(emb, dtype="float32"), None)
                
        except torch.cuda.OutOfMemoryError as e:
            logger.warning(f"[ParallelEmbedder] OOM on GPU {gpu_index}: {e}")
            self._cleanup_gpu(gpu_index)
            return (gpu_index, None, f"OOM on GPU {gpu_index}")
            
        except Exception as e:
            logger.error(f"[ParallelEmbedder] Error on GPU {gpu_index}: {e}")
            return (gpu_index, None, str(e))
    
    def _distribute_texts(
        self,
        texts: List[str],
        gpu_indices: List[int]
    ) -> List[Tuple[List[str], int]]:
        """
        Verdeel teksten over GPU's.
        
        Returns:
            Lijst van (batch_texts, gpu_index) tuples
        """
        n_gpus = len(gpu_indices)
        n_texts = len(texts)
        
        # Verdeel teksten gelijk over GPU's
        texts_per_gpu = (n_texts + n_gpus - 1) // n_gpus
        
        batches = []
        for i, gpu_idx in enumerate(gpu_indices):
            start = i * texts_per_gpu
            end = min(start + texts_per_gpu, n_texts)
            if start < n_texts:
                batches.append((texts[start:end], gpu_idx))
        
        return batches
    
    def embed(
        self,
        texts: List[str],
        cleanup_before: bool = True,
        cleanup_after: bool = True,
        min_texts_for_parallel: int = 10,
    ) -> np.ndarray:
        """
        Embed teksten met parallel GPU processing.
        
        Args:
            texts: Lijst van teksten om te embedden
            cleanup_before: Cleanup GPU's voor embedding (aanbevolen)
            cleanup_after: Cleanup GPU's na embedding
            min_texts_for_parallel: Minimum aantal teksten voor parallel processing
        
        Returns:
            Numpy array van embeddings [n_texts, embedding_dim]
        """
        if not texts:
            raise ValueError("Geen teksten om te embedden")
        
        start_time = time.time()
        n_texts = len(texts)
        
        # Cleanup voor embedding
        if cleanup_before:
            logger.info("[ParallelEmbedder] Pre-embed GPU cleanup...")
            self._cleanup_all_gpus()
        
        # Krijg beschikbare GPU's
        available_gpus = self._get_available_gpus()
        
        if not available_gpus:
            logger.warning("[ParallelEmbedder] Geen vrije GPU's, fallback naar CPU")
            return self._embed_on_cpu(texts)
        
        # Single GPU voor kleine batches
        if n_texts < min_texts_for_parallel or len(available_gpus) == 1:
            logger.info(f"[ParallelEmbedder] Using single GPU {available_gpus[0]} for {n_texts} texts")
            _, emb, error = self._embed_batch_on_gpu(texts, available_gpus[0])
            if emb is None:
                logger.warning(f"[ParallelEmbedder] Single GPU failed: {error}, trying CPU")
                return self._embed_on_cpu(texts)
            
            duration = time.time() - start_time
            logger.info(f"[ParallelEmbedder] Single GPU embed complete: {n_texts} texts in {duration:.2f}s")
            return emb
        
        # Parallel processing over meerdere GPU's
        logger.info(f"[ParallelEmbedder] Parallel embed {n_texts} texts over {len(available_gpus)} GPUs")
        
        # Verdeel teksten over GPU's
        batches = self._distribute_texts(texts, available_gpus)
        
        # Track resultaten in originele volgorde
        results: Dict[int, np.ndarray] = {}
        errors: List[str] = []
        
        # Parallel uitvoeren met progress tracking
        completed_texts = 0
        
        with ThreadPoolExecutor(max_workers=len(batches)) as executor:
            futures = {}
            batch_info = {}  # Track welke batch bij welke future hoort
            
            for i, (batch_texts, gpu_idx) in enumerate(batches):
                future = executor.submit(self._embed_batch_on_gpu, batch_texts, gpu_idx)
                futures[future] = i
                batch_info[i] = (len(batch_texts), gpu_idx)
            
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    gpu_idx, emb, error = future.result()
                    
                    if emb is not None:
                        results[batch_idx] = emb
                        completed_texts += len(emb)
                        
                        # Progress logging
                        pct = int(completed_texts * 100 / n_texts)
                        print(f"[EMBEDDING] Progress: {completed_texts}/{n_texts} texts ({pct}%)")
                        logger.info(f"[ParallelEmbedder] Batch {batch_idx} done on GPU {gpu_idx}")
                    else:
                        errors.append(error or f"Unknown error batch {batch_idx}")
                        logger.warning(f"[ParallelEmbedder] Batch {batch_idx} failed: {error}")
                        
                except Exception as e:
                    errors.append(str(e))
                    logger.error(f"[ParallelEmbedder] Batch {batch_idx} exception: {e}")
        
        # Check of alle batches gelukt zijn
        if len(results) != len(batches):
            # Sommige batches gefaald, probeer opnieuw op CPU
            failed_batches = set(range(len(batches))) - set(results.keys())
            logger.warning(f"[ParallelEmbedder] {len(failed_batches)} batches failed, retrying on CPU")
            
            for batch_idx in failed_batches:
                batch_texts, _ = batches[batch_idx]
                try:
                    cpu_emb = self._embed_on_cpu(batch_texts)
                    results[batch_idx] = cpu_emb
                except Exception as e:
                    logger.error(f"[ParallelEmbedder] CPU fallback failed for batch {batch_idx}: {e}")
                    raise RuntimeError(f"Embedding failed for batch {batch_idx}: {errors}")
        
        # Combineer resultaten in juiste volgorde
        ordered_results = [results[i] for i in range(len(batches))]
        combined = np.vstack(ordered_results)
        
        # Cleanup na embedding
        if cleanup_after:
            logger.info("[ParallelEmbedder] Post-embed GPU cleanup...")
            gc.collect()
            # Lichte cleanup, niet full cleanup want we willen workers behouden
            for gpu_idx in available_gpus:
                self._cleanup_gpu(gpu_idx)
        
        duration = time.time() - start_time
        texts_per_sec = n_texts / duration if duration > 0 else 0
        logger.info(
            f"[ParallelEmbedder] Parallel embed complete: {n_texts} texts in {duration:.2f}s "
            f"({texts_per_sec:.1f} texts/sec) over {len(available_gpus)} GPUs"
        )
        
        return combined
    
    def _embed_on_cpu(self, texts: List[str]) -> np.ndarray:
        """Fallback: embed op CPU."""
        logger.info(f"[ParallelEmbedder] CPU embedding {len(texts)} texts...")
        
        # Gebruik of maak CPU model
        model = SentenceTransformer(self._model_name, device="cpu")
        
        emb = model.encode(
            texts,
            batch_size=16,  # Kleinere batch op CPU
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        
        return np.asarray(emb, dtype="float32")
    
    def unload_all_models(self):
        """Unload alle GPU models om geheugen vrij te maken."""
        logger.info("[ParallelEmbedder] Unloading all GPU models...")
        
        for gpu_idx, worker in list(self._workers.items()):
            try:
                with worker.lock:
                    del worker.model
                    worker.model = None
                self._cleanup_gpu(gpu_idx)
            except Exception as e:
                logger.warning(f"[ParallelEmbedder] Error unloading GPU {gpu_idx}: {e}")
        
        self._workers.clear()
        gc.collect()
        
        logger.info("[ParallelEmbedder] All models unloaded")
    
    def get_status(self) -> Dict[str, Any]:
        """Krijg status van de embedder."""
        return {
            "model_name": self._model_name,
            "embedding_dim": self._embedding_dim,
            "loaded_workers": list(self._workers.keys()),
            "max_parallel_gpus": MAX_PARALLEL_GPUS,
            "min_free_mb": MIN_FREE_MB_FOR_EMBED,
            "available_gpus": self._get_available_gpus(),
        }


# Singleton instance
parallel_embedder = ParallelEmbedder()


# Convenience functions
def embed_texts_parallel(
    texts: List[str],
    cleanup_before: bool = True,
    cleanup_after: bool = True,
) -> np.ndarray:
    """
    Embed teksten met parallel multi-GPU processing.
    
    Args:
        texts: Lijst van teksten om te embedden
        cleanup_before: GPU cleanup voor embedding (default True)
        cleanup_after: GPU cleanup na embedding (default True)
    
    Returns:
        Numpy array van embeddings
    """
    return parallel_embedder.embed(
        texts,
        cleanup_before=cleanup_before,
        cleanup_after=cleanup_after,
    )


def get_embedder_status() -> Dict[str, Any]:
    """Krijg status van de parallel embedder."""
    return parallel_embedder.get_status()


def unload_embedder_models():
    """Unload alle embedder models."""
    parallel_embedder.unload_all_models()


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Parallel Embedder Test ===")
    
    # Status
    status = get_embedder_status()
    print(f"\nStatus: {status}")
    
    # Test embedding
    test_texts = [
        "Dit is een test document over financiële rapportages.",
        "De jaarrekening van 2024 toont een omzet van 1 miljoen euro.",
        "Klantreviews zijn essentieel voor de reputatie van het bedrijf.",
        "De coaching sessie ging over persoonlijke ontwikkeling.",
        "Offerte voor website ontwikkeling en onderhoud.",
    ] * 10  # 50 teksten
    
    print(f"\nEmbedding {len(test_texts)} texts...")
    start = time.time()
    embeddings = embed_texts_parallel(test_texts)
    duration = time.time() - start
    
    print(f"\nResult:")
    print(f"  Shape: {embeddings.shape}")
    print(f"  Duration: {duration:.2f}s")
    print(f"  Texts/sec: {len(test_texts)/duration:.1f}")
    
    # Cleanup
    print("\nUnloading models...")
    unload_embedder_models()
    
    print("\n=== Test Complete ===")
