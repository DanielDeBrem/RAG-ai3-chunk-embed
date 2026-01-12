# Chunking Strategies - Modular System

## 📋 Overzicht

Het chunking system is nu volledig modulair. Je kunt eenvoudig:
- ✅ Nieuwe strategieën toevoegen
- ✅ Bestaande strategieën aanpassen  
- ✅ Strategieën testen voordat je ze gebruikt
- ✅ Auto-detection laten beslissen welke strategie het beste past

---

## 🎯 Beschikbare Strategieën

### 1. `default` - Standaard Tekst
**Gebruik voor:** Gewone documenten, artikelen, tekst

**Config:**
```json
{
  "max_chars": 800,
  "overlap": 0
}
```

**Hoe het werkt:**
- Split op paragrafen (`\n\n`)
- Combineert paragrafen tot max_chars
- Optionele overlap tussen chunks

---

### 2. `page_plus_table_aware` - PDF's met Pagina's
**Gebruik voor:** PDF's, jaarrekeningen, rapporten, taxaties

**Config:**
```json
{
  "max_chars": 1500,
  "overlap": 200
}
```

**Hoe het werkt:**
- Respecteert `[PAGE X]` markers
- Houdt pagina grenzen intact
- Split lange pagina's verder
- Behoudt tabel structuren

**Auto-detect triggers:**
- `[PAGE` gevonden in tekst → confidence 0.95
- `mime_type` = "application/pdf" → confidence 0.70
- `.pdf` extensie → confidence 0.70

---

### 3. `semantic_sections` - Headers & Secties
**Gebruik voor:** Markdown, gestructureerde docs, offertes

**Config:**
```json
{
  "max_chars": 1200,
  "overlap": 150
}
```

**Hoe het werkt:**
- Split op Markdown headers (`#`, `##`, `###`)
- Split op underline headers (`===`, `---`)
- Behoudt header context bij sectie

**Auto-detect triggers:**
- 2+ Markdown headers → confidence 0.85
- 1+ underline headers → confidence 0.80
- `.md` extensie → confidence 0.75

---

### 4. `conversation_turns` - Dialogen & Chatlogs
**Gebruik voor:** WhatsApp, Slack, coaching sessies, Q&A

**Config:**
```json
{
  "max_chars": 600,
  "overlap": 0
}
```

**Hoe het werkt:**
- Detecteert speaker patterns (`User:`, `Assistant:`, `Q:`, etc.)
- Split per conversatie turn
- Combineert kleine turns

**Auto-detect triggers:**
- 5+ speaker patterns → confidence 0.90
- 2-4 speaker patterns → confidence 0.75
- "chat", "whatsapp", "telegram" in filename → confidence 0.85

**Supported patterns:**
- User:, Assistant:, Client:, Therapist:, Coach:, Coachee:
- Q:, A:, Vraag:, Antwoord:

---

### 5. `table_aware` - Tabel Preservatie
**Gebruik voor:** Data met tabellen, spreadsheets, structured data

**Config:**
```json
{
  "max_chars": 1000,
  "overlap": 100
}
```

**Hoe het werkt:**
- Detecteert tabellen (`| col |` of tabs)
- Houdt tabellen bij elkaar als `[TABLE]` chunks
- Voorkomt dat tabellen gesplitst worden

**Auto-detect triggers:**
- 3+ tabel lijnen → confidence 0.85

---

## 🔧 Gebruik

### Via API

**1. Lijst alle strategieën:**
```bash
curl http://localhost:9000/strategies/list
```

**2. Auto-detect beste strategie:**
```bash
curl -X POST http://localhost:9000/strategies/detect \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Sample text hier...",
    "metadata": {"filename": "chat.txt"}
  }'
```

**3. Test een strategie:**
```bash
curl -X POST http://localhost:9000/strategies/test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Sample text hier...",
    "strategy": "conversation_turns",
    "config": {"max_chars": 600}
  }'
```

**4. Ingest met specifieke strategie:**
```bash
curl -X POST http://localhost:9000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "project_id": "test",
    "filename": "chat.txt",
    "text": "User: Hello\nAssistant: Hi there!",
    "chunk_strategy": "conversation_turns"
  }'
```

### Via Python

```python
from chunking_strategies import chunk_text, list_strategies, detect_strategy

# Lijst alle strategieën
strategies = list_strategies()
print(strategies)

# Auto-detect
text = "User: Hello\nAssistant: Hi!"
strategy = detect_strategy(text, metadata={"filename": "chat.txt"})
print(f"Beste strategie: {strategy}")

# Chunk met specifieke strategie
chunks = chunk_text(
    text=text,
    strategy="conversation_turns",
    config={"max_chars": 600}
)

# Chunk met auto-detect
chunks = chunk_text(text=text)  # Kiest automatisch beste strategie
```

