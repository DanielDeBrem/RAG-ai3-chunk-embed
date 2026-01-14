#!/usr/bin/env python3
"""
Test script voor Review Summarizer → AI-3 DataFactory integratie.

Simuleert RS die reviews en menu data stuurt naar de DataFactory.
Logt complete e2e flow voor evaluatie.
"""
import requests
import json
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/revsummer_test.log', mode='w')
    ]
)
logger = logging.getLogger(__name__)

AI3_URL = "http://localhost:9000"

# Test data: Restaurant with reviews and menu
TEST_RESTAURANT_ID = "test_restaurant_123"
TEST_RESTAURANT_NAME = "De Smakelijke Hoek"

TEST_REVIEWS = """Review door Jan de Vries:
Rating: 5/5
Geweldig restaurant met uitstekende service en heerlijk eten. De biefstuk was perfect gebakken en het personeel was zeer vriendelijk. Absoluut een aanrader!

Review door Marie Jansen:
Rating: 3/5
Eten was prima maar de wachttijd was te lang. We moesten 45 minuten wachten op ons hoofdgerecht. De kwaliteit van het eten was goed, maar de service kan beter.

Review door Piet Bakker:
Rating: 4/5
Goede sfeer en lekkere gerechten. De prijzen zijn redelijk en de porties zijn ruim. Zeker geschikt voor een gezellige avond uit. Kleine minpunt: het was vrij druk en daardoor wat lawaaierig.

Review door Sophie Mulder:
Rating: 5/5
Fantastische ervaring! Het personeel kende het menu goed en kon uitstekende aanbevelingen doen. De wijnselectie was ook top. Komen zeker terug!

Review door Hans Peters:
Rating: 2/5
Teleurstellend. Het eten was lauw en de bediening onverschillig. Voor deze prijzen verwacht je meer. We zullen hier niet snel terugkomen.
"""

TEST_MENU = """Biefstuk met friet
Malse biefstuk van de grill met verse frietjes en huisgemaakte kruidenboter
€ 24.50

Caesarsalade met kip
Verse romaine sla met gegrilde kip, parmezaanse kaas, croutons en Caesar dressing
€ 12.00

Tiramisu
Klassieke Italiaanse tiramisu met mascarpone, koffie en cacao
€ 7.50

Gegrilde zalm
Verse zalm met gegrilde groenten en citroenboterraus
€ 22.00

Vegetarische pasta
Penne met gegrilde groenten, zongedroogde tomaten en basilicumpesto
€ 15.50

Huisgemaakte tomatensoep
Romige tomatensoep met verse basilicum en knoflook croutons
€ 6.50
"""

TEST_RESTAURANT_INFO = """Restaurant De Smakelijke Hoek

Adres: Hoofdstraat 123, 1234 AB Amsterdam
Telefoon: 020-1234567
Email: info@desmakelijkehoek.nl

Openingstijden:
Ma-Vr: 17:00 - 22:00
Za-Zo: 12:00 - 22:00

Keuken: Modern Nederlands met internationale invloeden
Aantal zitplaatsen: 60
Parkeren: Betaald parkeren in de buurt
Toegankelijkheid: Rolstoeltoegankelijk
"""


def test_health():
    """Test health endpoint"""
    logger.info("=" * 80)
    logger.info("STEP 1: Health Check")
    logger.info("=" * 80)
    
    try:
        response = requests.get(f"{AI3_URL}/health", timeout=5)
        logger.info(f"✓ Health check: {response.json()}")
        return True
    except Exception as e:
        logger.error(f"✗ Health check failed: {e}")
        return False


