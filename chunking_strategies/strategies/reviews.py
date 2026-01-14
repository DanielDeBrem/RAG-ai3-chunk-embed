"""
Reviews Chunking Strategy

Geoptimaliseerd voor review data (Google Reviews, etc.).
Focus op meningen, sentiment, trends en pijnpunten terugvindbaar maken.

Kenmerken:
- 1 review = 1 chunk (atomic)
- Max 500-700 tokens per chunk
- Nooit meerdere reviews in 1 chunk
- Optionele enrichment metadata (sentiment, themes)
- Support voor rollup chunks (trends per locatie/thema)

Chunk types:
- review_atomic: Basis review chunk (1 review = 1 chunk)
- review_enriched: Met LLM-gegenereerde labels (optioneel)
- review_rollup: Periodieke samenvattingen (optioneel)
"""
import re
from typing import List, Optional, Dict, Any
from ..base import ChunkStrategy, ChunkingConfig


class ReviewsStrategy(ChunkStrategy):
    """
    Chunking strategie voor reviews (Google, Yelp, etc.).
    
    Ondersteunt:
    - Google Reviews
    - Yelp reviews
    - TripAdvisor reviews
    - Algemene customer reviews
    """
    
    name = "reviews"
    description = "Optimized for review data: Google Reviews, customer feedback (1 review = 1 chunk)"
    default_config = {
        "max_tokens": 700,  # Hard limit
        "target_tokens": 600,  # Soft target
        "chunk_type": "atomic",  # "atomic", "enriched", "rollup"
        "preserve_metadata": True,
        "split_long_reviews": True,
        "min_review_length": 10  # Minimale tekst lengte
    }
    
    # Review indicators
    REVIEW_INDICATORS = [
        r'(?i)\b(rating|beoordeling|sterren|stars)\b',
        r'(?i)\b(review|recensie|ervaring)\b',
        r'(?i)\b(google|yelp|tripadvisor)\b',
        r'[★⭐]{1,5}',  # Star ratings
        r'\b[1-5]/5\b',  # Numeric ratings
    ]
    
    # Sentiment keywords (voor detectie)
    SENTIMENT_KEYWORDS = {
        'positive': ['geweldig', 'fantastisch', 'uitstekend', 'top', 'prima', 'goed', 'fijn', 'aanrader'],
        'negative': ['slecht', 'teleurstellend', 'nooit meer', 'niet aanraden', 'verschrikkelijk', 'onacceptabel'],
        'neutral': ['oké', 'gemiddeld', 'redelijk', 'normaal']
    }
    
    # Theme keywords
    THEME_KEYWORDS = {
        'service': ['service', 'bediening', 'personeel', 'medewerker', 'helpdesk'],
        'quality': ['kwaliteit', 'niveau', 'uitvoering', 'afwerking'],
        'price': ['prijs', 'kosten', 'duur', 'prijskwaliteit', 'waardevol'],
        'location': ['locatie', 'ligging', 'bereikbaarheid', 'parkeren'],
        'cleanliness': ['schoon', 'hygiëne', 'netjes', 'vuil', 'onhygiënisch'],
        'speed': ['wachttijd', 'snel', 'traag', 'lang wachten', 'te laat'],
        'food': ['eten', 'maaltijd', 'gerecht', 'menu', 'keuken', 'smaak'],
        'atmosphere': ['sfeer', 'ambiance', 'gezellig', 'druk', 'rustig'],
    }
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Detecteer review data.
        
        Indicatoren:
        - Review keywords
        - Rating mentions
        - Star symbols
        - Sentiment language
        - Short, opinion-based text
        """
        sample = text[:1000]
        metadata = metadata or {}
        
        score = 0.3  # Base score
        
        # Check: review indicators
        review_indicator_count = sum(
            len(re.findall(pattern, sample))
            for pattern in self.REVIEW_INDICATORS
        )
        
        if review_indicator_count >= 2:
            score += 0.25
        elif review_indicator_count == 1:
            score += 0.15
        
        # Check: sentiment keywords
        sentiment_count = sum(
            sum(1 for word in words if word in sample.lower())
            for words in self.SENTIMENT_KEYWORDS.values()
        )
        
        if sentiment_count >= 3:
            score += 0.20
        elif sentiment_count >= 1:
            score += 0.10
        
        # Check: metadata hints
        if metadata.get("doc_type") == "review":
            score += 0.30
        
        if metadata.get("source") in ["google", "yelp", "tripadvisor", "reviews"]:
            score += 0.25
        
        if "rating" in metadata:
            score += 0.15
        
        # Check: filename hints
        fn = metadata.get("filename", "").lower()
        review_hints = ["review", "recensie", "google", "yelp", "feedback"]
        if any(hint in fn for hint in review_hints):
            score += 0.15
        
        # Check: short text (reviews zijn meestal kort)
        if len(text) < 1000:
            score += 0.10
        
        return min(1.0, max(0.0, score))
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk reviews: 1 review = 1 chunk.
        
        Strategie:
        1. Detecteer individuele reviews
        2. Chunk per review (NOOIT meerdere reviews in 1 chunk)
        3. Split lange reviews (>700 tokens)
        4. Optioneel: voeg enrichment metadata toe
        """
        chunk_type = config.extra_params.get("chunk_type", "atomic")
        max_tokens = config.extra_params.get("max_tokens", 700)
        split_long = config.extra_params.get("split_long_reviews", True)
        
        # Check of dit multi-review input is of single review
        reviews = self._extract_individual_reviews(text)
        
        if not reviews:
            # Single review
            reviews = [(text, None)]
        
        chunks: List[str] = []
        
        for review_text, review_metadata in reviews:
            # Skip te korte reviews
            min_length = config.extra_params.get("min_review_length", 10)
            if len(review_text.strip()) < min_length:
                continue
            
            # Estimate tokens (rough: ~4 chars per token for Dutch/English)
            estimated_tokens = len(review_text) // 4
            
            if estimated_tokens > max_tokens and split_long:
                # Split lange review
                sub_chunks = self._split_long_review(
                    review_text,
                    review_metadata,
                    max_tokens,
                    chunk_type
                )
                chunks.extend(sub_chunks)
            else:
                # Single chunk
                chunk = self._format_review_chunk(
                    review_text,
                    review_metadata,
                    chunk_type
                )
                chunks.append(chunk)
        
        return chunks if chunks else [text.strip()]
    
    def _extract_individual_reviews(self, text: str) -> List[tuple]:
        """
        Probeer individuele reviews te extraheren uit multi-review text.
        
        Returns:
            List van (review_text, metadata) tuples
        """
        reviews = []
        
        # Pattern 1: Reviews gescheiden door dubbele newlines + rating
        pattern1 = r'(?:Rating:|Beoordeling:|\*+|★+)\s*[1-5](?:/5)?\s*\n'
        if len(re.findall(pattern1, text)) > 1:
            parts = re.split(pattern1, text)
            for part in parts:
                if part.strip():
                    reviews.append((part.strip(), None))
            return reviews
        
        # Pattern 2: Reviews gescheiden door "Review by" of namen
        pattern2 = r'(?:Review by|Recensie van|Door)\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?)\s*\n'
        if len(re.findall(pattern2, text)) > 1:
            parts = re.split(pattern2, text)
            current_author = None
            for i, part in enumerate(parts):
                if i % 2 == 1:  # Dit is een naam
                    current_author = part
                elif part.strip():
                    metadata = {"author": current_author} if current_author else None
                    reviews.append((part.strip(), metadata))
            return reviews
        
        # Pattern 3: JSON-like format
        if text.strip().startswith('[') or text.strip().startswith('{'):
            # Mogelijk JSON, laat parser dit afhandelen
            return []
        
        # Geen duidelijke multi-review structuur
        return []
    
    def _split_long_review(
        self,
        review_text: str,
        review_metadata: Optional[Dict[str, Any]],
        max_tokens: int,
        chunk_type: str
    ) -> List[str]:
        """
        Split lange review in meerdere delen.
        Voeg part=1/2 indicator toe.
        """
        # Estimate max chars (tokens * 4)
        max_chars = max_tokens * 4
        
        chunks = []
        
        # Split op zinnen
        sentences = re.split(r'([.!?]+\s+)', review_text)
        
        current_part = ""
        part_num = 1
        total_parts = (len(review_text) // max_chars) + 1
        
        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i]
            punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
            full_sentence = sentence + punctuation
            
            if len(current_part) + len(full_sentence) <= max_chars:
                current_part += full_sentence
            else:
                if current_part:
                    # Create chunk for current part
                    chunk = self._format_review_chunk(
                        current_part,
                        review_metadata,
                        chunk_type,
                        part=f"{part_num}/{total_parts}"
                    )
                    chunks.append(chunk)
                    part_num += 1
                current_part = full_sentence
        
        # Last part
        if current_part:
            chunk = self._format_review_chunk(
                current_part,
                review_metadata,
                chunk_type,
                part=f"{part_num}/{total_parts}"
            )
            chunks.append(chunk)
        
        return chunks
    
    def _format_review_chunk(
        self,
        review_text: str,
        review_metadata: Optional[Dict[str, Any]],
        chunk_type: str,
        part: Optional[str] = None
    ) -> str:
        """
        Format review chunk op basis van type.
        """
        chunks_parts = []
        
        if chunk_type == "atomic":
            # Basic review chunk
            chunks_parts.append("[REVIEW]")
            if part:
                chunks_parts.append(f"[PART: {part}]")
            chunks_parts.append("")
            chunks_parts.append(f"Reviewtekst:\n\"{review_text}\"")
        
        elif chunk_type == "enriched":
            # Enriched met metadata (zou later door LLM worden aangevuld)
            chunks_parts.append("[REVIEW ENRICHED]")
            if part:
                chunks_parts.append(f"[PART: {part}]")
            
            # Detect sentiment (basic)
            sentiment = self._detect_basic_sentiment(review_text)
            themes = self._detect_themes(review_text)
            
            chunks_parts.append("")
            chunks_parts.append(f"Review over {', '.join(themes) if themes else 'algemeen'}.")
            chunks_parts.append(f"Sentiment: {sentiment}.")
            chunks_parts.append(f"\n\"{review_text}\"")
        
        elif chunk_type == "rollup":
            # Rollup chunk (zou worden gegenereerd uit meerdere reviews)
            chunks_parts.append("[REVIEW ROLLUP]")
            chunks_parts.append("")
            chunks_parts.append(review_text)
        
        else:
            # Fallback
            chunks_parts.append(review_text)
        
        return "\n".join(chunks_parts)
    
    def _detect_basic_sentiment(self, text: str) -> str:
        """Simpele sentiment detectie op basis van keywords."""
        text_lower = text.lower()
        
        pos_count = sum(1 for word in self.SENTIMENT_KEYWORDS['positive'] if word in text_lower)
        neg_count = sum(1 for word in self.SENTIMENT_KEYWORDS['negative'] if word in text_lower)
        
        if pos_count > neg_count and pos_count > 0:
            return "positief"
        elif neg_count > pos_count and neg_count > 0:
            return "negatief"
        else:
            return "neutraal"
    
    def _detect_themes(self, text: str) -> List[str]:
        """Detecteer themes in review tekst."""
        text_lower = text.lower()
        detected_themes = []
        
        for theme, keywords in self.THEME_KEYWORDS.items():
            if any(keyword in text_lower for keyword in keywords):
                detected_themes.append(theme)
        
        return detected_themes[:3]  # Max 3 themes
