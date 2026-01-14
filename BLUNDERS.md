# Genoteerde Blunders - Pipeline Debug Sessie

**Datum:** 7 januari 2026  
**Document:** Taxatierapport Camping de Brem (650 pagina's, 45MB)

---

## 🟢 Blunder 1: Ollama serve zonder expliciet model - **GEFIXED**

**Wat ging fout:**  
Bij het starten van Ollama werd `ollama serve` uitgevoerd zonder te specificeren welk model geladen moest worden.

**FIX geïmplementeerd in:** `start_AI3_services.sh`

```bash
# STAP 4: Warmup 70B model (FIX Blunder 1)
WARMUP_RESULT=$(curl -s http://localhost:11434/api/generate \
  -d "{\"model\":\"$DEFAULT_LLM_MODEL\",\"prompt\":\"Hello\",\"stream\":false}" \
  --max-time 120)
```

---

## 🟢 Blunder 2: Model load status niet gecheckt - **GEFIXED**

**Wat ging fout:**  
Na het starten van Ollama werd niet gecheckt of het model daadwerkelijk geladen was.

**FIX geïmplementeerd in:** `start_AI3_services.sh`

```bash
# Check huidige model status (FIX Blunder 2)
echo_status "Huidige model status (ollama ps):"
OLLAMA_MODELS="$OLLAMA_MODELS" ollama ps

# Check of model al geladen is
if OLLAMA_MODELS="$OLLAMA_MODELS" ollama ps | grep -q "$DEFAULT_LLM_MODEL"; then
  echo_ok "Model $DEFAULT_LLM_MODEL is al geladen"
else
  # Load model...
fi
```

---

## 🟢 Blunder 3: OLLAMA_MODELS path niet gezet - **GEFIXED**

**Wat ging fout:**  
Ollama zocht standaard in `~/.ollama/models/` waar alleen het 8B model stond.

**FIX geïmplementeerd in:** `start_AI3_services.sh`

```bash
# === CRITICAL: Ollama model locatie ===
export OLLAMA_MODELS="/usr/share/ollama/.ollama/models"

# Alle commando's gebruiken nu deze path
OLLAMA_MODELS="$OLLAMA_MODELS" ollama serve
OLLAMA_MODELS="$OLLAMA_MODELS" ollama list
OLLAMA_MODELS="$OLLAMA_MODELS" ollama ps
```

---

## 🟢 Blunder 4: Parallel Embedder Meta Tensor Error - **GEFIXED**

**Wat ging fout:**  
De `parallel_embedder.py` faalde met "Cannot copy out of meta tensor" error.

**FIX geïmplementeerd in:** `parallel_embedder.py`

```python
def _load_model_on_gpu(self, gpu_index: int) -> Optional[SentenceTransformer]:
    """
    FIX voor Blunder 4: Meta tensor error
    - Laad eerst op CPU, dan verplaats naar GPU
    - Extra garbage collection voor stabiele state
    """
    # FIX: Laad model eerst op CPU om meta tensor error te voorkomen
    logger.info(f"[ParallelEmbedder] Loading model to CPU first (meta tensor fix)...")
    model = SentenceTransformer(self._model_name, device="cpu")
    
    # Verplaats naar GPU met error handling
    try:
        model = model.to(device)
    except NotImplementedError as e:
        if "meta tensor" in str(e).lower():
            logger.warning(f"[ParallelEmbedder] Meta tensor error, trying to_empty()...")
            model = model.to_empty(device=device)
```

---

## 🟡 Blunder 5: Tijdschatting Context Verrijking Te Optimistisch

**Wat ging fout:**  
Geschatte tijd voor 595 chunks was 45-70 minuten, daadwerkelijke tijd was **156.8 minuten**.

**Status:** Gedocumenteerd, geen code fix nodig - is een schatting issue.

**Geleerde les:**  
- 70B model op 8x RTX 3060 Ti: ~15-16 sec per chunk
- Factor 2-3x toevoegen aan schattingen voor grote documenten
- Benchmarks bijhouden per document type

---

## ✅ Actiepunten - COMPLEET

- [x] **start_AI3_services.sh updaten** met OLLAMA_MODELS export en model warmup
- [x] **Model status check** toegevoegd met `ollama ps`
- [x] **parallel_embedder.py gefixed** voor meta tensor issue (CPU-first loading)
- [x] **Health checks** toegevoegd aan start script
- [ ] **Betere tijdschattingen** - handmatig bij te houden

---

## Samenvatting Fixes

| Blunder | Status | Fix Locatie |
|---------|--------|-------------|
| 1. Geen 70B model warmup | ✅ GEFIXED | `start_AI3_services.sh` |
| 2. Model status niet gecheckt | ✅ GEFIXED | `start_AI3_services.sh` |
| 3. OLLAMA_MODELS path | ✅ GEFIXED | `start_AI3_services.sh` |
| 4. Meta tensor error | ✅ GEFIXED | `parallel_embedder.py` |
| 5. Tijdschatting | 🟡 GEDOCUMENTEERD | - |
