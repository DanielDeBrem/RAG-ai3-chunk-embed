"""
HyDE (Hypothetical Document Embeddings) Generator

Genereert hypothetische vragen die een chunk zou kunnen beantwoorden.
Dit overbrugt de gap tussen queries (vragen) en chunks (statements).

Voorbeeld:
- Chunk: "De kosten bedragen €50.000 inclusief BTW"
- Generated questions:
  1. "Wat zijn de kosten?"
  2. "Hoeveel kost het?"
  3. "Is BTW inbegrepen in de prijs?"
"""

from __future__ import annotations

import logging
import os
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# LLM Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL_HYDE", "llama3.1:8b")  # Use 8b for speed
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "30"))


@dataclass
class HyDEResult:
    """Result of HyDE generation."""
    chunk_text: str
    questions: List[str]
    generation_time_sec: float


class HyDEGenerator:
    """
    Generate hypothetical questions for chunks using LLM.
    
    These questions are then embedded and used for matching against user queries.
    """
    
    def __init__(
        self,
        num_questions: int = 3,
        ollama_url: str = OLLAMA_BASE_URL,
        ollama_model: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT
    ):
        """
        Initialize HyDE generator.
        
        Args:
            num_questions: Number of questions to generate per chunk
            ollama_url: Ollama base URL
            ollama_model: Model to use (8b recommended for speed)
            timeout: Request timeout in seconds
        """
        self.num_questions = num_questions
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.timeout = timeout
        
        logger.info(
            f"[HyDE] Initialized (model={ollama_model}, "
            f"questions={num_questions})"
        )
    
    def generate_questions(self, chunk_text: str) -> List[str]:
        """
        Generate hypothetical questions for a chunk.
        
        Args:
            chunk_text: Chunk text to generate questions for
        
        Returns:
            List of generated questions (empty list if generation fails)
        """
        import time
        start_time = time.time()
        
        # Build prompt
        prompt = self._build_prompt(chunk_text)
        
        try:
            # Call Ollama
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 200  # Limit output length
                    }
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # Extract generated text
            result = response.json()
            generated_text = result.get("response", "")
            
            # Parse questions from generated text
            questions = self._parse_questions(generated_text)
            
            duration = time.time() - start_time
            
            if questions:
                logger.info(
                    f"[HyDE] Generated {len(questions)} questions "
                    f"in {duration:.2f}s"
                )
            else:
                logger.warning("[HyDE] No questions generated")
            
            return questions[:self.num_questions]
            
        except Exception as e:
            logger.error(f"[HyDE] Generation failed: {e}")
            return []
    
    def generate_batch(
        self,
        chunks: List[Dict],
        show_progress: bool = True
    ) -> Dict[str, List[str]]:
        """
        Generate questions for multiple chunks (batch processing).
        
        Args:
            chunks: List of chunk dicts with 'chunk_id' and 'text' keys
            show_progress: Show progress logging
        
        Returns:
            Dict mapping chunk_id to list of questions
        """
        results = {}
        
        for i, chunk in enumerate(chunks, 1):
            chunk_id = chunk.get("chunk_id", f"chunk_{i}")
            chunk_text = chunk.get("text", "")
            
            if show_progress and i % 10 == 0:
                logger.info(f"[HyDE] Processing chunk {i}/{len(chunks)}")
            
            questions = self.generate_questions(chunk_text)
            results[chunk_id] = questions
        
        logger.info(
            f"[HyDE] Batch complete: {len(results)} chunks, "
            f"{sum(len(q) for q in results.values())} total questions"
        )
        
        return results
    
    def _build_prompt(self, chunk_text: str) -> str:
        """Build prompt for question generation."""
        prompt = f"""Je bent een expert in het genereren van vragen. Gegeven een stuk tekst, genereer {self.num_questions} verschillende vragen die deze tekst zou kunnen beantwoorden.

Regels:
- Genereer ALLEEN de vragen, geen antwoorden
- Elke vraag op een nieuwe regel
- Gebruik verschillende vraagwoorden (wat, wie, waar, wanneer, waarom, hoe)
- Vragen moeten specifiek en relevant zijn

TEKST:
{chunk_text[:500]}

VRAGEN:"""
        
        return prompt
    
    def _parse_questions(self, generated_text: str) -> List[str]:
        """
        Parse questions from generated text.
        
        Expects questions on separate lines, possibly with numbering.
        """
        lines = generated_text.strip().split('\n')
        questions = []
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Remove numbering (1. 2. etc.)
            import re
            line = re.sub(r'^\d+[\.\)]\s*', '', line)
            line = re.sub(r'^[-•]\s*', '', line)
            
            # Must end with ? or be a reasonable question
            if line.endswith('?') or any(
                line.lower().startswith(q) 
                for q in ['wat', 'wie', 'waar', 'wanneer', 'waarom', 'hoe', 'welke']
            ):
                questions.append(line)
        
        return questions


# Fallback: Simple question templates
class SimpleQuestionGenerator:
    """
    Fallback question generator using templates (no LLM needed).
    
    Useful when LLM is unavailable or for very fast generation.
    """
    
    TEMPLATES = [
        "Wat wordt er in deze tekst behandeld?",
        "Welke informatie bevat deze passage?",
        "Waar gaat dit tekstgedeelte over?",
        "Wat is het hoofdonderwerp van deze tekst?",
        "Welke details worden hier beschreven?"
    ]
    
    @staticmethod
    def generate_questions(chunk_text: str, num: int = 3) -> List[str]:
        """Generate simple template-based questions."""
        # Extract key nouns from text (very simple approach)
        words = chunk_text.lower().split()
        
        # Use first few templates
        questions = SimpleQuestionGenerator.TEMPLATES[:num]
        
        return questions


# Module test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== HyDE Generator Test ===\n")
    
    # Test with simple generator first (no LLM)
    print("1. Simple Question Generator (Template-based):")
    simple_gen = SimpleQuestionGenerator()
    simple_questions = simple_gen.generate_questions(
        "De kosten voor dit project bedragen €50.000 inclusief BTW. "
        "De planning is 3 maanden met een team van 5 personen.",
        num=3
    )
    for i, q in enumerate(simple_questions, 1):
        print(f"   {i}. {q}")
    
    print("\n2. HyDE Generator (LLM-based):")
    
    # Test if Ollama is available
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        ollama_available = r.status_code == 200
    except:
        ollama_available = False
    
    if ollama_available:
        generator = HyDEGenerator(num_questions=3)
        
        # Sample chunk
        chunk = """
        Het taxatierapport van Camping de Brem dateert van december 2024. 
        De getaxeerde waarde bedraagt €12.500.000 voor het totale complex.
        Dit is gebaseerd op de huidige marktomstandigheden en vergelijkbare objecten.
        """
        
        questions = generator.generate_questions(chunk)
        
        print(f"\n   Generated {len(questions)} questions:")
        for i, q in enumerate(questions, 1):
            print(f"   {i}. {q}")
    else:
        print("   ⚠️  Ollama not available, skipping LLM test")
        print("   (HyDE will fall back to template-based questions)")
    
    print("\n=== Test Complete ===")
