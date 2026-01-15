# Review Summarizer → AI-3 DataFactory Integration

## 📤 Prompt voor Cline op Review Summarizer (AI-4)

```
Stuur restaurant data naar AI-3 DataFactory voor RAG processing.

DATAFACTORY API: http://AI-3-IP:9000

⚠️ BELANGRIJK: MENU INGEST IS BESCHIKBAAR!
Gebruik EXACT HETZELFDE endpoint (/ingest) voor reviews EN menus.
Er is GEEN apart menu endpoint - beide gebruiken POST /ingest.
De filename hint (menu_*.txt) activeert automatisch de menu strategie.

=== BELANGRIJK: AUTO-DETECTION ===
AI-3 DataFactory heeft auto-detection voor reviews en menus.
Lever alleen RUWE DATA aan met hints in filename.
AI-3 doet automatisch:
- Document type detectie (review/menu)
- Chunking strategy selectie
- Metadata enrichment (sentiment, cuisine, etc.)

=== DATA AANLEVEREN ===

Voor elk restaurant, 2-3 requests:

1. GOOGLE REVIEWS (ruwe data)
POST /ingest
{
  "tenant_id": "revsummer",
  "project_id": "{restaurant_id}",
  "filename": "reviews_{restaurant_id}.txt",
  "text": "{alle reviews als platte text}",
  "metadata": {
    "restaurant_name": "{naam}",
    "source": "google_reviews"
  }
}

2. MENU/GERECHTEN (ruwe data)
POST /ingest
{
  "tenant_id": "revsummer",
  "project_id": "{restaurant_id}",
  "filename": "menu_{restaurant_id}.txt",
  "text": "{alle gerechten als platte text}",
  "metadata": {
    "restaurant_name": "{naam}"
  }
}

3. RESTAURANT INFO (optioneel)
POST /ingest
{
  "tenant_id": "revsummer",
  "project_id": "{restaurant_id}",
  "filename": "info_{restaurant_id}.txt",
  "text": "{adres, openingstijden, contact}"
}

NIET meegeven: document_type, chunk_strategy, cuisine_type
→ Dit detecteert AI-3 AUTOMATISCH via document analyzer!

=== TEXT FORMAT ===

Reviews (één string met alle reviews):
```
Review door Jan:
Rating: 5/5
Geweldig restaurant met uitstekende service en heerlijk eten. Aanrader!

Review door Marie:
Rating: 3/5
Eten was prima maar wachttijd was te lang.

Review door Piet:
Rating: 4/5
Goede sfeer, vriendelijk personeel, lekkere gerechten.
```

Menu (één string met alle gerechten):
```
Biefstuk met friet
Malse biefstuk van de grill met verse frietjes
€ 24.50

Tiramisu
Klassieke Italiaanse tiramisu met mascarpone
€ 7.50

Caesarsalade
Verse sla met kip, parmezaan en dressing
€ 12.00
```

=== IMPLEMENTATIE ===

```python
import requests

AI3_URL = "http://AI-3-IP:9000"

for restaurant in restaurants:
    # 1. Reviews aanleveren
    reviews_text = "\n\n".join([
        f"Review door {r.author}:\nRating: {r.rating}/5\n{r.text}"
        for r in restaurant.google_reviews
    ])
    
    response = requests.post(f"{AI3_URL}/ingest", json={
        "tenant_id": "revsummer",
        "project_id": str(restaurant.id),
        "filename": f"reviews_{restaurant.id}.txt",
        "text": reviews_text,
        "metadata": {
            "restaurant_name": restaurant.name,
            "source": "google_reviews"
        }
    })
    print(f"✓ Reviews: {response.json()['chunks_added']} chunks")
    
    # 2. Menu aanleveren (als aanwezig)
    if restaurant.menu_items:
        menu_text = "\n\n".join([
            f"{item.name}\n{item.description}\n€ {item.price}"
            for item in restaurant.menu_items
        ])
        
        response = requests.post(f"{AI3_URL}/ingest", json={
            "tenant_id": "revsummer",
            "project_id": str(restaurant.id),
            "filename": f"menu_{restaurant.id}.txt",
            "text": menu_text,
            "metadata": {
                "restaurant_name": restaurant.name
            }
        })
        print(f"✓ Menu: {response.json()['chunks_added']} chunks")
```

AI-3 detecteert automatisch via filename hints:
- "reviews_" in filename → reviews strategy (1 review = 1 chunk)
- "menu_" in filename → menus strategy (1 gerecht = 1 chunk)
- Auto-enrichment: sentiment, themes, cuisine type, etc.

Klaar! Geen chunk_strategy of metadata nodig.
```

## 🔍 Zoeken

```python
# Zoek reviews
response = requests.post(f"{AI3_URL}/search", json={
    "tenant_id": "revsummer",
    "project_id": str(restaurant_id),
    "query": "Wat vinden mensen van de service?",
    "top_k": 10
})

chunks = response.json()["chunks"]
# Gebruik chunks in je 70B LLM voor sentiment analyse
```

## ✅ Dat is het!

Lever alleen ruwe text aan met hints in filename.
AI-3 doet alle intelligence: detectie, chunking, enrichment.
