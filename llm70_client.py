"""
LLM70 Client - AI-4 Integration
Routes 70B LLM calls to AI-4's /llm70/* endpoints
"""

import logging
import time
from typing import Dict, List, Optional, Any

import requests

# Import config
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.ai3_settings import (
    AI4_LLM70_BASE_URL,
    AI4_LLM70_TIMEOUT,
    AI4_LLM70_ENABLED,
    AI4_FALLBACK_TO_HEURISTICS,
    get_ai4_llm70_endpoint,
)

logger = logging.getLogger(__name__)


class LLM70ClientError(Exception):
    """Base exception voor LLM70 client errors."""
    pass


class LLM70ConnectionError(LLM70ClientError):
    """AI-4 niet bereikbaar."""
    pass


class LLM70TimeoutError(LLM70ClientError):
    """AI-4 call timeout."""
    pass


class LLM70ResponseError(LLM70ClientError):
    """AI-4 responded met error."""
    pass


class LLM70Client:
    """
    Client voor AI-4 LLM70 endpoints.
    
    Handelt communicatie met AI-4 voor 70B LLM tasks.
    Biedt fallback naar heuristics als AI-4 niet bereikbaar.
    """
    
    def __init__(self):
        self.base_url = AI4_LLM70_BASE_URL
        self.timeout = AI4_LLM70_TIMEOUT
        self.enabled = AI4_LLM70_ENABLED
        self.fallback_enabled = AI4_FALLBACK_TO_HEURISTICS
        self._last_warmup_check = 0
        self._warmup_ok = False
        
        logger.info(f"LLM70Client initialized: base_url={self.base_url}, enabled={self.enabled}")
    
    def is_available(self) -> bool:
        """
        Check of AI-4 LLM70 service beschikbaar is.
        
        Returns:
            True als AI-4 bereikbaar, False anders
        """
        if not self.enabled:
            return False
        
        # Cache warmup check voor 60 seconden
        now = time.time()
        if now - self._last_warmup_check < 60 and self._warmup_ok:
            return True
        
        try:
            resp = requests.get(
                get_ai4_llm70_endpoint("/llm70/health"),
                timeout=5.0
            )
            self._warmup_ok = resp.status_code == 200
            self._last_warmup_check = now
            return self._warmup_ok
        except Exception as e:
            logger.warning(f"AI-4 health check failed: {e}")
            self._warmup_ok = False
            self._last_warmup_check = now
            return False
    
    def warmup(self) -> Dict[str, Any]:
        """
        Warmup AI-4 LLM70 model.
        
        Returns:
            Status dict met warmup info
            
        Raises:
            LLM70ConnectionError: Als AI-4 niet bereikbaar
            LLM70TimeoutError: Als warmup timeout
        """
        if not self.enabled:
            return {"status": "disabled", "message": "LLM70 routing is disabled"}
        
        url = get_ai4_llm70_endpoint("/llm70/warmup")
        
        try:
            logger.info(f"Warming up AI-4 LLM70 at {url}")
            resp = requests.post(url, json={}, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            
            self._warmup_ok = True
            self._last_warmup_check = time.time()
            
            logger.info(f"AI-4 LLM70 warmup successful: {data}")
            return data
            
        except requests.exceptions.Timeout as e:
            logger.error(f"AI-4 LLM70 warmup timeout: {e}")
            raise LLM70TimeoutError(f"Warmup timeout na {self.timeout}s") from e
        except requests.exceptions.ConnectionError as e:
            logger.error(f"AI-4 LLM70 connection error: {e}")
            raise LLM70ConnectionError(f"Kan AI-4 niet bereiken op {url}") from e
        except requests.exceptions.HTTPError as e:
            logger.error(f"AI-4 LLM70 HTTP error: {e}")
            raise LLM70ResponseError(f"AI-4 HTTP error: {e}") from e
        except Exception as e:
            logger.error(f"AI-4 LLM70 warmup error: {e}")
            raise LLM70ClientError(f"Unexpected error: {e}") from e
    
    def chat(
        self,
        question: str,
        context_chunks: Optional[List[str]] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        **kwargs
    ) -> str:
        """
        Send chat request naar AI-4 LLM70.
        
        Args:
            question: User vraag
            context_chunks: Optionele context chunks voor RAG
            system: Optioneel system prompt
            temperature: LLM temperature (0.0-1.0)
            max_tokens: Max response tokens
            **kwargs: Extra parameters voor AI-4
        
        Returns:
            LLM response text
            
        Raises:
            LLM70ConnectionError: Als AI-4 niet bereikbaar
            LLM70TimeoutError: Als call timeout
            LLM70ResponseError: Als AI-4 error retourneert
        """
        if not self.enabled:
            raise LLM70ClientError("LLM70 routing is disabled")
        
        url = get_ai4_llm70_endpoint("/llm70/chat")
        
        payload = {
            "question": question,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }
        
        if context_chunks:
            payload["context_chunks"] = context_chunks
        
        if system:
            payload["system"] = system
        
        try:
            logger.info(f"Sending chat request to AI-4: question_len={len(question)}, "
                       f"context_chunks={len(context_chunks) if context_chunks else 0}")
            
            start_time = time.time()
            resp = requests.post(url, json=payload, timeout=self.timeout)
            elapsed = time.time() - start_time
            
            resp.raise_for_status()
            data = resp.json()
            
            response_text = data.get("response", "")
            
            logger.info(f"AI-4 chat response received: elapsed={elapsed:.1f}s, "
                       f"response_len={len(response_text)}")
            
            return response_text
            
        except requests.exceptions.Timeout as e:
            logger.error(f"AI-4 LLM70 chat timeout: {e}")
            raise LLM70TimeoutError(f"Chat timeout na {self.timeout}s") from e
        except requests.exceptions.ConnectionError as e:
            logger.error(f"AI-4 LLM70 connection error: {e}")
            raise LLM70ConnectionError(f"Kan AI-4 niet bereiken op {url}") from e
        except requests.exceptions.HTTPError as e:
            logger.error(f"AI-4 LLM70 HTTP error: {e}")
            # Probeer error detail uit response te halen
            try:
                error_detail = e.response.json().get("detail", str(e))
            except:
                error_detail = str(e)
            raise LLM70ResponseError(f"AI-4 HTTP error: {error_detail}") from e
        except Exception as e:
            logger.error(f"AI-4 LLM70 chat error: {e}")
            raise LLM70ClientError(f"Unexpected error: {e}") from e
    
    def analyze_document(
        self,
        document: str,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Vraag AI-4 om document analyse met 70B model.
        
        Args:
            document: Document tekst (eerste 8000 chars worden gebruikt)
            filename: Optionele bestandsnaam
            mime_type: Optioneel MIME type
            system_prompt: Optioneel custom system prompt
        
        Returns:
            Dict met:
                - domain: domein (finance, sales, coaching, reviews, general)
                - format_hint: formaat (pdf, docx, txt, html)
                - entities: lijst van belangrijke entiteiten (max 5)
                - topics: lijst van onderwerpen (max 5)
                - extra: extra info dict
        
        Raises:
            LLM70ConnectionError: Als AI-4 niet bereikbaar
            LLM70TimeoutError: Als call timeout
            LLM70ResponseError: Als AI-4 error retourneert
        """
        if not self.enabled:
            raise LLM70ClientError("LLM70 routing is disabled")
        
        # Default system prompt voor document analyse
        if system_prompt is None:
            system_prompt = (
                "Je bent een document-analyzer. "
                "Geef een korte JSON met:\n"
                "- domain: kort domeinwoord (bv. finance, sales, coaching, reviews, general)\n"
                "- format_hint: bv. pdf, docx, txt, html\n"
                "- entities: lijst van max 5 belangrijke entiteiten (namen/organisaties)\n"
                "- topics: lijst van max 5 onderwerpen\n"
                "Gebruik Nederlands in waarden waar logisch, maar keys zelf Engelstalig laten."
            )
        
        # Bouw user prompt
        user_content = (
            f"Bestandsnaam: {filename or 'onbekend'}\n"
            f"MIME type: {mime_type or 'onbekend'}\n\n"
            f"CONTENT BEGIN:\n{document[:8000]}\nCONTENT EINDE\n\n"
            "Antwoord ALLEEN met JSON, geen uitleg."
        )
        
        try:
            # Chat call met structured output verwachting
            response_text = self.chat(
                question=user_content,
                system=system_prompt,
                temperature=0.1,
                max_tokens=512,
            )
            
            # Parse JSON uit response
            import json
            import re
            
            raw = response_text.strip()
            json_str = raw
            
            # Extract JSON als response niet met { begint
            if not raw.startswith("{"):
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    json_str = m.group(0)
            
            parsed = json.loads(json_str)
            
            # Normaliseer output
            result: Dict[str, Any] = {}
            
            result["domain"] = parsed.get("domain") or parsed.get("domein") or "general"
            result["format_hint"] = parsed.get("format_hint") or parsed.get("formaat") or "unknown"
            result["entities"] = parsed.get("entities") or parsed.get("entiteiten") or []
            result["topics"] = parsed.get("topics") or parsed.get("onderwerpen") or []
            
            result["extra"] = {
                "format": result["format_hint"],
                "llm_notes": "parsed_by_ai4_llama3_70b",
            }
            
            logger.info(f"AI-4 document analysis successful: domain={result['domain']}, "
                       f"entities={len(result['entities'])}, topics={len(result['topics'])}")
            
            return result
            
        except (LLM70ConnectionError, LLM70TimeoutError, LLM70ResponseError):
            # Re-raise deze specifieke errors
            raise
        except Exception as e:
            # JSON parse errors etc
            logger.error(f"AI-4 document analysis parsing error: {e}")
            return {
                "domain": "general",
                "format_hint": "unknown",
                "entities": [],
                "topics": [],
                "extra": {
                    "llm_error": str(e),
                    "llm_raw": response_text[:500] if 'response_text' in locals() else "no_response"
                }
            }


# ============================================
# Global Client Instance
# ============================================

_llm70_client: Optional[LLM70Client] = None


def get_llm70_client() -> LLM70Client:
    """
    Get or create global LLM70 client instance.
    
    Returns:
        Shared LLM70Client instance
    """
    global _llm70_client
    if _llm70_client is None:
        _llm70_client = LLM70Client()
    return _llm70_client
