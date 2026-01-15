# AI-3 Data Factory Pipeline & GPU Analyse (GECORRIGEERD)

**Datum:** 11 januari 2026  
**Server:** AI-3 (principium-ai-3) op 10.0.1.44  
**Doel:** Hoogwaardige data preparatie voor RAG applicaties vanaf AI-4

**CORRECTIE:** Deze analyse beschrijft de ACTUELE implementatie met CUDA_VISIBLE_DEVICES pinning.

---

## 🎮 GPU HARDWARE & ALLOCATIE (8x RTX 3060 Ti)

### Hardware Specificaties

```
8x NVIDIA GeForce RTX 3060 Ti
- VRAM per kaart: 8192 MB (8GB)
- Totaal VRAM: 65.536 GB
- CUDA Cores: 4864 per kaart (38,912 totaal)
- TDP: 200W per kaart (1600W totaal)
```

---

## ⚙️ ACTUELE GPU ALLOCATIE (via CUDA_VISIBLE_DEVICES)

### **Method: Process-Level GPU Pinning**

**Waarom dit werkt:** Elke service draait in eigen process met dedicated GPU via `CUDA_VISIBLE_DEVICES`. Dit voorkomt ALL GPU conflicts omdat processen elkaars GPU's niet zien!

#### **Setup 1: Standard Services (start_AI3_all.sh)**

```bash
# DataFactory (embedding) - GPU 0
CUDA_VISIBLE_DEVICES=0 uvicorn app:app --port 9000

# Reranker - GPU 1  
CUDA_VISIBLE_DEVICES=1 uvicorn reranker_service:app --port 9200

# Doc Analyzer - Geen pinning (gebruikt AI-4 of heuristics)
uvicorn doc_analyzer_service:app --port 9100
```

**Resultaat:**
- DataFactory ziet ALLEEN GPU 0
- Reranker ziet ALLEEN GPU 1
- **Geen conflicts mogelijk!**

#### **Setup 2: Multi-Ollama voor Enrichment (enable_multi_gpu_enrichment.sh)**

```bash
# 6 Ollama instances voor parallel enrichment
CUDA_VISIBLE_DEVICES=0 OLLAMA_HOST=0.0.0.0:11434 ollama serve  # GPU 0
CUDA_VISIBLE_DEVICES=1 OLLAMA_HOST=0.0.0.0:11435 ollama serve  # GPU 1
CUDA_VISIBLE_DEVICES=2 OLLAMA_HOST=0.0.0.0:11436 ollama serve  # GPU 2
CUDA_VISIBLE_DEVICES=3 OLLAMA_HOST=0.0.0.0:11437 ollama serve  # GPU 3
CUDA_VISIBLE_DEVICES=4 OLLAMA_HOST=0.0.0.0:11438 ollama serve  # GPU 4
CUDA_VISIBLE_DEVICES=5 OLLAMA_HOST=0.0.0.0:11439 ollama serve  # GPU 5

# DataFactory met OLLAMA_MULTI_GPU=true
OLLAMA_MULTI_GPU=true \
OLLAMA_NUM_INSTANCES=6 \
uvicorn app:app --port 9000
```

**Resultaat:**
- 6 Ollama processes, elk met dedicated GPU
- contextual_enricher.py doet round-robin over ports 11434-11439
- ThreadPoolExecutor met 6 workers = 6x parallel LLM calls

#### **GPU Toewijzing Schema:**

```
┌─────────┬────────────────────────────────────────────────────────┐
│ GPU     │ Functie (via CUDA_VISIBLE_DEVICES)                    │
├─────────┼────────────────────────────────────────────────────────┤
│ GPU 0   │ DataFactory embedding (dedicated)                      │
│         │ OF Ollama instance 1 (multi-GPU enrichment mode)       │
├─────────┼────────────────────────────────────────────────────────┤
│ GPU 1   │ Reranker (dedicated)                                   │
│         │ OF Ollama instance 2 (multi-GPU enrichment mode)       │
├─────────┼────────────────────────────────────────────────────────┤
│ GPU 2-5 │ Ollama instances 3-6 (multi-GPU enrichment mode)       │
│         │ OF vrij voor embedding fallback                        │
├─────────┼────────────────────────────────────────────────────────┤
│ GPU 6-7 │ Vrij / Reserve                                         │
│         │ Beschikbaar voor embedding parallel processing         │
└─────────┴────────────────────────────────────────────────────────┘
```

---

## 🔍 GPU Manager Rol: BINNEN Process, NIET Tussen Processes

### **Misverstand Opgehelderd:**

**gpu_manager.py heeft `_auto_cleanup_on_switch = True`** - maar dit werkt ALLEEN binnen 1 process!

```python
# In gpu_manager.py
self._auto_cleanup_on_switch = True  # Staat in code

# MAAR: dit geldt alleen binnen hetzelfde Python process
# Tussen verschillende processes (DataFactory, Reranker, Ollama) 
# zijn er GEEN conflicts omdat CUDA_VISIBLE_DEVICES ze isoleert!
```

### **Waar gpu_manager WEL gebruikt wordt:**