---

## ➕ Nieuwe Strategie Toevoegen

### Stap 1: Maak een nieuwe Strategy class

```python
# In chunking_strategies.py

class LogfileStrategy(ChunkStrategy):
    """Chunk logfiles op timestamp grenzen."""
    
    name = "logfile"
    description = "Splits logfiles on timestamp boundaries"
    default_config = {"max_chars": 1000, "overlap": 0}
    
    def detect_applicability(self, text: str, metadata: Optional[Dict] = None) -> float:
        import re
        # Detecteer timestamp patterns
        timestamps = re.findall(r'\d{4}-\d{2}-\d{2}', text[:2000])
        if len(timestamps) > 5:
            return 0.90
        elif len(timestamps) > 2:
            return 0.70
        
        # Check filename
        fn = (metadata or {}).get("filename", "").lower()
        if fn.endswith(".log"):
            return 0.85
        
        return 0.1
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        import re
        # Split op timestamp patterns
        pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
        chunks = re.split(pattern, text)
        
        # Combineer timestamp met log entry
        result: List[str] = []
        for i in range(0, len(chunks)-1, 2):
            if i+1 < len(chunks):
                entry = chunks[i] + chunks[i+1]
                if entry.strip():
                    result.append(entry.strip())
        
        return result if result else [text.strip()]
```

### Stap 2: Registreer de strategie

```python
# In chunking_strategies.py, in _register_default_strategies()

def _register_default_strategies(self):
    for strategy_class in [
        DefaultStrategy,
        PageAwareStrategy,
        SemanticSectionsStrategy,
        ConversationStrategy,
        TableAwareStrategy,
        LogfileStrategy,  # ← VOEG TOE
    ]:
        self.register(strategy_class())
```

### Stap 3: Test!

```bash
# Test de nieuwe strategie
curl -X POST http://localhost:9000/strategies/test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "2025-01-12 10:00:00 INFO Started\n2025-01-12 10:00:01 DEBUG Loading...",
    "strategy": "logfile"
  }'
```

**Klaar!** De strategie is nu beschikbaar voor iedereen.

---

## 🎨 Config Aanpassen

Je kunt configs runtime aanpassen zonder code wijzigingen:

```python
# Custom config per strategie
chunks = chunk_text(
    text=sample_text,
    strategy="page_plus_table_aware",
    config={
        "max_chars": 2000,  # Grotere chunks
        "overlap": 300      # Meer overlap
    }
)
```

---

## 🔍 Debugging

**Test strategie met sample data:**
```bash
curl -X POST http://localhost:9000/strategies/test \
  -d '{"text": "...", "strategy": "conversation_turns"}' | jq
```

**Zie welke strategie wordt gekozen:**
```bash
curl -X POST http://localhost:9000/strategies/detect \
  -d '{"text": "...", "metadata": {"filename": "test.pdf"}}' | jq
```

**Check confidence scores van alle strategieën:**
Response bevat `all_scores` met alle confidence waardes!

---

## 📊 Performance Tips

1. **Auto-detect is fast** - gebruikt alleen eerste 2000 chars
2. **Config caching** - defaults worden gecached
3. **Fallback** - bij fouten valt het terug naar `default` strategie
4. **Overlap** - gebruik overlap (100-200) voor betere context continuity

---

## 🎯 Use Cases

| Document Type | Beste Strategie | Waarom |
|--------------|----------------|--------|
| PDF rapport | `page_plus_table_aware` | Behoudt pagina structuur |
| WhatsApp chat | `conversation_turns` | Split per bericht |
| Markdown doc | `semantic_sections` | Behoudt headers |
| Excel export | `table_aware` | Behoudt tabellen |
| Plain text | `default` | Simpel en snel |
| Logfile | `logfile` (custom) | Timestamp-based |

---

## ✅ Best Practices

1. **Test eerst** - gebruik `/strategies/test` endpoint
2. **Laat auto-detect werken** - alleen override als nodig
3. **Monitor chunk sizes** - check avg/min/max in test results
4. **Gebruik overlap** - 10-20% van max_chars voor smooth transitions
5. **Custom strategies** - maak nieuwe strategies voor specifieke use cases

---

## 🚀 Volgende Stappen

**Mogelijke uitbreidingen:**
- API stream strategie (time-windowed)
- Code strategie (function/class boundaries)
- Email strategie (thread-aware)
- JSON/XML strategie (structure-aware)

**Configuratie file support:**
- Laad strategieën uit YAML/JSON config
- Hot-reload zonder restart
- Per-tenant strategie preferences

---

Heb je vragen of wil je een nieuwe strategie toevoegen? Het systeem is nu volledig modulair en klaar voor uitbreiding! 🎉
