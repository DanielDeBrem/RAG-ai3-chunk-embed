# Modulaire Chunking Strategieën

## 📋 Overzicht

Het chunking systeem is nu volledig modulair opgezet. Elke chunking strategie voor een specifiek datatype staat in een eigen file en kan onafhankelijk worden aangeroepen, aangepast of uitgebreid.

## 🏗️ Structuur

```
chunking_strategies/
├── __init__.py              # Main module: auto-registratie en public API
├── base.py                  # Base classes: ChunkStrategy & ChunkingConfig
├── registry.py              # Registry: beheer en auto-detectie van strategieën
└── strategies/
    ├── __init__.py          # Verzamelt alle strategie imports
    ├── default.py           # Fallback strategie (paragraph-based)
    ├── free_text.py         # ✅ Data type 1: Vrije tekst
    ├── tables_numbers.py    # 🔜 Data type 2: Tabellen & cijfers
    ├── legal.py             # 🔜 Data type 3: Juridische documenten
    ├── administrative.py    # 🔜 Data type 4: Ambtelijke documenten
    ├── technical.py         # 🔜 Data type 5: Technische documenten
    ├── entities.py          # 🔜 Data type 6: Entiteiten (menus, etc.)
    └── mixed.py             # 🔜 Data type 7: Mixed content
```

## 🚀 Gebruik

### Basis gebruik (auto-detect)

```python
from chunking_strategies import chunk_text

text = "Je lange document tekst hier..."
chunks = chunk_text(text)
```

### Specifieke strategie kiezen

```python
from chunking_strategies import chunk_text

# Gebruik vrije tekst strategie
chunks = chunk_text(text, strategy="free_text")

# Of gebruik default strategie
chunks = chunk_text(text, strategy="default")
```

### Met custom configuratie

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

### Met metadata (helpt auto-detectie)

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

### Info over beschikbare strategieën

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

## 📝 Beschikbare Strategieën

### ✅ 1. Free Text (`free_text`)
**Status:** Geïmplementeerd

**Voor:** Vrije, ongestructureerde narratieve tekst
- Artikelen
- Verhalen  
- Rapporten zonder vaste structuur
- Essays & blogs
- Notities

**Kenmerken:**
- Respecteert zinsgrenzen (nooit mid-sentence)
- Behoudt paragraaf integriteit
- Intelligente overlap voor context
- Merge kleine chunks voor betere semantiek
- Default: 1000 chars, 150 overlap

**Config opties:**
```python
{
    "max_chars": 1000,
    "overlap": 150,
    "min_chunk_chars": 200,
    "preserve_sentences": True
}
```

### 2. Default (`default`)
**Status:** Geïmplementeerd (fallback)

**Voor:** Alle documenttypen als fallback

**Kenmerken:**
- Simpel paragraph-based chunking
- Split op `\n\n` (dubbele newline)
- Optionele overlap
- Altijd beschikbaar als fallback

## 🔨 Nieuwe Strategie Toevoegen

### Stap 1: Maak een nieuwe strategie file

Maak `chunking_strategies/strategies/jouw_type.py`:

```python
"""
Jouw Type Chunking Strategy

Beschrijving van wat deze strategie doet.
"""
import re
from typing import List, Optional, Dict, Any
from ..base import ChunkStrategy, ChunkingConfig


class JouwTypeStrategy(ChunkStrategy):
    """
    Chunking strategie voor jouw specifieke datatype.
    """
    
    name = "jouw_type"
    description = "Beschrijving van deze strategie"
    default_config = {
        "max_chars": 800,
        "overlap": 100,
        # Voeg custom parameters toe
    }
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
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
        # Bijvoorbeeld:
        if "ARTIKEL" in sample and "§" in sample:
            score += 0.5
        
        return min(1.0, score)
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Voer de chunking uit.
        
        Returns:
            List van chunk strings
        """
        # Jouw chunking logica hier
        chunks = []
        
        # Voorbeeld: split op sections
        sections = text.split("\n\n")
        for section in sections:
            if section.strip():
                chunks.append(section.strip())
        
        return chunks
```

### Stap 2: Registreer de strategie

Voeg toe aan `chunking_strategies/strategies/__init__.py`:

```python
from .jouw_type import JouwTypeStrategy

__all__ = [
    "DefaultStrategy",
    "FreeTextStrategy",
    "JouwTypeStrategy",  # Nieuw!
]
```

### Stap 3: Auto-registreer bij import

Voeg toe aan `chunking_strategies/__init__.py`:

```python
from .strategies import DefaultStrategy, FreeTextStrategy, JouwTypeStrategy

def _initialize_default_strategies():
    registry = get_registry()
    strategies_to_register = [
        DefaultStrategy(),
        FreeTextStrategy(),
        JouwTypeStrategy(),  # Nieuw!
    ]
    # ...
```

### Stap 4: Test je strategie

```python
from chunking_strategies import chunk_text, detect_strategy

# Test auto-detect
strategy = detect_strategy(je_test_tekst)
print(f"Detected: {strategy}")

# Test chunking
chunks = chunk_text(je_test_tekst, strategy="jouw_type")
print(f"Chunks: {len(chunks)}")
```

## 🎯 Roadmap: Te Implementeren Data Types

