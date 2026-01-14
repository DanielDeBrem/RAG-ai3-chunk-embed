"""
AI-3 Configuration Settings
Configuratie voor AI-4 LLM routing en GPU pinning
"""

import os

# ============================================
# AI-4 LLM70 Integration
# ============================================

# AI-4 base URL voor 70B LLM calls
AI4_LLM70_BASE_URL = os.getenv("AI4_LLM70_BASE_URL", "http://10.0.1.227:8000")

# Timeout voor AI-4 calls (seconden)
AI4_LLM70_TIMEOUT = float(os.getenv("AI4_LLM70_TIMEOUT", "180"))

# Enable/disable AI-4 routing (voor testing)
AI4_LLM70_ENABLED = os.getenv("AI4_LLM70_ENABLED", "true").lower() == "true"

# Fallback gedrag als AI-4 niet bereikbaar
AI4_FALLBACK_TO_HEURISTICS = os.getenv("AI4_FALLBACK_TO_HEURISTICS", "true").lower() == "true"

# ============================================
# GPU Pinning Configuration
# ============================================

# GPU voor embedder (resident)
AI3_EMBED_GPU = os.getenv("AI3_EMBED_GPU", "0")

# GPU voor reranker (resident)
AI3_RERANK_GPU = os.getenv("AI3_RERANK_GPU", "1")

# GPU's voor worker pool (future: llama3.1:8b)
AI3_WORKER_GPUS = os.getenv("AI3_WORKER_GPUS", "2,3,4,5,6,7")

# ============================================
# Service Ports
# ============================================

DATAFACTORY_PORT = int(os.getenv("DATAFACTORY_PORT", "9000"))
DOC_ANALYZER_PORT = int(os.getenv("DOC_ANALYZER_PORT", "9100"))
RERANKER_PORT = int(os.getenv("RERANKER_PORT", "9200"))
EMBEDDING_SERVICE_PORT = int(os.getenv("EMBEDDING_SERVICE_PORT", "7997"))

# ============================================
# Feature Flags
# ============================================

# Auto-unload models na gebruik (voor 70B-first stability)
AUTO_UNLOAD_EMBEDDER = os.getenv("AUTO_UNLOAD_EMBEDDER", "true").lower() == "true"
AUTO_UNLOAD_RERANKER = os.getenv("AUTO_UNLOAD_RERANKER", "true").lower() == "true"

# Disable startup warmup (70B-first: geen GPU pre-loading)
DISABLE_STARTUP_EMBED_WARMUP = os.getenv("DISABLE_STARTUP_EMBED_WARMUP", "true").lower() == "true"
DISABLE_STARTUP_CORPUS_LOAD = os.getenv("DISABLE_STARTUP_CORPUS_LOAD", "true").lower() == "true"

# ============================================
# Model Names
# ============================================

EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

# ============================================
# Helper Functions
# ============================================

def get_embed_cuda_visible_devices() -> str:
    """Get CUDA_VISIBLE_DEVICES string for embedder."""
    return AI3_EMBED_GPU

def get_rerank_cuda_visible_devices() -> str:
    """Get CUDA_VISIBLE_DEVICES string for reranker."""
    return AI3_RERANK_GPU

def get_worker_cuda_visible_devices() -> str:
    """Get CUDA_VISIBLE_DEVICES string for worker pool."""
    return AI3_WORKER_GPUS

def get_ai4_llm70_endpoint(path: str) -> str:
    """
    Bouw volledige AI-4 endpoint URL.
    
    Args:
        path: endpoint path (e.g., '/llm70/chat' or '/llm70/warmup')
    
    Returns:
        Full URL (e.g., 'http://10.0.1.227:8000/llm70/chat')
    """
    base = AI4_LLM70_BASE_URL.rstrip('/')
    path = path.lstrip('/')
    return f"{base}/{path}"

def log_config():
    """Log huidige configuratie (voor debugging)."""
    print("=" * 60)
    print("AI-3 Configuration")
    print("=" * 60)
    print(f"AI4_LLM70_BASE_URL: {AI4_LLM70_BASE_URL}")
    print(f"AI4_LLM70_ENABLED: {AI4_LLM70_ENABLED}")
    print(f"AI4_FALLBACK_TO_HEURISTICS: {AI4_FALLBACK_TO_HEURISTICS}")
    print(f"AI3_EMBED_GPU: {AI3_EMBED_GPU}")
    print(f"AI3_RERANK_GPU: {AI3_RERANK_GPU}")
    print(f"AI3_WORKER_GPUS: {AI3_WORKER_GPUS}")
    print(f"DATAFACTORY_PORT: {DATAFACTORY_PORT}")
    print(f"DOC_ANALYZER_PORT: {DOC_ANALYZER_PORT}")
    print(f"RERANKER_PORT: {RERANKER_PORT}")
    print("=" * 60)
