"""
GPU Task Manager - Hybride GPU orchestratie met cleanup.

Zorgt dat Ollama (LLM) en PyTorch (embedding/reranking) taken
om de beurt of parallel kunnen draaien met GPU geheugen management.

Strategie:
- Ollama: Gebruikt alle beschikbare GPU's, keep_alive=0 na gebruik
- PyTorch: Lazy load, cleanup na gebruik, kiest beste vrije GPU
"""

from __future__ import annotations

import gc
import os
import subprocess
import time
import logging
from enum import Enum
from threading import Lock, RLock
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Probeer torch te importeren, maar fail gracefully
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch niet beschikbaar - GPU management beperkt")


class TaskType(Enum):
    """Type GPU-intensieve taken."""
    IDLE = "idle"
    OLLAMA_ANALYSIS = "ollama_analysis"      # Doc analyzer via 70B
    OLLAMA_ENRICHMENT = "ollama_enrichment"  # Context enrichment via 8B
    PYTORCH_EMBEDDING = "pytorch_embedding"   # BGE-m3 embedding
    PYTORCH_RERANKING = "pytorch_reranking"   # BGE reranker


@dataclass
class GPUInfo:
    """Info over een GPU."""
    index: int
    name: str
    total_memory_mb: int
    free_memory_mb: int
    used_memory_mb: int
    utilization_pct: int


@dataclass
class TaskInfo:
    """Info over huidige taak."""
    task_type: TaskType
    doc_id: Optional[str]
    started_at: datetime
    gpu_indices: List[int]