def ingest_reviews():
    """Ingest Google reviews"""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Ingest Reviews")
    logger.info("=" * 80)
    logger.info(f"Filename: reviews_{TEST_RESTAURANT_ID}.txt")
    logger.info(f"Text length: {len(TEST_REVIEWS)} chars")
    logger.info(f"Expected: Auto-detect 'reviews' strategy")
    
    payload = {
        "tenant_id": "revsummer",
        "project_id": TEST_RESTAURANT_ID,
        "filename": f"reviews_{TEST_RESTAURANT_ID}.txt",
        "text": TEST_REVIEWS,
        "metadata": {
            "restaurant_name": TEST_RESTAURANT_NAME,
            "source": "google_reviews"
        }
    }
    
    try:
        logger.info(f"POST {AI3_URL}/ingest")
        logger.info(f"Payload keys: {list(payload.keys())}")
        
        response = requests.post(
            f"{AI3_URL}/ingest",
            json=payload,
            timeout=120
        )
        
        response.raise_for_status()
        result = response.json()
        
        logger.info("=" * 80)
        logger.info("✓ REVIEWS INGEST SUCCESS")
        logger.info("=" * 80)
        logger.info(f"Response: {json.dumps(result, indent=2)}")
        logger.info(f"Chunks created: {result.get('chunks_added', 0)}")
        logger.info(f"Expected: ~5 chunks (1 per review)")
        
        return result
    except Exception as e:
        logger.error(f"✗ Reviews ingest failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


def ingest_menu():
    """Ingest menu data"""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Ingest Menu")
    logger.info("=" * 80)
    logger.info(f"Filename: menu_{TEST_RESTAURANT_ID}.txt")
    logger.info(f"Text length: {len(TEST_MENU)} chars")
    logger.info(f"Expected: Auto-detect 'menus' strategy")
    
    payload = {
        "tenant_id": "revsummer",
        "project_id": TEST_RESTAURANT_ID,
        "filename": f"menu_{TEST_RESTAURANT_ID}.txt",
        "text": TEST_MENU,
        "metadata": {
            "restaurant_name": TEST_RESTAURANT_NAME
        }
    }
    
    try:
        logger.info(f"POST {AI3_URL}/ingest")
        logger.info(f"Payload keys: {list(payload.keys())}")
        
        response = requests.post(
            f"{AI3_URL}/ingest",
            json=payload,
            timeout=120
        )
        
        response.raise_for_status()
        result = response.json()
        
        logger.info("=" * 80)
        logger.info("✓ MENU INGEST SUCCESS")
        logger.info("=" * 80)
        logger.info(f"Response: {json.dumps(result, indent=2)}")
        logger.info(f"Chunks created: {result.get('chunks_added', 0)}")
        logger.info(f"Expected: ~6 chunks (1 per dish)")
        
        return result
    except Exception as e:
        logger.error(f"✗ Menu ingest failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


def ingest_info():
    """Ingest restaurant info"""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: Ingest Restaurant Info")
    logger.info("=" * 80)
    logger.info(f"Filename: info_{TEST_RESTAURANT_ID}.txt")
    logger.info(f"Text length: {len(TEST_RESTAURANT_INFO)} chars")
    logger.info(f"Expected: Use 'default' strategy")
    
    payload = {
        "tenant_id": "revsummer",
        "project_id": TEST_RESTAURANT_ID,
        "filename": f"info_{TEST_RESTAURANT_ID}.txt",
        "text": TEST_RESTAURANT_INFO,
        "metadata": {
            "restaurant_name": TEST_RESTAURANT_NAME
        }
    }
    
    try:
        logger.info(f"POST {AI3_URL}/ingest")
        logger.info(f"Payload keys: {list(payload.keys())}")
        
        response = requests.post(
            f"{AI3_URL}/ingest",
            json=payload,
            timeout=120
        )
        
        response.raise_for_status()
        result = response.json()
        
        logger.info("=" * 80)
        logger.info("✓ INFO INGEST SUCCESS")
        logger.info("=" * 80)
        logger.info(f"Response: {json.dumps(result, indent=2)}")
        logger.info(f"Chunks created: {result.get('chunks_added', 0)}")
        
        return result
    except Exception as e:
        logger.error(f"✗ Info ingest failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


def search_reviews():
    """Search in reviews"""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 5: Search Reviews")
    logger.info("=" * 80)
    
    query = "Wat vinden klanten van de service?"
    logger.info(f"Query: {query}")
    
    payload = {
        "tenant_id": "revsummer",
        "project_id": TEST_RESTAURANT_ID,
        "query": query,
        "top_k": 3
    }
    
    try:
        response = requests.post(
            f"{AI3_URL}/search",
            json=payload,
            timeout=30
        )
        
        response.raise_for_status()
        result = response.json()
        
        logger.info("=" * 80)
        logger.info("✓ SEARCH SUCCESS")
        logger.info("=" * 80)
        logger.info(f"Found {len(result.get('chunks', []))} chunks")
        
        for i, chunk in enumerate(result.get('chunks', [])[:3], 1):
            logger.info(f"\n--- Chunk {i} (score: {chunk.get('score', 0):.3f}) ---")
            logger.info(f"Doc ID: {chunk.get('doc_id')}")
            logger.info(f"Text: {chunk.get('text', '')[:200]}...")
        
        return result
    except Exception as e:
        logger.error(f"✗ Search failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None


def main():
    """Run complete test"""
    logger.info("\n" + "#" * 80)
    logger.info("# REVIEW SUMMARIZER → AI-3 DATAFACTORY E2E TEST")
    logger.info("#" * 80)
    
    # Step 1: Health check
    if not test_health():
        logger.error("Health check failed, aborting test")
        return False
    
    # Step 2: Ingest reviews
    reviews_result = ingest_reviews()
    if not reviews_result:
        logger.error("Reviews ingest failed")
        return False
    
    # Step 3: Ingest menu
    menu_result = ingest_menu()
    if not menu_result:
        logger.error("Menu ingest failed")
        return False
    
    # Step 4: Ingest info
    info_result = ingest_info()
    
    # Step 5: Search
    search_result = search_reviews()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"✓ Reviews ingested: {reviews_result.get('chunks_added', 0)} chunks")
    logger.info(f"✓ Menu ingested: {menu_result.get('chunks_added', 0)} chunks")
    logger.info(f"✓ Info ingested: {info_result.get('chunks_added', 0) if info_result else 0} chunks")
    logger.info(f"✓ Search returned: {len(search_result.get('chunks', [])) if search_result else 0} chunks")
    
    logger.info("\n" + "=" * 80)
    logger.info("EVALUATION")
    logger.info("=" * 80)
    logger.info("Check the server logs for:")
    logger.info("  1. Strategy detection scores for reviews/menu")
    logger.info("  2. Chosen chunking strategy")
    logger.info("  3. Number of chunks created")
    logger.info("  4. Enrichment process")
    logger.info("\nLog file: logs/revsummer_test.log")
    logger.info("Server log: Check console output of DataFactory")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
