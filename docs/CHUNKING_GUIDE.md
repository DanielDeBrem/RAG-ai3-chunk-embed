# Chunking Strategies Guide
**Last Updated:** 14 januari 2026

Complete guide voor het modulaire chunking systeem van AI-3.

---

## 📋 Overzicht

Het chunking system is volledig modulair. Elke strategie staat in een eigen file en kan onafhankelijk worden aangeroepen, aangepast of uitgebreid. Auto-detectie kiest automatisch de beste strategie op basis van document karakteristieken.

**Voordelen:**
- ✅ Auto-detectie van beste strategie
- ✅ Modular design - eenvoudig nieuwe strategieën toevoegen
- ✅ Runtime configureerbaar
- ✅ API én Python interface
- ✅ Consistent testen en valideren

---

## 🏗️ Architectuur

```
chunking_strategies/
├── __init__.py              # Public API & auto-registratie
├── base.py                  # ChunkStrategy & ChunkingConfig base classes
├── registry.py              # Strategy registry & auto-detection
└── strategies/
    ├── __init__.py          # Strategy imports
    ├── default.py           # Fallback (paragraph-based)
    ├── legal.py             # Legal documents (hierarchical)
    ├── financial_tables.py  # Tables & numbers
    ├── free_text.py         # Narrative text
    ├── reviews.py           # Review aggregation
    ├── menus.py             # Menu items
    └── administrative.py    # Administrative documents
```

---

## 🎯 Beschikbare Strategieën

### 1. **default** - Standaard Tekst
**Gebruik voor:** Gewone documenten, artikelen, algemene tekst

**Config:**
```json
{
  "max_chars": 800,
  "overlap": 0
}
```

**Kenmerken:**
- Split op paragrafen (`\n\n`)
- Combineert paragrafen tot max_chars
- Optionele overlap tussen chunks
- Snelle fallback strategie

---

### 2. **page_plus_table_aware** - PDF's met Pagina's
**Gebruik voor:** PDF's, jaarrekeningen, rapporten, taxaties

**Config:**
```json
{
  "max_chars": 1500,
  "overlap": 200
}
```

**Kenmerken:**
- Respecteert `[PAGE X]` markers
- Houdt pagina grenzen intact
- Split lange pagina's verder
- Behoudt tabel structuren

**Auto-detect triggers:**
- `[PAGE` gevonden in tekst → confidence 0.95
- `mime_type` = "application/pdf" → confidence 0.70
- `.pdf` extensie → confidence 0.70

---

### 3. **semantic_sections** - Headers & Secties
**Gebruik voor:** Markdown, gestructureerde docs, offertes

**Config:**
```json
{
  "max_chars": 1200,
  "overlap": 150
}
```

**Kenmerken:**
- Split op Markdown headers (`#`, `##`, `###`)
- Split op underline headers (`===`, `---`)
- Behoudt header context bij sectie

**Auto-detect triggers:**
- 2+ Markdown headers → confidence 0.85
- 1+ underline headers → confidence 0.80
- `.md` extensie → confidence 0.75

---

### 4. **conversation_turns** - Dialogen & Chatlogs
**Gebruik voor:** WhatsApp, Slack, coaching sessies, Q&A

**Config:**
```json
{
  "max_chars": 600,
  "overlap": 0
}
```

**Kenmerken:**
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

### 5. **table_aware** - Tabel Preservatie
**Gebruik voor:** Data met tabellen, spreadsheets, structured data

**Config:**
```json
{
  "max_chars": 1000,
  "overlap": 100
}
```

**Kenmerken:**
- Detecteert tabellen (`| col |` of tabs)
- Houdt tabellen bij elkaar als `[TABLE]` chunks
- Voorkomt dat tabellen gesplitst worden

**Auto-detect triggers:**
- 3+ tabel lijnen → confidence 0.85

---

### 6. **legal** - Juridische Documenten
**Gebruik voor:** Juridische documenten met hiërarchische structuur

**Config:**
```json
{
  "max_chars": 1200,
  "overlap": 150
}
```

**Kenmerken:**
- Artikel/paragraaf nummering behouden
- Hiërarchische structuur (§1.2.3)
- Referenties intact houden
- Wettekst formatting

---

### 7. **free_text** - Vrije Tekst
**Gebruik voor:** Narratieve, ongestructureerde tekst

