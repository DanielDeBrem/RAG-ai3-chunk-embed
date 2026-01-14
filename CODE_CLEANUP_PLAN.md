# Code Cleanup Plan: Dedicated GPU per Taak

**Doel:** Maximale stabiliteit met dedicated GPU's
**Strategie:** 1 GPU embedding, 1 GPU reranking, 6 GPU's voor Ollama enrichment

---

## 🎯 OPTIMALE GPU ALLOCATIE

```
GPU 0: DataFactory Embedding (BAAI/bge-m3) - dedicated
GPU 1: Reranker (BAAI/bge-reranker-v2-m3) - dedicated
GPU 2-7: Ollama Enrichment (6x llama3.1:8b parallel) - dedicated
```

**Waarom deze verdeling:**
- ✅ Enrichment is bottleneck (2-5 minuten voor 150 chunks)
- ✅ 6 GPU's voor enrichment = maximale speedup waar nodig
- ✅ Embedding + reranking zijn snel (1-30 seconden), 1 GPU genoeg

---

## 🗑️ CODE TE VERWIJDEREN/VEREENVOUDIGEN

### 1. **parallel_embedder.py - Multi-GPU Logic (NIET NODIG)**

**Reden:** Met CUDA_VISIBLE_DEVICES=0 ziet DataFactory alleen GPU 0, multi-GPU werkt niet

**Te verwijderen:**
```python
# parallel_embedder.py

❌ class ParallelEmbedder - hele class
❌ def _get_available_gpus() - GPU 6-7 preference logic
❌ def _distribute_texts() - tekst verdeling over GPU's
❌ def _embed_batch_on_gpu() - per-GPU embedding
❌ ThreadPoolExecutor multi-GPU logic

✅ BEHOUDEN: Fallback naar CPU embedding
```

**Vervangen door:**
```python
# Simpele single-GPU embedder in app.py
def embed_texts(texts: List[str]) -> np.ndarray:
    """Embed op dedicated GPU 0 (via CUDA_VISIBLE_DEVICES)"""
    init_model()  # Load op GPU 0
    return model.encode(texts, batch_size=32, normalize_embeddings=True)
```

**Impact:**
- ❌ Verliest: Multi-GPU embedding capability (maar werkt toch niet met pinning!)
- ✅ Wint: Simpelere code, beter onderhoudbaar
- ✅ Performance: Identiek (was toch al 1 GPU)

---

### 2. **gpu_manager.py - Cross-GPU Features (BEPERKT NUTTIG)**

**Reden:** Met CUDA_VISIBLE_DEVICES pinning zijn cross-GPU features niet relevant

**Te verwijderen:**
```python
# gpu_manager.py

❌ def _needs_task_switch_cleanup() - cross-task cleanup (niet nodig)
❌ self._auto_cleanup_on_switch = True - tussen-process cleanup
❌ def get_free_gpus(min_free_mb, max_temp) - multi-GPU selectie
❌ def get_coolest_gpu() - temperature-based GPU keuze
❌ def wait_for_gpu_cooldown() - wachten op cooldown

✅ BEHOUDEN:
   - def cleanup_pytorch() - binnen-process cleanup
   - def unload_ollama_models() - voor manual cleanup
   - def get_gpu_info() - monitoring
   - def get_gpu_temperatures() - monitoring
```

**Vervangen door:**
```python
# Simplified gpu_manager.py
class SimpleGPUManager:
    """Simpele GPU manager voor monitoring en cleanup (single GPU per process)"""
    
    def cleanup_pytorch(self):
        """PyTorch cache cleanup (binnen process)"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    
    def get_gpu_info(self) -> Dict:
        """GPU status voor monitoring"""
        # nvidia-smi query (blijft werken)
    
    def unload_ollama_models(self):
        """Manual Ollama cleanup indien nodig"""
        # ollama stop commands
```

**Impact:**
- ❌ Verliest: Cross-GPU orchestration (niet nodig met pinning!)
- ✅ Wint: Veel simpeler, minder bugs
- ✅ Performance: Identiek

---

### 3. **app.py - Aggressive Ollama Cleanup (TE COMPLEX)**