#### **1. Binnen parallel_embedder.py (Multi-GPU Embedding)**

**Scenario:** DataFactory process heeft `CUDA_VISIBLE_DEVICES=0` MAAR wil toch meerdere GPU's gebruiken voor embedding.

**NOOT:** Dit werkt NIET omdat CUDA_VISIBLE_DEVICES de GPU visibility beperkt!

**Code analyse:**
```python
# parallel_embedder.py::_get_available_gpus()
def _get_available_gpus(self, min_free_mb=2000):
    """Prefer GPU 6-7 (dedicated embedding GPU's)"""
    free_gpu_indices = gpu_manager.get_free_gpus(
        min_free_mb=min_free_mb,
        max_temp=MAX_GPU_TEMP_EMBED,
    )
    
    # PRIORITEIT: GPU 6-7 eerst
    embedding_gpus = []
    for gpu_idx in [6, 7]:  # Prefer deze
        if gpu_idx in free_gpu_indices:
            embedding_gpus.append(gpu_idx)
```

**MAAR:** Als DataFactory start met `CUDA_VISIBLE_DEVICES=0`, ziet het ALLEEN GPU 0!

**Conclusie:** 
- **parallel_embedder multi-GPU werkt ALLEEN als geen CUDA_VISIBLE_DEVICES pinning**
- Met pinning: single GPU (de gepinde GPU)
- Temperature & memory monitoring werkt wel binnen die 1 GPU

#### **2. Dynamic Device Selection (Binnen 1 Process)**

```python
# app.py::embed_texts()
best_device = get_pytorch_device(prefer_gpu=True, min_free_mb=2000)

# Dit geeft "cuda:0" als CUDA_VISIBLE_DEVICES=0
# OF selecteert beste van meerdere als geen pinning
```

#### **3. Cleanup Operations (Binnen 1 Process)**

```python
# Tussen taken binnen zelfde process
with GPUTask(TaskType.PYTORCH_EMBEDDING):
    embeddings = model.encode(texts)
# → Auto cleanup van PyTorch cache op die 1 GPU
```

---

## ✅ WAT WEL WAAR IS

### **1. CUDA_VISIBLE_DEVICES = Process Isolation**
- ✅ DataFactory (GPU 0) ziet geen andere GPU's
- ✅ Reranker (GPU 1) ziet geen andere GPU's  
- ✅ Ollama instances (elk eigen GPU) zien geen andere GPU's
- ✅ **GEEN cross-process conflicts mogelijk!**

### **2. Geen Auto-Cleanup Tussen Processes Nodig**
- ✅ Processes draaien op verschillende GPU's
- ✅ Geen memory conflicts
- ✅ Cleanup alleen binnen process (PyTorch cache, etc.)

### **3. Multi-GPU Ollama Enrichment**
- ✅ 6 separate Ollama processes (ports 11434-11439)
- ✅ Round-robin load balancing in contextual_enricher.py
- ✅ ThreadPoolExecutor met 6 workers = echt parallel
- ✅ 6x speedup vs single GPU

### **4. Temperature Monitoring**
- ✅ gpu_manager.get_gpu_temperatures() werkt (nvidia-smi)
- ✅ get_coolest_gpu() kan worden gebruikt
- ⚠️ MAAR: als CUDA_VISIBLE_DEVICES=0, zie je alleen GPU 0 temp

---

## ❌ WAT NIET WAAR IS

### **1. "Dynamic GPU Selection Over All 8 GPUs"**
- ❌ Niet als CUDA_VISIBLE_DEVICES pinning gebruikt wordt
- ✅ Alleen binnen process zonder pinning
- ✅ OF: geen pinning + parallel_embedder = multi-GPU

### **2. "Automatic Cleanup Bij Task Switch (Ollama ↔ PyTorch)"**
- ❌ Niet tussen processes (ze delen geen geheugen!)
- ✅ Wel binnen process (bijv. DataFactory internal)
- ❌ "Kill Ollama processes" in app.py is WORKAROUND, geen elegante oplossing

### **3. "Load Balancing Over Coolste GPU's"**  
- ❌ Niet als CUDA_VISIBLE_DEVICES pinning (ziet maar 1 GPU)
- ✅ Wel binnen parallel_embedder als GEEN pinning
- ⚠️ Huidige setup: BEIDE gebruikt (pinning ÉN parallel logic)

---

## 🔧 HUIDIGE IMPLEMENTATIE: Hybrid Approach

### **Scenario A: Standard Operation (start_AI3_all.sh)**

```bash
# GPU 0: DataFactory embedding
CUDA_VISIBLE_DEVICES=0 uvicorn app:app --port 9000

# GPU 1: Reranker
CUDA_VISIBLE_DEVICES=1 uvicorn reranker_service:app --port 9200
```

**Binnen DataFactory:**
- Ziet ALLEEN GPU 0
- parallel_embedder kan NIET meerdere GPU's gebruiken
- Maar: stabiel, geen conflicts

### **Scenario B: Multi-GPU Enrichment (enable_multi_gpu_enrichment.sh)**