class GPUManager:
    """
    Singleton GPU Manager voor hybride GPU orchestratie.
    
    Gebruik:
        gpu_manager = GPUManager()
        
        # Acquire voor een taak
        gpu_manager.acquire(TaskType.PYTORCH_EMBEDDING, doc_id="doc123")
        try:
            # Doe GPU werk
            embeddings = model.encode(texts)
        finally:
            gpu_manager.release()
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._task_lock = RLock()
        self._current_task: Optional[TaskInfo] = None
        self._last_task_type: Optional[TaskType] = None  # Track vorig taak type voor cleanup
        self._ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._gpu_count = self._detect_gpu_count()
        self._auto_cleanup_on_switch = True  # Automatisch cleanup bij taak switch
        self._initialized = True
        
        logger.info(f"[GPU Manager] Initialized with {self._gpu_count} GPU's (auto_cleanup=True)")
    
    def _detect_gpu_count(self) -> int:
        """Detecteer aantal GPU's."""
        if not TORCH_AVAILABLE:
            return 0
        try:
            return torch.cuda.device_count()
        except Exception:
            return 0
    
    def get_gpu_info(self) -> List[GPUInfo]:
        """Haal info op over alle GPU's via nvidia-smi."""
        try:
            result = subprocess.run(
                [
                    'nvidia-smi',
                    '--query-gpu=index,name,memory.total,memory.free,memory.used,utilization.gpu',
                    '--format=csv,nounits,noheader'
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            gpus = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 6:
                    gpus.append(GPUInfo(
                        index=int(parts[0]),
                        name=parts[1],
                        total_memory_mb=int(parts[2]),
                        free_memory_mb=int(parts[3]),
                        used_memory_mb=int(parts[4]),
                        utilization_pct=int(parts[5]) if parts[5].isdigit() else 0,
                    ))
            return gpus
        except Exception as e:
            logger.warning(f"[GPU Manager] nvidia-smi failed: {e}")
            return []
    
    def get_best_gpu(self, min_free_mb: int = 2000) -> int:
        """
        Vind de GPU met meeste vrije geheugen.
        
        Args:
            min_free_mb: Minimum vrij geheugen vereist (default 2GB)
        
        Returns:
            GPU index, of -1 als geen geschikte GPU gevonden
        """
        gpus = self.get_gpu_info()
        if not gpus:
            return -1
        
        # Filter op minimum geheugen
        suitable = [g for g in gpus if g.free_memory_mb >= min_free_mb]
        if not suitable:
            logger.warning(f"[GPU Manager] Geen GPU met >= {min_free_mb}MB vrij")
            return -1
        
        # Kies GPU met meeste vrije geheugen
        best = max(suitable, key=lambda g: g.free_memory_mb)
        logger.info(f"[GPU Manager] Beste GPU: {best.index} ({best.name}) met {best.free_memory_mb}MB vrij")
        return best.index
    
    def get_free_gpus(self, min_free_mb: int = 6000, max_temp: int = 80) -> List[int]:
        """
        Krijg alle GPU's die voldoende vrij geheugen en lage temperatuur hebben.
        
        Args:
            min_free_mb: Minimum vrij geheugen vereist (default 6GB voor LLM)
            max_temp: Maximum temperatuur in °C (default 80°C)
        
        Returns:
            Lijst van GPU indices, gesorteerd op vrij geheugen (meeste eerst)
        """
        gpus = self.get_gpu_info()
        if not gpus:
            return []
        
        # Haal temperaturen op
        temps = self.get_gpu_temperatures()
        
        # Filter op geheugen en temperatuur
        suitable = []
        for g in gpus:
            temp = temps.get(g.index, 0)
            if g.free_memory_mb >= min_free_mb:
                if temp == 0 or temp <= max_temp:  # 0 = geen temp data
                    suitable.append((g.index, g.free_memory_mb, temp))
                else:
                    logger.warning(f"[GPU Manager] GPU {g.index} te warm: {temp}°C > {max_temp}°C")
        
        # Sorteer op vrij geheugen (meeste eerst)
        suitable.sort(key=lambda x: x[1], reverse=True)
        result = [idx for idx, _, _ in suitable]
        
        logger.info(f"[GPU Manager] {len(result)} vrije GPU's gevonden: {result}")
        return result
    
    def get_gpu_temperatures(self) -> Dict[int, int]:
        """
        Haal GPU temperaturen op via nvidia-smi.
        
        Returns:
            Dict van GPU index naar temperatuur in °C
        """
        try:
            result = subprocess.run(
                [
                    'nvidia-smi',
                    '--query-gpu=index,temperature.gpu',
                    '--format=csv,nounits,noheader'
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            temps = {}
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 2:
                    try:
                        idx = int(parts[0])
                        temp = int(parts[1])
                        temps[idx] = temp
                    except ValueError:
                        continue
            return temps
        except Exception as e:
            logger.warning(f"[GPU Manager] Temperature query failed: {e}")
            return {}
    
    def wait_for_gpu_cooldown(self, gpu_index: int, max_temp: int = 75, timeout_sec: int = 60) -> bool:
        """
        Wacht tot GPU onder max temperatuur is.
        
        Args:
            gpu_index: GPU index om te checken
            max_temp: Maximum temperatuur in °C
            timeout_sec: Maximum wachttijd in seconden
        
        Returns:
            True als GPU afgekoeld is, False bij timeout
        """
        start = time.time()
        while time.time() - start < timeout_sec:
            temps = self.get_gpu_temperatures()
            current_temp = temps.get(gpu_index, 0)
            
            if current_temp == 0 or current_temp <= max_temp:
                logger.info(f"[GPU Manager] GPU {gpu_index} is koel genoeg: {current_temp}°C")
                return True
            
            logger.info(f"[GPU Manager] GPU {gpu_index} nog te warm: {current_temp}°C, wacht...")
            time.sleep(5)
        
        logger.warning(f"[GPU Manager] Timeout wachten op GPU {gpu_index} cooldown")
        return False
    
    def get_coolest_gpu(self, min_free_mb: int = 6000) -> int:
        """
        Vind de GPU met laagste temperatuur die voldoende geheugen heeft.
        
        Args:
            min_free_mb: Minimum vrij geheugen vereist
        
        Returns:
            GPU index, of -1 als geen geschikte GPU gevonden
        """
        gpus = self.get_gpu_info()
        temps = self.get_gpu_temperatures()
        
        if not gpus:
            return -1
        
        # Filter op geheugen en sorteer op temperatuur
        suitable = []
        for g in gpus:
            if g.free_memory_mb >= min_free_mb:
                temp = temps.get(g.index, 100)  # Hoog default als geen data
                suitable.append((g.index, temp, g.free_memory_mb))
        
        if not suitable:
            return -1
        
        # Sorteer op temperatuur (laagste eerst)
        suitable.sort(key=lambda x: x[1])
        best_idx = suitable[0][0]
        best_temp = suitable[0][1]
        
        logger.info(f"[GPU Manager] Koelste GPU: {best_idx} ({best_temp}°C)")
        return best_idx
    
    def cleanup_pytorch(self):
        """Maak PyTorch GPU geheugen vrij."""
        if not TORCH_AVAILABLE:
            return
        
        logger.info("[GPU Manager] Cleaning PyTorch GPU memory...")
        
        # Garbage collection
        gc.collect()
        
        # CUDA cache cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        # Extra GC rounds
        for _ in range(3):
            gc.collect()
        
        logger.info("[GPU Manager] PyTorch cleanup complete")
    
    def unload_ollama_models(self, models: Optional[List[str]] = None):
        """
        Unload Ollama modellen om GPU geheugen vrij te maken.
        
        Args:
            models: Specifieke modellen om te unloaden, of None voor alle
        """
        if models is None:
            models = ["llama3.1:70b", "llama3.1:8b"]
        
        logger.info(f"[GPU Manager] Unloading Ollama models: {models}")
        
        for model in models:
            try:
                result = subprocess.run(
                    ["ollama", "stop", model],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    logger.info(f"[GPU Manager] Stopped {model}")
                else:
                    logger.debug(f"[GPU Manager] Model {model} was not running")
            except subprocess.TimeoutExpired:
                logger.warning(f"[GPU Manager] Timeout stopping {model}")
            except FileNotFoundError:
                logger.warning("[GPU Manager] ollama CLI not found")
                break
            except Exception as e:
                logger.warning(f"[GPU Manager] Error stopping {model}: {e}")
        
        # Wacht even op GPU vrijgave
        time.sleep(1)
    
    def full_cleanup(self):
        """Volledige GPU cleanup - zowel Ollama als PyTorch."""
        logger.info("[GPU Manager] Full GPU cleanup starting...")
        self.unload_ollama_models()
        self.cleanup_pytorch()
        time.sleep(1)
        logger.info("[GPU Manager] Full cleanup complete")
    
    def _is_ollama_task(self, task_type: TaskType) -> bool:
        """Check of taak type een Ollama taak is."""
        return task_type in [TaskType.OLLAMA_ANALYSIS, TaskType.OLLAMA_ENRICHMENT]
    
    def _is_pytorch_task(self, task_type: TaskType) -> bool:
        """Check of taak type een PyTorch taak is."""
        return task_type in [TaskType.PYTORCH_EMBEDDING, TaskType.PYTORCH_RERANKING]
    
    def _needs_task_switch_cleanup(self, new_task: TaskType) -> str:
        """
        Bepaal of cleanup nodig is bij taakwisseling.
        
        Returns:
            'ollama' - unload ollama models
            'pytorch' - cleanup pytorch
            'full' - volledige cleanup
            'none' - geen cleanup nodig
        """
        if self._last_task_type is None:
            return 'none'
        
        # Van Ollama naar PyTorch: unload Ollama models
        if self._is_ollama_task(self._last_task_type) and self._is_pytorch_task(new_task):
            return 'ollama'
        
        # Van PyTorch naar Ollama: cleanup PyTorch geheugen
        if self._is_pytorch_task(self._last_task_type) and self._is_ollama_task(new_task):
            return 'pytorch'
        
        return 'none'

    def acquire(
        self,
        task_type: TaskType,
        doc_id: Optional[str] = None,
        cleanup_before: bool = False,
    ) -> bool:
        """
        Acquire GPU resources voor een taak.
        
        Doet automatisch cleanup bij taakwisseling:
        - Ollama → PyTorch: unload Ollama models voor GPU ruimte
        - PyTorch → Ollama: cleanup PyTorch geheugen
        
        Args:
            task_type: Type taak waarvoor GPU nodig is
            doc_id: Document ID (voor logging/status)
            cleanup_before: Doe extra cleanup voordat taak start
        
        Returns:
            True als acquire succesvol
        """
        with self._task_lock:
            # Automatische cleanup bij taakwisseling
            if self._auto_cleanup_on_switch:
                cleanup_type = self._needs_task_switch_cleanup(task_type)
                if cleanup_type == 'ollama':
                    logger.info(f"[GPU Manager] Task switch: Ollama → PyTorch, unloading Ollama models...")
                    self.unload_ollama_models()
                elif cleanup_type == 'pytorch':
                    logger.info(f"[GPU Manager] Task switch: PyTorch → Ollama, cleaning PyTorch memory...")
                    self.cleanup_pytorch()
                elif cleanup_type == 'full':
                    logger.info(f"[GPU Manager] Task switch: full cleanup required...")
                    self.full_cleanup()
            
            # Extra cleanup als expliciet gevraagd
            if cleanup_before:
                self.full_cleanup()
            
            # Bepaal welke GPU's gebruikt worden
            gpu_indices = []
            if task_type in [TaskType.PYTORCH_EMBEDDING, TaskType.PYTORCH_RERANKING]:
                best_gpu = self.get_best_gpu()
                if best_gpu >= 0:
                    gpu_indices = [best_gpu]
            elif task_type in [TaskType.OLLAMA_ANALYSIS, TaskType.OLLAMA_ENRICHMENT]:
                # Ollama beheert zelf GPU's
                gpu_indices = list(range(self._gpu_count))
            
            self._current_task = TaskInfo(
                task_type=task_type,
                doc_id=doc_id,
                started_at=datetime.utcnow(),
                gpu_indices=gpu_indices,
            )
            
            # Update last task type voor volgende keer
            self._last_task_type = task_type
            
            logger.info(
                f"[GPU Manager] Acquired for {task_type.value} "
                f"(doc={doc_id}, gpus={gpu_indices})"
            )
            return True
    
    def release(self, cleanup_after: bool = True):
        """
        Release GPU resources na een taak.
        
        Args:
            cleanup_after: Doe cleanup na release
        """
        with self._task_lock:
            if self._current_task:
                task_type = self._current_task.task_type
                doc_id = self._current_task.doc_id
                duration = (datetime.utcnow() - self._current_task.started_at).total_seconds()
                
                logger.info(
                    f"[GPU Manager] Released {task_type.value} "
                    f"(doc={doc_id}, duration={duration:.1f}s)"
                )
                
                self._current_task = None
            
            if cleanup_after:
                self.cleanup_pytorch()
    
    def get_current_task(self) -> Optional[TaskInfo]:
        """Haal huidige taak info op."""
        with self._task_lock:
            return self._current_task
    
    def get_status(self) -> Dict[str, Any]:
        """
        Haal volledige GPU status op.
        
        Returns:
            Dict met GPU info en huidige taak
        """
        gpus = self.get_gpu_info()
        current = self.get_current_task()
        
        return {
            "gpu_count": self._gpu_count,
            "gpus": [
                {
                    "index": g.index,
                    "name": g.name,
                    "total_mb": g.total_memory_mb,
                    "free_mb": g.free_memory_mb,
                    "used_mb": g.used_memory_mb,
                    "utilization_pct": g.utilization_pct,
                }
                for g in gpus
            ],
            "current_task": {
                "type": current.task_type.value if current else "idle",
                "doc_id": current.doc_id if current else None,
                "started_at": current.started_at.isoformat() if current else None,
                "gpu_indices": current.gpu_indices if current else [],
            },
        }


# Singleton instance
gpu_manager = GPUManager()


# Context manager voor eenvoudig gebruik
class GPUTask:
    """
    Context manager voor GPU taken.
    
    Gebruik:
        with GPUTask(TaskType.PYTORCH_EMBEDDING, doc_id="doc123"):
            embeddings = model.encode(texts)
    """
    
    def __init__(
        self,
        task_type: TaskType,
        doc_id: Optional[str] = None,
        cleanup_before: bool = False,
        cleanup_after: bool = True,
    ):
        self.task_type = task_type
        self.doc_id = doc_id
        self.cleanup_before = cleanup_before
        self.cleanup_after = cleanup_after
    
    def __enter__(self):
        gpu_manager.acquire(
            self.task_type,
            doc_id=self.doc_id,
            cleanup_before=self.cleanup_before,
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        gpu_manager.release(cleanup_after=self.cleanup_after)
        return False  # Don't suppress exceptions


# Helper functies
def get_pytorch_device(prefer_gpu: bool = True, min_free_mb: int = 2000) -> str:
    """
    Krijg het beste PyTorch device string.
    
    Args:
        prefer_gpu: Probeer GPU te gebruiken
        min_free_mb: Minimum vrij geheugen voor GPU
    
    Returns:
        Device string zoals "cuda:5" of "cpu"
    """
    if not prefer_gpu or not TORCH_AVAILABLE:
        return "cpu"
    
    if not torch.cuda.is_available():
        return "cpu"
    
    best_gpu = gpu_manager.get_best_gpu(min_free_mb)
    if best_gpu >= 0:
        return f"cuda:{best_gpu}"
    
    return "cpu"


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    print("=== GPU Manager Test ===")
    print(f"GPU Count: {gpu_manager._gpu_count}")
    print("\nGPU Status:")
    status = gpu_manager.get_status()
    for gpu in status["gpus"]:
        print(f"  GPU {gpu['index']}: {gpu['name']}")
        print(f"    Memory: {gpu['used_mb']}MB / {gpu['total_mb']}MB (free: {gpu['free_mb']}MB)")
        print(f"    Utilization: {gpu['utilization_pct']}%")
    
    print(f"\nBest GPU for PyTorch: {get_pytorch_device()}")
    
    print("\n--- Testing context manager ---")
    with GPUTask(TaskType.PYTORCH_EMBEDDING, doc_id="test_doc"):
        print(f"Current task: {gpu_manager.get_current_task()}")
    print(f"After release: {gpu_manager.get_current_task()}")
