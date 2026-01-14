# Chunking Strategies - Implementatie Status

## ✅ Geïmplementeerd

### 1️⃣ Vrije Tekst (Free Text)
**Strategie:** `free_text`  
**Status:** ✅ KLAAR  
**File:** `chunking_strategies/strategies/free_text.py`

**Voor:**
- Artikelen
- Verhalen
- Rapporten zonder vaste structuur
- Essays & blogs
- Notities

**Features:**
- Respecteert zinsgrenzen (nooit mid-sentence)
- Behoudt paragraaf integriteit
- Intelligente overlap voor context
- Merge kleine chunks voor betere semantiek
- Default: 1000 chars, 150 overlap

**Gebruik:**
```python
from chunking_strategies import chunk_text

chunks = chunk_text(text, strategy="free_text")
```

---

### 2️⃣ Tekst met Tabellen & Cijfers (Financial Tables)
**Strategie:** `financial_tables`  
**Status:** ✅ KLAAR  
**File:** `chunking_strategies/strategies/financial_tables.py`

**Voor:**
- Jaarrekeningen (Balans, V&W, Kasstroom)
- Financiële rapportages
- Offertes & prijsopgaven
- Contractvoorstellen

**Features:**
- Hybride chunking per sectie (Balans, V&W, etc.)
- Tabellen: rij-per-rij voor korte tabellen
- KPI-tracking: kolom-per-kolom voor tijdreeksen
- Intelligente sectie detectie
- Metadata extractie (jaar, entiteit)
- Default: 1500 chars, 100 overlap

**Modes:**
- `row`: 1 rij = 1 chunk (beste voor korte tabellen)
- `column`: KPI over tijd (beste voor tijdreeksen)
- `hybrid`: Automatisch kiezen (default)

**Gebruik:**
```python
from chunking_strategies import chunk_text

# Auto-detect en hybrid mode
chunks = chunk_text(
    text, 
    strategy="financial_tables",
    metadata={"filename": "jaarrekening_2023.pdf"}
)

# Expliciet row mode voor prijslijsten
chunks = chunk_text(
    text,
    strategy="financial_tables",
    config={"table_mode": "row"}
)

# Column mode voor KPI tijdreeksen
chunks = chunk_text(
    text,
    strategy="financial_tables", 
    config={"table_mode": "column"}
)
```

**Voorbeeldoutput:**

Voor een jaarrekening met balans over 2021-2023:
```
Chunk 1: [BALANS]
         [TABEL]
         2023    2022    2021
         Vaste activa    450.000    425.000    400.000

Chunk 2: [BALANS]
         [TABEL]
         2023    2022    2021
         Vlottende activa    125.000    110.000    95.000
```

In column mode (tijdreeks):
```
Chunk 1: [BALANS]
         [TABEL]
         KPI: Vaste activa
         2021: 400.000
         2022: 425.000
         2023: 450.000

Chunk 2: [BALANS]
         [TABEL]
         KPI: EBITDA
         2021: 210.000
         2022: 230.000
         2023: 240.000
```

Dit maakt queries mogelijk zoals:
- "Hoe ontwikkelt EBITDA zich over 2019-2023?"
- "Wat zijn de kosten in 2023?"
- "Vergelijk de balans van 2022 met 2023"

**Detectie:**
De strategie detecteert automatisch financiële documenten op basis van:
- Financiële sectie headers (Balans, V&W, Kasstroom, Toelichting)
- Contract termen (Scope, Prijs, Looptijd, Voorwaarden)
- KPI termen (EBITDA, Omzet, Winst, Marge)
- Tabel structuren (|, tabs, borders)
- Getallen en valuta symbolen (€, $, decimalen)
- Jaartallen (meerdere jaren = tijdreeks indicator)
- Filename hints (jaarrekening, balans, offerte, etc.)

---

### 3️⃣ Juridische & Beleidsdocumenten (Legal Documents)
**Strategie:** `legal`  
**Status:** ✅ KLAAR  
**File:** `chunking_strategies/strategies/legal.py`

**Voor:**
- Contracten
- Algemene voorwaarden
- Wet- en regelgeving
- APV (Algemene Plaatselijke Verordening)
- EU-richtlijnen
- Subsidieregels
- Beleidsregels

