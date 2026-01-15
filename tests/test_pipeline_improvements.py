#!/usr/bin/env python3
"""
Integration Test voor Pipeline Improvements V2

Test alle 3 nieuwe features:
1. Hybrid Search (Dense + BM25)
2. Parent-Child Chunking
3. HyDE (Hypothetical Questions)
"""

import sys
import logging
from typing import List, Dict

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test results storage
test_results = {
    "hybrid_search": {"status": "pending", "details": ""},
    "parent_child": {"status": "pending", "details": ""},
    "hyde": {"status": "pending", "details": ""}
}


def test_hybrid_search():
    """Test Hybrid Search module."""
    logger.info("=" * 60)
    logger.info("TEST 1: Hybrid Search (Dense + BM25)")
    logger.info("=" * 60)
    
    try:
        from hybrid_search import HybridRetriever
        
        # Mock data
        chunks = [
            {"chunk_id": "doc1#c0", "text": "De kosten bedragen €50.000 inclusief BTW", "metadata": {}},
            {"chunk_id": "doc1#c1", "text": "Het project loopt van januari tot maart 2025", "metadata": {}},
            {"chunk_id": "doc1#c2", "text": "De totale prijs is vijftigduizend euro met belasting", "metadata": {}},
            {"chunk_id": "doc2#c0", "text": "Contact opnemen via email@example.com", "metadata": {}},
            {"chunk_id": "doc2#c1", "text": "Telefoonnummer: 06-12345678", "metadata": {}},
        ]
        
        # Initialize retriever
        retriever = HybridRetriever(dense_weight=0.7, sparse_weight=0.3)
        retriever.index_chunks(chunks)
        
        # Mock dense results (from FAISS)
        dense_results = [
            ("doc1#c0", 0.9),
            ("doc1#c2", 0.85),
            ("doc2#c0", 0.7),
        ]
        
        # Test search
        query = "Wat zijn de kosten?"
        results = retriever.search(query, dense_results, top_k=3)
        
        logger.info(f"\nQuery: '{query}'")
        logger.info(f"Results: {len(results)} chunks\n")
        
        for i, result in enumerate(results, 1):
            logger.info(f"{i}. {result.chunk_id} (combined={result.combined_score:.4f})")
            logger.info(f"   Dense: {result.dense_score:.4f}, Sparse: {result.sparse_score:.4f}")
            logger.info(f"   Text: {result.text[:60]}...")
        
        # Validation
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        assert results[0].chunk_id == "doc1#c0", "Top result should be doc1#c0"
        assert results[0].combined_score > 0, "Combined score should be > 0"
        
        test_results["hybrid_search"]["status"] = "✅ PASS"
        test_results["hybrid_search"]["details"] = f"{len(results)} results, top score: {results[0].combined_score:.4f}"
        logger.info("\n✅ Hybrid Search test PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"\n❌ Hybrid Search test FAILED: {e}\n")
        test_results["hybrid_search"]["status"] = "❌ FAIL"
        test_results["hybrid_search"]["details"] = str(e)
        return False


def test_parent_child_chunking():
    """Test Parent-Child Chunking module."""
    logger.info("=" * 60)
    logger.info("TEST 2: Parent-Child Chunking")
    logger.info("=" * 60)
    
    try:
        from parent_child_chunking import ParentChildChunker
        
        # Test document
        text = """
        Het Taxatierapport van Camping de Brem dateert van december 2024. 
        De getaxeerde waarde bedraagt €12.500.000 voor het totale complex.
        Dit is gebaseerd op de huidige marktomstandigheden en vergelijkbare objecten.
        
        Het complex bestaat uit diverse accommodaties waaronder stacaravans en chalets.
        De locatie is zeer aantrekkelijk vanwege de nabijheid van het strand.
        Er zijn moderne sanitaire voorzieningen en recreatiefaciliteiten aanwezig.
        
        De exploitatie verloopt goed met een hoge bezettingsgraad gedurende het seizoen.
        De financiële cijfers tonen een stabiele omzet en positief resultaat.
        De vooruitzichten voor de komende jaren zijn gunstig.
        """
        
        # Initialize chunker
        chunker = ParentChildChunker(
            parent_max_chars=200,  # Small for testing
            child_max_chars=80,
            parent_overlap=50,
            child_overlap=20
        )
        
        # Chunk
        pairs = chunker.chunk(text, doc_id="test_doc")
        
        logger.info(f"\nCreated {len(pairs)} parent-child pairs")
        logger.info(f"Sample pairs:\n")
        
        for i, pair in enumerate(pairs[:3], 1):
            logger.info(f"Pair {i}:")
            logger.info(f"  Parent ID: {pair.parent_id}")
            logger.info(f"  Child ID: {pair.child_id}")
            logger.info(f"  Parent chars: {len(pair.parent_text)}")
            logger.info(f"  Child chars: {len(pair.child_text)}")
            logger.info(f"  Child text: {pair.child_text[:50]}...")
        
        # Validation
        assert len(pairs) > 0, "Should create at least 1 pair"
        assert all(len(p.child_text) <= 100 for p in pairs), "Child text should be <= 100 chars (with tolerance)"
        assert all(len(p.parent_text) >= len(p.child_text) for p in pairs), "Parent should be >= child"
        
        test_results["parent_child"]["status"] = "✅ PASS"
        test_results["parent_child"]["details"] = f"{len(pairs)} pairs created"
        logger.info("\n✅ Parent-Child Chunking test PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"\n❌ Parent-Child Chunking test FAILED: {e}\n")
        test_results["parent_child"]["status"] = "❌ FAIL"
        test_results["parent_child"]["details"] = str(e)
        return False


def test_hyde_generator():
    """Test HyDE Generator module."""
    logger.info("=" * 60)
    logger.info("TEST 3: HyDE (Hypothetical Questions)")
    logger.info("=" * 60)
    
    try:
        from hyde_generator import HyDEGenerator, SimpleQuestionGenerator
        import requests
        
        # Check if Ollama is available
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2)
            ollama_available = r.status_code == 200
        except:
            ollama_available = False
        
        # Test chunk
        chunk_text = """
        De kosten voor dit project bedragen €50.000 inclusief BTW.
        De planning is 3 maanden met een team van 5 personen.
        Het project start in januari 2025.
        """
        
        if ollama_available:
            logger.info("Testing LLM-based HyDE generation...\n")
            
            generator = HyDEGenerator(num_questions=3)
            questions = generator.generate_questions(chunk_text)
            
            logger.info(f"Generated {len(questions)} questions:")
            for i, q in enumerate(questions, 1):
                logger.info(f"  {i}. {q}")
            
            assert len(questions) > 0, "Should generate at least 1 question"
            assert any('?' in q for q in questions), "Questions should contain '?'"
            
        else:
            logger.info("⚠️  Ollama not available, testing template-based fallback...\n")
            
            simple_gen = SimpleQuestionGenerator()
            questions = simple_gen.generate_questions(chunk_text, num=3)
            
            logger.info(f"Generated {len(questions)} template questions:")
            for i, q in enumerate(questions, 1):
                logger.info(f"  {i}. {q}")
            
            assert len(questions) == 3, "Should generate 3 template questions"
        
        test_results["hyde"]["status"] = "✅ PASS"
        test_results["hyde"]["details"] = f"{len(questions)} questions, LLM={'yes' if ollama_available else 'no (fallback)'}"
        logger.info("\n✅ HyDE Generator test PASSED\n")
        return True
        
    except Exception as e:
        logger.error(f"\n❌ HyDE Generator test FAILED: {e}\n")
        test_results["hyde"]["status"] = "❌ FAIL"
        test_results["hyde"]["details"] = str(e)
        return False


def print_summary():
    """Print test summary."""
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    for feature, result in test_results.items():
        status = result["status"]
        details = result["details"]
        logger.info(f"{feature.upper()}: {status}")
        if details:
            logger.info(f"  → {details}")
    
    # Overall result
    passed = sum(1 for r in test_results.values() if "✅" in r["status"])
    total = len(test_results)
    
    logger.info("=" * 60)
    if passed == total:
        logger.info(f"🎉 ALL TESTS PASSED ({passed}/{total})")
        logger.info("=" * 60)
        return 0
    else:
        logger.info(f"⚠️  SOME TESTS FAILED ({passed}/{total})")
        logger.info("=" * 60)
        return 1


def main():
    """Run all integration tests."""
    logger.info("\n" + "=" * 60)
    logger.info("PIPELINE IMPROVEMENTS V2 - INTEGRATION TESTS")
    logger.info("=" * 60 + "\n")
    
    # Run tests
    test_hybrid_search()
    test_parent_child_chunking()
    test_hyde_generator()
    
    # Print summary
    exit_code = print_summary()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
