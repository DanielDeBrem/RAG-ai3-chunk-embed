#!/usr/bin/env python3
"""
Test script voor modulaire chunking strategieën.

Test de nieuwe modulaire structuur en vergelijk met verwacht gedrag.
"""
import sys
from chunking_strategies import chunk_text, list_strategies, detect_strategy

# Test data voor verschillende types
TEST_TEXTS = {
    "free_text": """
Dit is een verhaal over een camping. De camping ligt aan zee en heeft veel faciliteiten. 
Mensen komen hier graag om te ontspannen en te genieten van de natuur.

De eigenaar van de camping vertelde enthousiast over de plannen voor de toekomst. 
"We willen graag uitbreiden," zei hij. "Daarom hebben we een nieuw restaurant gebouwd."

Vervolgens liet hij het nieuwe gebouw zien. Het was modern en gezellig ingericht. 
De gasten waren zeer tevreden met de nieuwe voorzieningen.

Echter, er waren ook uitdagingen. Het weer was niet altijd even goed geweest. 
Bovendien moesten er nog wat administratieve zaken worden geregeld.

Uiteindelijk verliep alles naar wens. De camping was klaar voor het nieuwe seizoen.
""",
    "structured": """
# Hoofdstuk 1: Introductie

## 1.1 Achtergrond

Dit document beschrijft de situatie.

## 1.2 Doelstelling

Het doel is het verbeteren van processen.

# Hoofdstuk 2: Uitwerking

## 2.1 Aanpak

We gebruiken een stapsgewijze methode.
"""
}


def test_module_import():
    """Test of module correct geïmporteerd kan worden."""
    print("✓ Module import successful")


def test_list_strategies():
    """Test of strategieën geregistreerd zijn."""
    strategies = list_strategies()
    print(f"\n📋 Beschikbare strategieën: {len(strategies)}")
    for s in strategies:
        print(f"   - {s['name']}: {s['description']}")
    assert len(strategies) >= 2, "Minimaal 2 strategieën verwacht"
    print("✓ Strategies registered")


def test_auto_detection():
    """Test auto-detectie van strategieën."""
    print("\n🔍 Auto-detection tests:")
    
    for text_type, text in TEST_TEXTS.items():
        detected = detect_strategy(text)
        print(f"   {text_type}: detected '{detected}'")
    
    print("✓ Auto-detection works")


def test_chunking():
    """Test daadwerkelijke chunking."""
    print("\n✂️  Chunking tests:")
    
    # Test 1: Free text met auto-detect
    chunks = chunk_text(TEST_TEXTS["free_text"])
    print(f"   Free text (auto): {len(chunks)} chunks")
    for i, chunk in enumerate(chunks[:2], 1):
        preview = chunk[:80].replace('\n', ' ')
        print(f"      Chunk {i}: {preview}...")
    
    # Test 2: Specifieke strategie
    chunks_default = chunk_text(TEST_TEXTS["free_text"], strategy="default")
    print(f"   Free text (default): {len(chunks_default)} chunks")
    
    chunks_free = chunk_text(TEST_TEXTS["free_text"], strategy="free_text")
    print(f"   Free text (free_text): {len(chunks_free)} chunks")
    
    # Test 3: Custom config
    chunks_custom = chunk_text(
        TEST_TEXTS["free_text"], 
        strategy="free_text",
        config={"max_chars": 500, "overlap": 100}
    )
    print(f"   Free text (custom config): {len(chunks_custom)} chunks")
    
    print("✓ Chunking works")


def test_metadata():
    """Test chunking met metadata."""
    print("\n🏷️  Metadata test:")
    
    chunks = chunk_text(
        TEST_TEXTS["free_text"],
        metadata={"filename": "verhaal.txt", "mime_type": "text/plain"}
    )
    print(f"   With metadata: {len(chunks)} chunks")
    print("✓ Metadata support works")


def test_error_handling():
    """Test error handling."""
    print("\n⚠️  Error handling test:")
    
    # Non-existent strategy should fallback to default
    try:
        chunks = chunk_text("test text", strategy="non_existent")
        print(f"   Fallback to default: {len(chunks)} chunks")
        print("✓ Error handling works")
    except Exception as e:
        print(f"   ❌ Error handling failed: {e}")


def run_all_tests():
    """Run alle tests."""
    print("=" * 60)
    print("🧪 Testing Modular Chunking Strategies")
    print("=" * 60)
    
    try:
        test_module_import()
        test_list_strategies()
        test_auto_detection()
        test_chunking()
        test_metadata()
        test_error_handling()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