**Features:**
- Artikel-gebaseerde chunking (NIET semantisch!)
- Hiërarchische structuur behouden (Art. 1.2.3)
- Subartikelen als aparte chunks
- **GEEN overlap** (juridische precisie vereist)
- Volledige zinnen altijd bewaren (nooit mid-sentence)
- Metadata extractie (artikelnummer, rechtsgebied, status)
- Default: 2000 chars, 0 overlap

**Waarom geen semantische chunking?**
Juridische vragen zijn **referentie-gedreven**, niet verhalend.
Queries zoals "Wat staat er in Artikel 3 lid 2?" vereisen exacte artikel referenties.

**Gebruik:**
```python
from chunking_strategies import chunk_text

# Auto-detect
chunks = chunk_text(
    contract_text,
    metadata={"filename": "algemene_voorwaarden.pdf"}
)

# Expliciet legal strategie
chunks = chunk_text(contract_text, strategy="legal")

# Met custom config
chunks = chunk_text(
    wet_text,
    strategy="legal",
    config={
        "max_chars": 2500,
        "split_subarticles": True
    }
)
```

**Voorbeeldoutput:**

Voor een contract met artikelen:
```
Chunk 1: [ARTIKEL 1]
         [TITEL: Definities]
         
         In deze algemene voorwaarden wordt verstaan onder:
         a) Exploitant: Camping De Brem B.V.
         b) Gast: de natuurlijke persoon...

Chunk 2: [ARTIKEL 2]
         [TITEL: Toepasselijkheid]
         
         1. Deze algemene voorwaarden zijn van toepassing...
         2. Afwijkingen zijn slechts geldig indien...
```

Voor artikelen met subartikelen wordt gesplitst per lid:
```
Chunk 1: [ARTIKEL 3.1]
         [TITEL: Reservering en betaling]
         
         Een reservering komt tot stand na...

Chunk 2: [ARTIKEL 3.2]
         [TITEL: Reservering en betaling]
         
         Bij reservering dient 30% van het...
```

**Detectie:**
De strategie detecteert juridische documenten op basis van:
- Artikel nummering (Artikel 1, Art. 2, § 3, etc.)
- Juridische terminologie (partij, overeenkomst, aansprakelijkheid, etc.)
- Hiërarchische structuur (1. 2. a) b) etc.)
- Formele taal patronen
- Rechtsgebied indicaties (Nederlands recht, EU-richtlijn, gemeentelijk)
- Filename hints (contract, voorwaarden, wet, apv, etc.)

**GEEN overlap:**
In tegenstelling tot andere strategieën heeft legal **0 overlap**.
Dit is cruciaal voor juridische precisie - elke chunk moet exact één artikel/lid bevatten.

---

### 4️⃣ Ambtelijke & Bestuurlijke Documenten (Administrative Documents)
**Strategie:** `administrative`  
**Status:** ✅ KLAAR  
**File:** `chunking_strategies/strategies/administrative.py`

**Voor:**
- Beleidsnota's
- Besluitstukken / raadsbesluiten
- Subsidieregels en -aanvragen
- Vergunningsdocumentatie
- Ambtelijke adviezen
- Collegebesluiten

**Features:**
- Sectie-gebaseerde chunking (Besluit, Motivatie, Voorwaarden, etc.)
- Speciale secties apart chunken
- Samenvattende kop + alinea's
- Metadata extractie (besluittype, bestuursorgaan, datum)
- Ondersteunt vage taal en veel verwijzingen
- Default: 1200 chars, 100 overlap

**Waarom deze aanpak?**
Ambtelijke documenten bevatten vaak vage taal en veel verwijzingen.
Speciale secties zoals BESLUIT, VOORWAARDEN, TERMIJNEN moeten apart worden gechunked
voor vragen als **"Kom ik in aanmerking als X en Y?"**

**Gebruik:**
```python
from chunking_strategies import chunk_text

# Auto-detect
chunks = chunk_text(
    besluit_text,
    metadata={"filename": "raadsbesluit_subsidie.pdf"}
)

# Expliciet administrative strategie
chunks = chunk_text(subsidie_text, strategy="administrative")
```

**Voorbeeldoutput:**