**Huidige situatie:**
```python
# app.py::ingest_text_into_index()

# === AGRESSIEF GPU cleanup (voor embedding) ===
print(f"[AI-3] AGRESSIEF GPU cleanup (voor embedding)...")

# Methode 1: Kill alle ollama runner processes via psutil
killed_count = 0
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = ' '.join(proc.info['cmdline'] or [])
        if 'ollama' in cmdline.lower() and 'runner' in cmdline.lower():
            psutil.Process(proc.info['pid']).kill()
            killed_count += 1
    except:
        pass

time.sleep(3)  # OS cleanup tijd
gpu_manager.cleanup_pytorch()
time.sleep(2)
```

**Probleem:** 
- ❌ Te agressief (killed Ollama processes die dedicated GPU's hebben!)
- ❌ Nodig omdat Ollama en PyTorch GPU's delen (niet met dedicated setup!)

**Vervangen door:**
```python
# app.py - met dedicated GPU's

# Geen aggressive cleanup nodig!
# Ollama draait op GPU 2-7, PyTorch op GPU 0
# GEEN conflicts!

# Alleen binnen-process PyTorch cleanup:
def prepare_for_embedding():
    """Light cleanup voor embedding"""
    gc.collect()
    torch.cuda.empty_cache()  # Alleen GPU 0
```

**Impact:**
- ❌ Verliest: "Oplossing" voor GPU conflicts
- ✅ Wint: Geen conflicts meer! Ollama blijft draaien
- ✅ Performance: Sneller (geen 3-5s kill+wait)

---

### 4. **GPUTask Context Manager (BEPERKT NUTTIG)**

**Huidige situatie:**
```python
# gpu_manager.py
with GPUTask(TaskType.PYTORCH_EMBEDDING, doc_id="doc123"):
    embeddings = model.encode(texts)
# → Auto cleanup + task tracking
```

**Met dedicated GPU's:**
```python
# Simpeler:
def embed_texts(texts):
    # Altijd GPU 0 (via CUDA_VISIBLE_DEVICES)
    try:
        return model.encode(texts)
    finally:
        cleanup_pytorch()  # Simple cleanup
```

**Te verwijderen:**
```python
❌ class GPUTask (context manager)
❌ class TaskType (enum)
❌ def acquire() / release() in gpu_manager
❌ Task tracking infrastructure
```

**Vervangen door:**
```python
# Simple cleanup helper
def with_cleanup(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            gc.collect()
            torch.cuda.empty_cache()
    return wrapper

@with_cleanup
def embed_texts(texts):
    return model.encode(texts)
```

---

### 5. **gpu_phase_lock.py (FILE-BASED LOCK - NIET MEER NODIG)**

**Huidige situatie:**
```python
# gpu_phase_lock.py
with gpu_exclusive_lock("embedding", doc_id="doc123", timeout_sec=900):
    embeddings = model.encode(texts)
```

**Reden verwijderen:**
- ❌ File-based lock tussen processes
- ❌ Nodig was voor GPU conflicts
- ✅ Dedicated GPU's = geen conflicts = geen lock nodig!

**Vervangen door:**
- Niets! Remove file en alle imports

**Impact:**
- ❌ Verliest: Cross-process synchronization
- ✅ Wint: Eenvoudiger, sneller (geen disk I/O voor locks)
- ✅ Performance: Geen lock overhead

---

## 🔧 NIEUWE SETUP: DEDICATED GPU's

### **start_AI3_optimized.sh (NIEUWE VERSIE)**

```bash
#!/bin/bash
# Optimized AI-3 Startup: Dedicated GPU per taak
set -e

echo "=========================================="
echo "AI-3 Optimized Startup"
echo "GPU 0: Embedding, GPU 1: Reranking"
echo "GPU 2-7: Ollama Enrichment (6x)"
echo "=========================================="

# === STAP 1: Stop oude processen ===
pkill -f "uvicorn.*9000" 2>/dev/null || true
pkill -f "uvicorn.*9200" 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
sleep 2

# === STAP 2: Start 6 Ollama instances (GPU 2-7) ===
echo "Starting 6 Ollama instances (GPU 2-7)..."
for i in {2..7}; do
    PORT=$((11434 + i - 2))  # Ports 11434-11439
    echo "  GPU $i -> port $PORT"
    CUDA_VISIBLE_DEVICES=$i \
    OLLAMA_HOST="0.0.0.0:$PORT" \
    OLLAMA_KEEP_ALIVE="30m" \
        nohup ollama serve > "logs/ollama_gpu${i}.log" 2>&1 &
    sleep 0.5
done

sleep 3

# === STAP 3: Start DataFactory met Embedder (GPU 0) ===
echo "Starting DataFactory + Embedder (GPU 0)..."
# DataFactory (app.py) bevat de embedder!
# SentenceTransformer wordt geladen binnen app.py op GPU 0
CUDA_VISIBLE_DEVICES=0 \
OLLAMA_MULTI_GPU=true \
OLLAMA_NUM_INSTANCES=6 \
OLLAMA_BASE_PORT=11434 \
    nohup uvicorn app:app --host 0.0.0.0 --port 9000 \
    > logs/datafactory.log 2>&1 &

sleep 3

# === STAP 4: Start Reranker (GPU 1) ===
echo "Starting Reranker (GPU 1)..."
CUDA_VISIBLE_DEVICES=1 \
    nohup uvicorn reranker_service:app --host 0.0.0.0 --port 9200 \
    > logs/reranker.log 2>&1 &

sleep 2

# === STAP 5: Health checks ===
echo ""
echo "Health Checks:"
curl -s http://localhost:9000/health && echo "  ✓ DataFactory"
curl -s http://localhost:9200/health && echo "  ✓ Reranker"
for i in {0..5}; do
    PORT=$((11434 + i))
    curl -s "http://localhost:$PORT/api/tags" > /dev/null && echo "  ✓ Ollama GPU $((i+2))"
done

echo ""
echo "=========================================="
echo "GPU Status:"
nvidia-smi --query-gpu=index,memory.used,temperature.gpu \
    --format=csv,noheader,nounits | while IFS=, read -r idx used temp; do
    echo "  GPU $idx: ${used}MB used, ${temp}°C"
done

echo ""
echo "✅ AI-3 Ready!"
echo "   DataFactory + Embedding: GPU 0 (port 9000)"
echo "   Reranker: GPU 1 (port 9200)"
echo "   Ollama Enrichment: GPU 2-7 (ports 11434-11439)"
echo ""
echo "Services:"
echo "   http://localhost:9000 - DataFactory (includes embedding)"
echo "   http://localhost:9200 - Reranker"
echo "=========================================="
```

---

### **app.py - Simplified (CLEANUP)**

**Verwijderen:**
```python
❌ from parallel_embedder import parallel_embedder, embed_texts_parallel
❌ from gpu_phase_lock import gpu_exclusive_lock
❌ Aggressive Ollama cleanup code (psutil kill logic)
❌ Multi-GPU embedding logic
❌ GPUTask context managers
```

**Behouden & Vereenvoudigen:**
```python
✅ Basic SentenceTransformer op GPU 0
✅ Simple PyTorch cleanup (torch.cuda.empty_cache)
✅ Contextual enrichment (6x Ollama parallel)
✅ FAISS indexing
✅ Status reporting
```

**Nieuwe embed_texts():**
```python
def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Embed teksten op GPU 0 (via CUDA_VISIBLE_DEVICES).
    Simpel en stabiel - geen multi-GPU complexity.
    """
    global model
    if model is None:
        init_model()  # Load op GPU 0
    
    try:
        emb = model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(emb, dtype="float32")
    except torch.cuda.OutOfMemoryError:
        # Fallback naar CPU
        logger.warning("GPU 0 OOM, fallback to CPU")
        model = model.to("cpu")
        emb = model.encode(texts, batch_size=16)
        return np.asarray(emb, dtype="float32")
    finally:
        # Light cleanup
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
```

---

### **contextual_enricher.py - GEEN WIJZIGINGEN**

**Blijft perfect werken:**
```python
✅ 6 Ollama instances op GPU 2-7
✅ Round-robin load balancing
✅ ThreadPoolExecutor parallel processing
✅ Keep-alive 30m voor snelheid
```

**Dit is al optimaal!** Enrichment krijgt 6 GPU's = maximale speedup.

---

### **reranker.py - Simplified**

**Verwijderen:**
```python
❌ from gpu_phase_lock import gpu_exclusive_lock
❌ from gpu_manager import gpu_manager, GPUTask
❌ Complex GPU selection logic
```

**Vervangen door:**
```python
# reranker.py - simplified
class BGEReranker:
    def __init__(self):
        # Load op GPU 1 (via CUDA_VISIBLE_DEVICES)
        self.model = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda")
    
    def rerank(self, query, items, top_k=10):
        try:
            scores = self.model.predict([(query, it.text) for it in items])
            # ... scoring logic
        finally:
            # Light cleanup
            gc.collect()
            torch.cuda.empty_cache()
```

---

## 📊 PERFORMANCE VERWACHTING

### **Met Dedicated GPU Setup:**

```
Document Ingest (150 chunks):

FASE 1: Analyse          20s → AI-4 of heuristic
FASE 2: Chunking          2s → CPU
FASE 3: Enrichment      120s → 6 GPU's parallel (was 180s)
FASE 4: Embedding        15s → GPU 0 (was 25s, beter model warmup)
FASE 5: Storage           3s → CPU

Totaal: ~160 seconden (~2.7 minuten)
Verbetering: 30% sneller door stabielere execution
```

**Waarom sneller:**
- ✅ Geen Ollama kill/reload overhead (3-5s)
- ✅ Ollama models blijven warm (30m keep-alive)
- ✅ Geen GPU conflicts = geen retries
- ✅ Simpelere code = minder overhead

---

## ✅ CLEANUP CHECKLIST

### **Files te verwijderen:**
- [ ] `parallel_embedder.py` (hele file - multi-GPU logic niet nodig)
- [ ] `gpu_phase_lock.py` (hele file - geen cross-process locks nodig)
- [ ] `embedding_service.py` (aparte service niet nodig, zit in app.py)

### **Files te vereenvoudigen:**
- [ ] `gpu_manager.py` → `simple_gpu_manager.py` (80% kleiner)
- [ ] `app.py` → remove multi-GPU + aggressive cleanup logic
- [ ] `reranker.py` → remove gpu_phase_lock imports

### **Files ongewijzigd (al optimaal):**
- [ ] `contextual_enricher.py` ✅
- [ ] `doc_analyzer.py` ✅
- [ ] `status_reporter.py` ✅

### **Nieuwe files:**
- [ ] `start_AI3_optimized.sh` (dedicated GPU setup)
- [ ] `simple_gpu_manager.py` (monitoring only)

---

## 📝 BELANGRIJKE VERDUIDELIJKING

### **Embedder = IN DataFactory (app.py)**

**Er is GEEN aparte embedder service!**

```
┌─────────────────────────────────────────┐
│ DataFactory (app.py) op GPU 0           │
│ ├─ FastAPI endpoints (/ingest, /search) │
│ ├─ FAISS index management               │
│ ├─ SentenceTransformer (embedder) ◄──── GPU 0
│ ├─ Chunking logic                       │
│ └─ Status reporting                     │
└─────────────────────────────────────────┘
```

**Services architectuur:**
1. **DataFactory** (port 9000, GPU 0)
   - Bevat embedder (SentenceTransformer)
   - Bevat FAISS index
   - Endpoints: /ingest, /search, /health

2. **Reranker** (port 9200, GPU 1)
   - Aparte service
   - CrossEncoder model
   - Endpoint: /rerank

3. **Doc Analyzer** (port 9100, geen GPU)
   - Aparte service
   - Routes naar AI-4 of heuristics
   - Endpoint: /analyze

4. **Ollama** (ports 11434-11439, GPU 2-7)
   - 6 separate processen
   - Voor enrichment (binnen DataFactory workflow)
   - Geen direct endpoint naar AI-4

**embedding_service.py (port 8000):**
- ❌ Oude standalone service (niet gebruikt)
- ❌ Te verwijderen in cleanup
- ✅ Functionaliteit zit al in app.py

---

## 🎯 SAMENVATTING

**Strategie:**
1. **Remove complexity** die niet werkt met CUDA_VISIBLE_DEVICES pinning
2. **Keep it simple** - 1 GPU per taak, geen conflicts
3. **Focus op enrichment** - 6 GPU's waar het ertoe doet

**GPU Verdeling:**
- GPU 0: Embedding (dedicated)
- GPU 1: Reranking (dedicated)
- GPU 2-7: Ollama 6x parallel enrichment (dedicated)

**Code Reductie:**
- ~500 regels te verwijderen
- ~80% minder complexity in gpu_manager
- Stabielere execution
- Sneller door geen overhead

**Performance:**
- Enrichment: 2-3 minuten (was 3-5 min)
- Total ingest: ~2.7 min (was ~3.8 min)
- **30% sneller + veel stabieler!**
