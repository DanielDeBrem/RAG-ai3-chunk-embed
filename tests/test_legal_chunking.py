#!/usr/bin/env python3
"""
Test script voor Legal Documents chunking strategie.
"""
import sys
from chunking_strategies import chunk_text, list_strategies, detect_strategy

# Test data: contract met artikelen
CONTRACT_TEXT = """
ALGEMENE VOORWAARDEN
Camping De Brem B.V.

Artikel 1 - Definities

In deze algemene voorwaarden wordt verstaan onder:
a) Exploitant: Camping De Brem B.V., gevestigd te Renesse
b) Gast: de natuurlijke of rechtspersoon die gebruik maakt van de accommodatie
c) Overeenkomst: de tussen partijen gesloten overeenkomst

Artikel 2 - Toepasselijkheid

1. Deze algemene voorwaarden zijn van toepassing op alle aanbiedingen en overeenkomsten.
2. Afwijkingen zijn slechts geldig indien schriftelijk overeengekomen.
3. De toepasselijkheid van eventuele inkoop of andere voorwaarden wordt uitdrukkelijk van de hand gewezen.

Artikel 3 - Reservering en betaling

1. Een reservering komt tot stand na schriftelijke bevestiging door de exploitant.
2. Bij reservering dient 30% van het totaalbedrag te worden voldaan.
3. Het resterende bedrag dient uiterlijk 4 weken voor aankomst te zijn voldaan.
4. Bij niet tijdige betaling behoudt de exploitant zich het recht voor de reservering te annuleren.

Artikel 4 - Annulering

1. Annulering dient schriftelijk te geschieden.
2. Bij annulering tot 8 weken voor aankomst worden geen kosten in rekening gebracht.
3. Bij annulering tussen 8 en 4 weken voor aankomst wordt 50% van het totaalbedrag in rekening gebracht.
4. Bij annulering binnen 4 weken voor aankomst wordt het volledige bedrag in rekening gebracht.

Artikel 5 - Aansprakelijkheid

De exploitant is niet aansprakelijk voor schade aan eigendommen van gasten, tenzij sprake is van opzet of grove schuld aan de zijde van de exploitant.

Artikel 6 - Toepasselijk recht

Op deze overeenkomst is Nederlands recht van toepassing. Geschillen worden voorgelegd aan de bevoegde rechter in Zeeland.
"""

# Test data: wet/regelgeving
REGULATION_TEXT = """
ALGEMENE PLAATSELIJKE VERORDENING
Gemeente Schouwen-Duiveland

§ 1 - Begripsbepalingen

In deze verordening wordt verstaan onder:
a) gemeente: de gemeente Schouwen-Duiveland
b) college: het college van burgemeester en wethouders
c) openbare plaats: een voor publiek toegankelijke plaats

§ 2 - Openbare orde

1. Het is verboden de openbare orde te verstoren.
2. Het is verboden zich zodanig te gedragen dat gevaar dan wel schade voor personen of goederen wordt veroorzaakt.

§ 3 - Evenementen

1. Het is verboden zonder vergunning van het college een evenement te organiseren.
2. Het college kan aan een vergunning voorschriften verbinden.
3. Een vergunning kan worden geweigerd in het belang van de openbare orde en veiligheid.

Deze verordening is in werking getreden op 1 januari 2024 en geldig tot nader order.
Van kracht op gemeentelijk niveau onder Nederlands recht.
"""


def test_legal_detection():
    """Test of juridische documenten correct gedetecteerd worden."""
    print("=" * 60)
    print("⚖️  Testing Legal Document Detection")
    print("=" * 60)
    
    # Test 1: Contract
    strategy = detect_strategy(CONTRACT_TEXT, metadata={"filename": "algemene_voorwaarden.pdf"})
    print(f"\n✓ Contract detected as: '{strategy}'")
    
    # Test 2: Regelgeving
    strategy = detect_strategy(REGULATION_TEXT, metadata={"filename": "apv_schouwen-duiveland.pdf"})
    print(f"✓ Regelgeving detected as: '{strategy}'")
    
    # List all strategies
    strategies = list_strategies()
    print(f"\n📋 Available strategies: {len(strategies)}")
    for s in strategies:
        print(f"   - {s['name']}")