Voor een subsidiebesluit:
```
Chunk 1: [SECTIE: BESLUIT]
         [TYPE: BELANGRIJK]
         
         Het college van B&W besluit subsidie te verlenen...

Chunk 2: [SECTIE: VOORWAARDEN]
         [TYPE: BELANGRIJK]
         
         Voor subsidie komt in aanmerking:
         - Organisaties met KvK-inschrijving
         - Activiteiten binnen gemeente...

Chunk 3: [SECTIE: UITSLUITINGEN]
         [TYPE: BELANGRIJK]
         
         Niet in aanmerking komen:
         - Commerciële activiteiten
         - Activiteiten buiten gemeente...

Chunk 4: [SECTIE: TERMIJNEN]
         [TYPE: BELANGRIJK]
         
         Aanvragen indienen uiterlijk 30 dagen voor...
```

**Detectie:**
De strategie detecteert ambtelijke documenten op basis van:
- Speciale secties (BESLUIT, MOTIVERING, VOORWAARDEN, UITSLUITINGEN, TERMIJNEN)
- Ambtelijk taalgebruik (college, gemeenteraad, subsidie, vergunning, etc.)
- Subsidie/vergunning termen (in aanmerking, voorwaarde, uitgesloten, aanvraag)
- Bestuursorgaan vermeldingen (gemeente, college, raad, provincie)
- Formele datum notaties
- Filename hints (besluit, subsidie, vergunning, etc.)

**Speciale secties altijd apart:**
Belangrijke secties zoals BESLUIT, VOORWAARDEN, TERMIJNEN krijgen altijd een eigen chunk,
ook als ze kort zijn. Dit maakt retrieval mogelijk voor specifieke vragen over
voorwaarden, uitsluitingen en procedures.

---

## 🔜 Nog Te Implementeren

### 5️⃣ Operationele & Technische Documenten
**Strategie:** `technical`  
**Status:** 🔜 TODO  
**File:** `chunking_strategies/strategies/technical.py`

**Focus:**
- Procedures & stappen behouden
- Code blocks intact
- Lijsten & specificaties
- Diagrammen & schema's (markers)

---

### 6️⃣ Databronnen met Entiteiten (Menus, etc.)
**Strategie:** `entities`  
**Status:** 🔜 TODO  
**File:** `chunking_strategies/strategies/entities.py`

**Focus:**
- Per-item chunking (elk menu item = chunk)
- Metadata extractie (prijs, beschrijving)
- Gestructureerde data behouden
- Review aggregatie

---

### 7️⃣ Mixed / Samengestelde Bronnen
**Strategie:** `mixed`  
**Status:** 🔜 TODO  
**File:** `chunking_strategies/strategies/mixed.py`

**Focus:**
- Detecteer verschillende secties
- Route naar juiste sub-strategie per sectie
- Combineer resultaten intelligent
- Behoud document coherentie

---

## 🧪 Testing

### Test Scripts
1. `test_chunking_modular.py` - Basis module tests
2. `test_financial_chunking.py` - Financiële document tests

### Run Tests
```bash
# Test basis systeem
python test_chunking_modular.py

# Test financiële strategie
python test_financial_chunking.py
```

### Test Status
- ✅ Module import
- ✅ Strategy registration
- ✅ Auto-detection
- ✅ Basic chunking
- ✅ Metadata support
- ✅ Error handling
- ✅ Financial document detection
- ✅ Financial table chunking (row/column/hybrid)
- ✅ Section splitting
- ✅ KPI extraction

---

## 📊 Architectuur

```
chunking_strategies/
├── __init__.py              # Public API + auto-registratie
├── base.py                  # ChunkStrategy & ChunkingConfig
├── registry.py              # Registry met auto-detectie
└── strategies/
    ├── __init__.py          
    ├── default.py           # ✅ Fallback
    ├── free_text.py         # ✅ Data type 1
    ├── financial_tables.py  # ✅ Data type 2
    ├── legal.py             # ✅ Data type 3
    ├── administrative.py    # ✅ Data type 4
    ├── technical.py         # 🔜 Data type 5
    ├── entities.py          # 🔜 Data type 6
    └── mixed.py             # 🔜 Data type 7
```

---

## 🚀 Next Steps

**Voor gebruiker:**
Per data type dat je wilt implementeren:
1. Geef voorbeelddata
2. Beschrijf specifieke requirements
3. Test met echte documenten
4. Itereer op basis van resultaten

**Klaar om te starten met data type 3, 4, 5, 6, of 7!**