**Config:**
```json
{
  "max_chars": 1000,
  "overlap": 150,
  "min_chunk_chars": 200,
  "preserve_sentences": true
}
```

**Kenmerken:**
- Respecteert zinsgrenzen (nooit mid-sentence)
- Behoudt paragraaf integriteit
- Intelligente overlap voor context
- Merge kleine chunks voor betere semantiek

---

## 🔧 Gebruik

### Via API

#### 1. Lijst alle strategieën
```bash
curl http://localhost:9000/strategies/list
```

#### 2. Auto-detect beste strategie
```bash
curl -X POST http://localhost:9000/strategies/detect \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Sample text hier...",
    "metadata": {"filename": "chat.txt"}
  }'
```

#### 3. Test een strategie
```bash
curl -X POST http://localhost:9000/strategies/test \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Sample text hier...",
    "strategy": "conversation_turns",
    "config": {"max_chars": 600}
  }'
```

#### 4. Ingest met specifieke strategie
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

#### Basis gebruik (auto-detect)
```python
from chunking_strategies import chunk_text

text = "Je lange document tekst hier..."
chunks = chunk_text(text)  # Auto-detect beste strategie
```

#### Specifieke strategie kiezen
```python
from chunking_strategies import chunk_text

# Gebruik vrije tekst strategie
chunks = chunk_text(text, strategy="free_text")

# Of gebruik default strategie
chunks = chunk_text(text, strategy="default")
```

#### Met custom configuratie
```python
from chunking_strategies import chunk_text

chunks = chunk_text(
    text,
    strategy="free_text",
    config={
        "max_chars": 1200,      # Maximale chunk grootte
        "overlap": 200,          # Overlap tussen chunks
        "min_chunk_chars": 300,  # Minimale chunk grootte
        "preserve_sentences": True
    }
)
```

#### Met metadata (helpt auto-detectie)
```python
from chunking_strategies import chunk_text

chunks = chunk_text(
    text,
    metadata={
        "filename": "rapport.pdf",
        "mime_type": "application/pdf",
        "doc_type": "report"
    }
)
```

#### Info over beschikbare strategieën
```python
from chunking_strategies import list_strategies, detect_strategy

# Lijst alle strategieën
strategies = list_strategies()
for s in strategies:
    print(f"{s['name']}: {s['description']}")

# Detecteer beste strategie voor je tekst
best_strategy = detect_strategy(text, metadata)
print(f"Beste strategie: {best_strategy}")
```

---

## ➕ Nieuwe Strategie Toevoegen

### Stap 1: Maak Strategy Class

Maak `chunking_strategies/strategies/jouw_type.py`:

```python
"""
Jouw Type Chunking Strategy
"""
import re
from typing import List, Optional, Dict, Any
from ..base import ChunkStrategy, ChunkingConfig


class JouwTypeStrategy(ChunkStrategy):
    """Chunking strategie voor jouw specifieke datatype."""
    
    name = "jouw_type"
    description = "Beschrijving van deze strategie"
    default_config = {
        "max_chars": 800,
        "overlap": 100,
    }
    
    def detect_applicability(
        self, 
        text: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Return confidence score 0.0-1.0 voor deze strategie.
        
        Kijk naar:
        - Tekst patronen (regex)
        - Structuur markers
        - Metadata hints (filename, mime_type)
        """
        sample = text[:2000]
        score = 0.0
        
        # Jouw detectie logica hier
        if "SPECIAL_MARKER" in sample:
            score += 0.5
        
        return min(1.0, score)
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Voer de chunking uit.
        
        Returns:
            List van chunk strings
        """
        chunks = []
        
        # Jouw chunking logica hier
        sections = text.split("\n\n")
        for section in sections:
            if section.strip():
                chunks.append(section.strip())
        
        return chunks
```

### Stap 2: Registreer de Strategie

Voeg toe aan `chunking_strategies/strategies/__init__.py`:

```python
from .jouw_type import JouwTypeStrategy

__all__ = [
    "DefaultStrategy",
    "FreeTextStrategy",
    "JouwTypeStrategy",  # Nieuw!
]
```

### Stap 3: Auto-registreer

Voeg toe aan `chunking_strategies/__init__.py`:

```python
from .strategies import (
    DefaultStrategy, 
    FreeTextStrategy, 
    JouwTypeStrategy  # Nieuw!
)

def _initialize_default_strategies():
    registry = get_registry()
    strategies_to_register = [
        DefaultStrategy(),
        FreeTextStrategy(),
        JouwTypeStrategy(),  # Nieuw!
    ]
    # ...
```

### Stap 4: Test

```python
from chunking_strategies import chunk_text, detect_strategy

# Test auto-detect
strategy = detect_strategy(je_test_tekst)
print(f"Detected: {strategy}")

# Test chunking
chunks = chunk_text(je_test_tekst, strategy="jouw_type")
print(f"Chunks: {len(chunks)}")
```

**Klaar!** De strategie is nu beschikbaar via API én Python.

---

## 📊 Use Cases

| Document Type | Beste Strategie | Waarom |
|--------------|----------------|--------|
| PDF rapport | `page_plus_table_aware` | Behoudt pagina structuur |
| WhatsApp chat | `conversation_turns` | Split per bericht |
| Markdown doc | `semantic_sections` | Behoudt headers |
| Excel export | `table_aware` | Behoudt tabellen |
| Plain text | `default` | Simpel en snel |
| Juridisch | `legal` | Hiërarchische structuur |
| Reviews | `reviews` | Per-review chunking |
| Menus | `menus` | Per-item chunking |

---

## ✅ Best Practices

### 1. Auto-detect eerst
```python
# Laat systeem kiezen
chunks = chunk_text(text, metadata=metadata)

# Override alleen bij problemen
if not good_result:
    chunks = chunk_text(text, strategy="specific_strategy")
```

### 2. Gebruik metadata
```python
chunks = chunk_text(
    text,
    metadata={
        "filename": doc.name,
        "mime_type": doc.content_type,
        "doc_type": "legal",  # Custom hint
        "language": "nl"
    }
)
```

### 3. Monitor chunk quality
```python
chunks = chunk_text(text, strategy="free_text")

# Check kwaliteit
avg_size = sum(len(c) for c in chunks) / len(chunks)
min_size = min(len(c) for c in chunks)
max_size = max(len(c) for c in chunks)

print(f"Chunks: {len(chunks)}, Avg: {avg_size:.0f}, Range: {min_size}-{max_size}")
```

### 4. Test met echte data
```python
# Houd sample data voor elke strategie
SAMPLE_DATA = {
    "free_text": load_sample("samples/artikel.txt"),
    "legal": load_sample("samples/wetgeving.txt"),
}

for dtype, sample in SAMPLE_DATA.items():
    detected = detect_strategy(sample)
    print(f"{dtype}: detected as '{detected}'")
```

---

## 🔍 Debugging & Troubleshooting

### Verkeerde strategie gedetecteerd?
- Pas `detect_applicability()` aan in de strategie
- Gebruik expliciete `strategy="naam"` parameter
- Voeg betere metadata hints toe

### Chunks te groot/klein?
- Pas `max_chars` en `min_chunk_chars` aan in config
- Check strategy-specifieke parameters

### Context verlies tussen chunks?
- Verhoog `overlap` parameter (10-20% van max_chars)
- Overweeg parent-child chunking voor grote documenten

### Test een strategie
```bash
curl -X POST http://localhost:9000/strategies/test \
  -d '{"text": "...", "strategy": "conversation_turns"}' | jq
```

### Zie welke strategie wordt gekozen
```bash
curl -X POST http://localhost:9000/strategies/detect \
  -d '{"text": "...", "metadata": {"filename": "test.pdf"}}' | jq
```

Response bevat `all_scores` met alle confidence waardes!

---

## 📈 Performance Tips

1. **Auto-detect is fast** - gebruikt alleen eerste 2000 chars
2. **Config caching** - defaults worden gecached
3. **Fallback** - bij fouten valt het terug naar `default` strategie
4. **Overlap** - gebruik overlap (100-200) voor betere context continuity
5. **Batch processing** - chunk meerdere documenten in parallel

---

## 🧪 Testing

### Run test suite
```bash
python test_chunking_modular.py
```

### Test individuele strategie
```python
from chunking_strategies import get_registry

registry = get_registry()
strategy = registry.get("free_text")

chunks = strategy.chunk(text, config)
print(f"Created {len(chunks)} chunks")
```

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

Heb je vragen of wil je een nieuwe strategie toevoegen? Het systeem is volledig modulair en klaar voor uitbreiding! 🎉
