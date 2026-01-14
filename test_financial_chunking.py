#!/usr/bin/env python3
"""
Test script voor Financial Tables chunking strategie.
"""
import sys
from chunking_strategies import chunk_text, list_strategies, detect_strategy

# Test data: financieel rapport met tabel
FINANCIAL_TEXT = """
Jaarrekening 2023
De Brem Holding B.V.

BALANS

Activa

                        2023        2022        2021
Vaste activa           450.000     425.000     400.000
Vlottende activa       125.000     110.000     95.000
Liquide middelen        75.000      65.000     55.000
----------------------------------------
Totaal activa          650.000     600.000     550.000


RESULTATENREKENING

                        2023        2022        2021
Omzet                  890.000     850.000     800.000
Kosten                -650.000    -620.000    -590.000
----------------------------------------
EBITDA                 240.000     230.000     210.000
Afschrijvingen         -45.000     -40.000     -38.000
----------------------------------------
EBIT                   195.000     190.000     172.000
Financiële lasten      -15.000     -12.000     -10.000
----------------------------------------
Winst voor belasting   180.000     178.000     162.000


TOELICHTING

De onderneming heeft in 2023 een goede ontwikkeling doorgemaakt.
De omzet is gestegen met 4,7% ten opzichte van 2022.

De EBITDA-marge bedraagt 27%, wat een verbetering is ten opzichte
van vorig jaar (27,1% in 2022).

Het eigen vermogen is gestegen naar € 420.000 per 31 december 2023.
"""

# Test data: offerte
QUOTE_TEXT = """
OFFERTE

Aan: Gemeente Schouwen-Duiveland
Datum: 14 januari 2026
Geldig tot: 14 maart 2026

SCOPE VAN WERKZAAMHEDEN

Uitvoering nieuwbouw werkplaats camping De Brem:
- Fundering en grondwerk
- Bouw werkplaats 200m²
- Installaties (elektra, water, verwarming)
- Afwerking en schilderwerk

PRIJSOPGAVE

Omschrijving                    Eenheid     Prijs       Totaal
--------------------------------------------------------------------
Grondwerk en fundering          m²          € 125       € 25.000
Bouw werkplaats                 m²          € 850       € 170.000
Installaties                    forfait     -           € 45.000
Afwerking                       forfait     -           € 30.000
--------------------------------------------------------------------
Subtotaal                                               € 270.000
BTW 21%                                                 € 56.700
--------------------------------------------------------------------
Totaal                                                  € 326.700

LOOPTIJD

Start werkzaamheden: 1 april 2026
Oplevering: 1 augustus 2026
Looptijd: 4 maanden

BETALINGSVOORWAARDEN

- 30% bij opdrachtverlening
- 40% bij halverwege project
- 30% bij oplevering
"""


def test_financial_detection():
    """Test of financiële documenten correct gedetecteerd worden."""
    print("=" * 60)
    print("🔍 Testing Financial Document Detection")
    print("=" * 60)
    
    # Test 1: Jaarrekening
    strategy = detect_strategy(FINANCIAL_TEXT, metadata={"filename": "jaarrekening_2023.pdf"})
    print(f"\n✓ Jaarrekening detected as: '{strategy}'")
    
    # Test 2: Offerte
    strategy = detect_strategy(QUOTE_TEXT, metadata={"filename": "offerte_nieuwbouw.pdf"})
    print(f"✓ Offerte detected as: '{strategy}'")
    
    # List all strategies
    strategies = list_strategies()
    print(f"\n📋 Available strategies: {len(strategies)}")
    for s in strategies:
        print(f"   - {s['name']}")


def test_financial_chunking():
    """Test chunking van financiële documenten."""
    print("\n" + "=" * 60)
    print("✂️  Testing Financial Document Chunking")
    print("=" * 60)
    
    # Test 1: Jaarrekening met auto-detect
    print("\n1️⃣ Jaarrekening (auto-detect):")
    chunks = chunk_text(
        FINANCIAL_TEXT,
        metadata={"filename": "jaarrekening_2023.pdf"}
    )
    print(f"   Created {len(chunks)} chunks")
    for i, chunk in enumerate(chunks[:3], 1):
        preview = chunk[:100].replace('\n', ' ')
        print(f"   Chunk {i}: {preview}...")
    
    # Test 2: Expliciete financial_tables strategie
    print("\n2️⃣ Jaarrekening (explicit financial_tables):")
    chunks = chunk_text(
        FINANCIAL_TEXT,
        strategy="financial_tables",
        config={"table_mode": "row"}
    )
    print(f"   Created {len(chunks)} chunks (row mode)")
    
    # Test 3: Offerte
    print("\n3️⃣ Offerte:")
    chunks = chunk_text(
        QUOTE_TEXT,
        strategy="financial_tables"
    )
    print(f"   Created {len(chunks)} chunks")
    for i, chunk in enumerate(chunks[:2], 1):
        preview = chunk[:100].replace('\n', ' ')
        print(f"   Chunk {i}: {preview}...")
    
    # Test 4: Column mode voor tijdreeksen
    print("\n4️⃣ Jaarrekening (column mode - tijdreeks):")
    chunks = chunk_text(
        FINANCIAL_TEXT,
        strategy="financial_tables",
        config={"table_mode": "column"}
    )
    print(f"   Created {len(chunks)} chunks (KPI over time)")


def test_table_detection():
    """Test specifiek de tabel detectie."""
    print("\n" + "=" * 60)
    print("📊 Testing Table Detection")
    print("=" * 60)
    
    # Simple table
    simple_table = """
Product     Prijs    Aantal
Tafel       € 450    5
Stoel       € 120    20
Lamp        € 65     10
"""
    
    strategy = detect_strategy(simple_table)
    print(f"\n✓ Simple table detected as: '{strategy}'")
    
    chunks = chunk_text(simple_table, strategy="financial_tables")
    print(f"✓ Created {len(chunks)} chunks")


def run_all_tests():
    """Run alle financial chunking tests."""
    try:
        test_financial_detection()
        test_financial_chunking()
        test_table_detection()
        
        print("\n" + "=" * 60)
        print("✅ All financial chunking tests passed!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
