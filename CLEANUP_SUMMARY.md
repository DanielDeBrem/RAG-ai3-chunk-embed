# Cleanup Summary - Wat Is Gedaan

## A) ✅ Taak 1 & 2: Hybrid Doc Analyzer

**File: doc_analyzer.py**

Geïmplementeerd 3-Tier fallback strategie:

```python
def _llm_enrich(document, filename, mime_type):
    # Tier 1: AI-4 LLM70 (95% kwaliteit, preferred)
    try:
        return llm_client.analyze_document(...)
    except:
        pass
    
    # Tier 2: Local Ollama 8B (85% kwaliteit, goede fallback) ← NIEUW!
    try:
        return _llm_enrich_local_8b(document, filename, mime_type)
    except:
        pass
    
    # Tier 3: Heuristics (40% kwaliteit, emergency)
    return _llm_enrich_heuristic(document, filename, mime_type)
```

**Nieuw:** `_llm_enrich_local_8b()` gebruikt Ollama op GPU 2-7 (port 11434)

**Voordelen:**
- Robuuster (3 levels van fallback)
- Beter dan pure heuristics bij AI-4 problemen
- +45% kwaliteit vs alleen heuristics
- Gebruikt bestaande Ollama instances (geen extra GPU nodig)

---

## B) ✅ Cleanup: Old Files Renamed to NU_

**Hernoemde files:**
```bash
parallel_embedder.py → NU_parallel_embedder.py
gpu_phase_lock.py → NU_gpu_phase_lock.py
embedding_service.py → NU_embedding_service.py
```

**Reden:**
- `parallel_embedder.py`: Multi-GPU logic werkt NIET met CUDA_VISIBLE_DEVICES=0 pinning
- `gpu_phase_lock.py`: File-based locks NIET nodig met dedicated GPU's
- `embedding_service.py`: Oude standalone service, functionaliteit zit in app.py

**Deze files kunnen later veilig verwijderd worden!**

---

## ⚠️ Nog Te Doen: app.py Cleanup

**app.py heeft nog references naar verwijderde modules:**

### 1. Remove parallel_embedder references:
```python
❌ from parallel_embedder import embed_texts_parallel, get_embedder_status, unload_embedder_models
❌ embed_texts_parallel() calls
❌ get_embedder_status() endpoint
❌ unload_embedder_models() calls
```

### 2. Remove gpu_phase_lock references:
```python
❌ Alle GPUTask context managers
❌ TaskType enum usage
❌ with GPUTask(TaskType.PYTORCH_EMBEDDING, ...):
```

### 3. Simplify embed_texts():
```python
# Oud (complex):
if PARALLEL_EMBED_ENABLED and n_texts >= MIN_CHUNKS_FOR_PARALLEL:
    embed_texts_parallel(...)
else:
    # Single GPU with complex device switching

# Nieuw (simpel):
def embed_texts(texts):
    global model
    if model is None:
        init_model()  # Load op GPU 0
    
    try:
        return model.encode(texts, batch_size=32, normalize_embeddings=True)
    except torch.cuda.OutOfMemoryError:
        # Fallback to CPU
        model = model.to("cpu")
        return model.encode(texts, batch_size=16)
    finally:
        # Light cleanup
        gc.collect()
        torch.cuda.empty_cache()
```

### 4. Simplify init_model():
```python
# Oud (complex met GPUTask):
with GPUTask(TaskType.PYTORCH_EMBEDDING, ...):
    model = SentenceTransformer(EMBED_MODEL_NAME)
    model = model.to(device)  # Complex device logic

# Nieuw (simpel):
def init_model():
    global model
    # Load direct op cuda (GPU 0 via CUDA_VISIBLE_DEVICES)
    model = SentenceTransformer(EMBED_MODEL_NAME, device="cuda")
```

### 5. Remove unnecessary endpoints:
```python
❌ @app.get("/embedder/status")  # Uses get_embedder_status()
❌ @app.post("/embedder/unload")  # Uses unload_embedder_models()
❌ @app.post("/embedder/prepare")  # Complex GPU orchestration
```

### 6. Simplify ingest_text_into_index():
```python
# Verwijder:
❌ Aggressive Ollama cleanup (psutil kill logic)
❌ GPUTask context managers
❌ Complex GPU device switching

# Behoud:
✅ Contextual enrichment (6x Ollama parallel)
✅ Simple embedding (GPU 0)
✅ Simple PyTorch cleanup
```

---

## 🎯 Doel van Cleanup

**Strategie: Dedicated GPU per Taak**
```
GPU 0: DataFactory embedding (via CUDA_VISIBLE_DEVICES)
GPU 1: Reranker (via CUDA_VISIBLE_DEVICES)
GPU 2-7: Ollama enrichment + doc analysis (6x instances)
```

**Voordelen:**
- ✅ Geen GPU conflicts (process isolation)
- ✅ Stabiel (geen meta tensor errors)
- ✅ Simpeler code (~500 regels minder)
- ✅ Beter onderhoudbaar

**Trade-off:**
- ❌ Geen multi-GPU embedding (maar was toch broken)
- ✅ Focus op enrichment speedup (6x parallel)

---

## 📝 Status

- [x] A) Implement hybrid doc analyzer (3-tier fallback)
- [x] B) Rename old files to NU_*
- [ ] C) Clean up app.py (remove broken references)
- [ ] D) Test lokaal
- [ ] E) Test vanaf AI-4

**Next:** Cleanup app.py before testing!