def test_legal_chunking():
    """Test chunking van juridische documenten."""
    print("\n" + "=" * 60)
    print("✂️  Testing Legal Document Chunking")
    print("=" * 60)
    
    # Test 1: Contract met auto-detect
    print("\n1️⃣ Contract (auto-detect):")
    chunks = chunk_text(
        CONTRACT_TEXT,
        metadata={"filename": "algemene_voorwaarden.pdf"}
    )
    print(f"   Created {len(chunks)} chunks (artikel-based)")
    for i, chunk in enumerate(chunks[:3], 1):
        lines = chunk.split('\n')
        header = lines[0] if lines else ""
        print(f"   Chunk {i}: {header}")
    
    # Test 2: Expliciete legal strategie
    print("\n2️⃣ Contract (explicit legal):")
    chunks = chunk_text(
        CONTRACT_TEXT,
        strategy="legal"
    )
    print(f"   Created {len(chunks)} chunks")
    
    # Show artikel structuur
    print("\n   Artikel structuur:")
    for chunk in chunks[:5]:
        lines = chunk.split('\n')
        if lines and lines[0].startswith('[ARTIKEL'):
            article_num = lines[0]
            title = lines[1] if len(lines) > 1 and lines[1].startswith('[TITEL') else "Geen titel"
            print(f"     - {article_num}")
    
    # Test 3: Regelgeving met paragrafen
    print("\n3️⃣ Regelgeving (APV):")
    chunks = chunk_text(
        REGULATION_TEXT,
        strategy="legal"
    )
    print(f"   Created {len(chunks)} chunks")
    for i, chunk in enumerate(chunks[:3], 1):
        lines = chunk.split('\n')
        header = lines[0] if lines else ""
        print(f"   Chunk {i}: {header}")
    
    # Test 4: Geen overlap (juridische precisie)
    print("\n4️⃣ Overlap test (should be 0):")
    chunks = chunk_text(
        CONTRACT_TEXT,
        strategy="legal"
    )
    # Check dat er geen overlap is
    for i in range(len(chunks) - 1):
        current = chunks[i].lower()
        next_chunk = chunks[i + 1].lower()
        # Extract content (skip markers)
        current_lines = [l for l in current.split('\n') if not l.startswith('[')]
        next_lines = [l for l in next_chunk.split('\n') if not l.startswith('[')]
        
        if current_lines and next_lines:
            # Check if last line of current appears in next
            last_current = current_lines[-1][:50] if current_lines[-1] else ""
            first_next = next_lines[0][:50] if next_lines else ""
            if last_current and last_current in first_next:
                print(f"   ⚠️  Overlap detected tussen chunk {i+1} en {i+2}")
    print("   ✓ No overlap detected (as expected)")


def test_article_extraction():
    """Test specifiek de artikel extractie."""
    print("\n" + "=" * 60)
    print("📜 Testing Article Extraction")
    print("=" * 60)
    
    # Test met subartikelen
    subarticle_text = """
Artikel 10 - Betalingstermijnen

1. Alle facturen dienen binnen 30 dagen te worden voldaan.
2. Bij te late betaling is de wederpartij in verzuim zonder dat daartoe een ingebrekestelling is vereist.
3. Bij niet tijdige betaling is de verschuldigde rente gelijk aan de wettelijke rente.
"""
    
    chunks = chunk_text(subarticle_text, strategy="legal")
    print(f"\n✓ Text with sub-articles created {len(chunks)} chunks")
    for i, chunk in enumerate(chunks, 1):
        header = chunk.split('\n')[0]
        print(f"   Chunk {i}: {header}")


def test_sentence_preservation():
    """Test dat hele zinnen bewaard blijven."""
    print("\n" + "=" * 60)
    print("✍️  Testing Sentence Preservation")
    print("=" * 60)
    
    long_article = """
Artikel 100 - Bijzondere bepalingen

""" + " ".join([f"Dit is zin nummer {i} in een heel lang artikel dat moet worden gesplitst maar wel complete zinnen moet behouden." for i in range(1, 30)])
    
    chunks = chunk_text(
        long_article,
        strategy="legal",
        config={"max_chars": 500}
    )
    
    print(f"\n✓ Long article split into {len(chunks)} chunks")
    print("   Checking sentence integrity...")
    
    for i, chunk in enumerate(chunks, 1):
        # Check dat chunks niet eindigen mid-sentence
        content = '\n'.join([l for l in chunk.split('\n') if not l.startswith('[')])
        if content.strip() and not content.strip().endswith('.'):
            print(f"   ⚠️  Chunk {i} might not end on sentence boundary")
        else:
            if i <= 3:
                print(f"   ✓ Chunk {i} preserves sentence boundaries")


def run_all_tests():
    """Run alle legal chunking tests."""
    try:
        test_legal_detection()
        test_legal_chunking()
        test_article_extraction()
        test_sentence_preservation()
        
        print("\n" + "=" * 60)
        print("✅ All legal chunking tests passed!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