### 2️⃣ Tabellen & Cijfers
**File:** `strategies/tables_numbers.py`
**Focus:**
- Detecteer en behoud tabel structuren
- Preserveer relaties tussen cijfers en labels
- Smart splitting bij lange tabellen
- Context voor cijfers (koppen erboven)

### 3️⃣ Juridische & Beleidsdocumenten
**File:** `strategies/legal.py`
**Focus:**
- Artikel/paragraaf nummering behouden
- Hiërarchische structuur (§1.2.3)
- Referenties intact houden
- Wettekst formatting

### 4️⃣ Ambtelijke & Bestuurlijke Documenten
**File:** `strategies/administrative.py`
**Focus:**
- Formele structuur (bijlagen, paragrafen)
- Besluitvorming flow
- Referentie nummers
- Handtekeningen & bijlagen apart

### 5️⃣ Operationele & Technische Documenten
**File:** `strategies/technical.py`
**Focus:**
- Procedures & stappen behouden
- Code blocks intact
- Lijsten & specificaties
- Diagrammen & schema's (markers)

### 6️⃣ Entiteiten (Menus, etc.)
**File:** `strategies/entities.py`
**Focus:**
- Per-item chunking (elk menu item = chunk)
- Metadata extractie (prijs, beschrijving)
- Gestructureerde data behouden
- Review aggregatie

### 7️⃣ Mixed/Samengesteld
**File:** `strategies/mixed.py`
**Focus:**
- Detecteer verschillende secties
- Route naar juiste sub-strategie per sectie
- Combineer resultaten intelligent
- Behoud document coherentie

## 🧪 Testing

Run de test suite:

```bash
python test_chunking_modular.py
```

Test individuele strategie:

```python
from chunking_strategies import get_registry

registry = get_registry()
strategy = registry.get("free_text")

chunks = strategy.chunk(text, config)
print(f"Created {len(chunks)} chunks")
```

## 🔧 Geavanceerd Gebruik

### Custom Registry

```python
from chunking_strategies import ChunkStrategyRegistry
from chunking_strategies.strategies import FreeTextStrategy

# Maak eigen registry
my_registry = ChunkStrategyRegistry()
my_registry.register(FreeTextStrategy())

# Gebruik custom registry
chunks = my_registry.chunk_text(text)
```

### Extend Bestaande Strategie

```python
from chunking_strategies.strategies import FreeTextStrategy
from chunking_strategies import ChunkingConfig

class MyCustomFreeText(FreeTextStrategy):
    name = "my_custom_free_text"
    
    def chunk(self, text: str, config: ChunkingConfig):
        # Roep parent aan
        chunks = super().chunk(text, config)
        
        # Voeg custom post-processing toe
        chunks = [self.clean_chunk(c) for c in chunks]
        return chunks
    
    def clean_chunk(self, chunk: str) -> str:
        # Jouw custom cleaning
        return chunk.strip()
```

## 📊 Best Practices

### 1. Auto-detect eerst, manual fallback
```python
# Laat systeem kiezen
chunks = chunk_text(text, metadata=metadata)

# Of override bij problemen
if not good_result:
    chunks = chunk_text(text, strategy="specific_strategy")
```

### 2. Gebruik metadata voor betere detectie
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

### 3. Test met echte data
```python
# Houd sample data voor elke strategie
SAMPLE_DATA = {
    "free_text": load_sample("samples/artikel.txt"),
    "legal": load_sample("samples/wetgeving.txt"),
    # etc
}

for dtype, sample in SAMPLE_DATA.items():
    detected = detect_strategy(sample)
    print(f"{dtype}: detected as '{detected}'")
```

### 4. Monitor chunk quality
```python
chunks = chunk_text(text, strategy="free_text")

# Check kwaliteit
avg_size = sum(len(c) for c in chunks) / len(chunks)
min_size = min(len(c) for c in chunks)
max_size = max(len(c) for c in chunks)

print(f"Chunks: {len(chunks)}")
print(f"Avg size: {avg_size:.0f}")
print(f"Range: {min_size}-{max_size}")
```

## 🆘 Troubleshooting

### Verkeerde strategie gedetecteerd?
→ Pas `detect_applicability()` aan in de strategie  
→ Gebruik expliciete `strategy="naam"` parameter  
→ Voeg betere metadata hints toe

### Chunks te groot/klein?
→ Pas `max_chars` en `min_chunk_chars` aan in config  
→ Check strategy-specifieke parameters

### Context verlies tussen chunks?
→ Verhoog `overlap` parameter  
→ Overweeg parent-child chunking voor grote documenten

### Nieuwe strategie werkt niet?
→ Check of strategie geregistreerd is (`list_strategies()`)  
→ Test `detect_applicability()` apart  
→ Valideer `chunk()` output met kleine test

## 📝 Next Steps

1. **Voor nu:** Gebruik `free_text` voor narratieve documenten
2. **Volgende:** Geef input voor data type 2 (Tabellen & Cijfers)
3. **Daarna:** Implementeer overige types stap voor stap

Bij elke nieuwe data type:
- Lever voorbeelddata aan
- Bespreek specifieke requirements
- Test met echte documenten
- Itereer op basis van resultaten