```bash
# GPU 0-5: Ollama instances (6x)
# Elke instance eigen GPU via CUDA_VISIBLE_DEVICES

# DataFactory zonder pinning (ziet alle GPU's)
OLLAMA_MULTI_GPU=true uvicorn app:app --port 9000
```

**Binnen DataFactory:**
- Ziet ALLE GPU's
- parallel_embedder kan multi-GPU embedding
- Ollama instances dedicated per GPU
- **Trade-off:** Complexer, meer kans op conflicts

---

## 📊 PERFORMANCE IMPLICATIES

### **Met CUDA_VISIBLE_DEVICES Pinning:**

**Voordelen:**
- ✅ Geen GPU conflicts
- ✅ Stabiel en voorspelbaar
- ✅ Eenvoudig te debuggen

**Nadelen:**
- ❌ Embedding op 1 GPU (langzamer)
- ❌ Geen dynamic GPU selection
- ❌ Geen automatic load balancing

**Performance:**
- Embedding: ~50-100 chunks/sec (single GPU)
- Enrichment: ~50 chunks/min (6x Ollama parallel)
- Speedup: 6x voor enrichment, 1x voor embedding

### **Zonder CUDA_VISIBLE_DEVICES Pinning:**

**Voordelen:**
- ✅ Multi-GPU embedding (6x speedup mogelijk)
- ✅ Dynamic GPU selection
- ✅ Temperature-aware load balancing

**Nadelen:**
- ❌ GPU conflicts mogelijk (Ollama vs PyTorch)
- ❌ Complex cleanup management
- ❌ Meta tensor errors (zie BLUNDERS.md)

**Performance:**
- Embedding: ~300-600 chunks/sec (6 GPU parallel)
- Enrichment: ~50 chunks/min (6x Ollama parallel)  
- Speedup: 6x voor beide!

---

## 🎯 CONCLUSIE: ACTUELE SITUATIE

### **Gekozen Strategie: CUDA_VISIBLE_DEVICES Pinning**

**Waarom:**
1. ✅ Voorkomt GPU conflicts (was probleem!)
2. ✅ Stabiel en betrouwbaar
3. ✅ Eenvoudig te beheren
4. ❌ Trade-off: geen multi-GPU embedding

**GPU Verdeling:**
- **GPU 0:** DataFactory embedding (dedicated)
- **GPU 1:** Reranker (dedicated)
- **GPU 2-7:** Vrij voor Ollama enrichment (optioneel)

### **gpu_manager.py Functie:**

**BINNEN process:**
- ✅ PyTorch cache cleanup
- ✅ Temperature monitoring (van zichtbare GPU's)
- ✅ Memory monitoring
- ✅ Task tracking

**NIET tussen processes:**
- ❌ Geen cross-process cleanup
- ❌ Geen dynamic GPU reallocation
- ❌ Geen automatic task switching

### **Multi-GPU Features:**

**Wat WEL werkt:**
- ✅ 6x Ollama parallel (via multiple processes + ports)
- ✅ Round-robin load balancing (contextual_enricher.py)
- ✅ ThreadPoolExecutor parallel enrichment

**Wat NIET werkt (met pinning):**
- ❌ Multi-GPU embedding in parallel_embedder
- ❌ Dynamic GPU selection over all 8 GPU's
- ❌ Automatic GPU switching bij temperature

---

## 💡 AANBEVELINGEN

### **Voor Huidige Setup (Met Pinning):**

1. ✅ **Houd CUDA_VISIBLE_DEVICES pinning** (voorkomt de problemen!)
2. ✅ **Multi-Ollama voor enrichment** (6x speedup)
3. ⚠️ **Remove parallel_embedder multi-GPU logic** (werkt toch niet met pinning)
4. ✅ **Simplify gpu_manager** (remove unused cross-GPU logic)

### **Voor Maximum Performance (Zonder Pinning):**

1. ⚠️ Remove CUDA_VISIBLE_DEVICES pinning
2. ✅ Enable parallel_embedder multi-GPU
3. ⚠️ Fix meta tensor issues (zie BLUNDERS.md)
4. ⚠️ Implement robust cleanup mechanisms
5. ✅ Monitor voor GPU conflicts

### **Best of Both Worlds:**

**Dedicated Ollama GPU Pool:**
```bash
# GPU 0-5: Ollama only (CUDA_VISIBLE_DEVICES per instance)
# GPU 6-7: PyTorch only (DataFactory + Reranker)

# DataFactory sees only GPU 6-7
CUDA_VISIBLE_DEVICES=6,7 uvicorn app:app --port 9000

# Reranker on GPU 7
CUDA_VISIBLE_DEVICES=7 uvicorn reranker_service:app --port 9200
```

**Voordelen:**
- ✅ Ollama en PyTorch gescheiden (geen conflicts!)
- ✅ Multi-GPU embedding mogelijk (GPU 6-7)
- ✅ Stabiel en snel

---

**SAMENVATTING:** De huidige implementatie gebruikt CUDA_VISIBLE_DEVICES pinning voor stabiliteit. gpu_manager features werken alleen binnen processen, niet tussen processen. Multi-GPU enrichment werkt via separate Ollama processes. Trade-off: stabiliteit vs maximum performance. 🎯
