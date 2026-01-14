"""
Strategy Registry

Centraal register voor alle chunking strategieën.
Biedt auto-detection en eenvoudige toegang tot strategieën.
"""
import logging
from typing import List, Dict, Any, Optional
from .base import ChunkStrategy, ChunkingConfig

logger = logging.getLogger(__name__)


class ChunkStrategyRegistry:
    """Centraal register voor alle chunking strategieën."""
    
    def __init__(self):
        self.strategies: Dict[str, ChunkStrategy] = {}
    
    def register(self, strategy: ChunkStrategy):
        """Registreer een nieuwe strategie."""
        self.strategies[strategy.name] = strategy
        logger.info(f"Registered chunking strategy: {strategy.name}")
    
    def get(self, name: str) -> Optional[ChunkStrategy]:
        """Haal strategie op bij naam."""
        return self.strategies.get(name)
    
    def list_available(self) -> List[Dict[str, Any]]:
        """Lijst alle beschikbare strategieën."""
        return [strategy.get_info() for strategy in self.strategies.values()]
    
    def auto_detect(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Detecteer beste strategie voor deze data.
        
        Returns:
            Naam van de strategie met hoogste confidence
        """
        if not text:
            return "default"
        
        # Gebruik eerste 2000 chars voor detectie (snelheid)
        sample = text[:2000]
        
        # Log detection start
        filename = metadata.get("filename", "unknown") if metadata else "unknown"
        logger.info(f"[STRATEGY DETECTION] Starting for: {filename}")
        logger.info(f"[STRATEGY DETECTION] Text length: {len(text)} chars, Sample: {len(sample)} chars")
        if metadata:
            logger.info(f"[STRATEGY DETECTION] Metadata: {metadata}")
        
        scores = {}
        for name, strategy in self.strategies.items():
            try:
                score = strategy.detect_applicability(sample, metadata)
                scores[name] = score
                logger.info(f"[STRATEGY DETECTION] '{name}' → score: {score:.3f}")
            except Exception as e:
                logger.warning(f"[STRATEGY DETECTION] Error detecting '{name}': {e}")
                scores[name] = 0.0
        
        if not scores:
            logger.warning("[STRATEGY DETECTION] No strategies registered, using 'default'")
            return "default"
        
        # Sort scores voor duidelijke output
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        logger.info(f"[STRATEGY DETECTION] All scores (sorted):")
        for name, score in sorted_scores[:5]:  # Top 5
            logger.info(f"  - {name}: {score:.3f}")
        
        best_strategy = max(scores, key=scores.get)
        best_score = scores[best_strategy]
        logger.info(f"[STRATEGY DETECTION] ✓ SELECTED: '{best_strategy}' (score: {best_score:.3f})")
        
        return best_strategy
    
    def chunk_text(
        self, 
        text: str, 
        strategy_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Chunk text met opgegeven of auto-detected strategie.
        
        Args:
            text: Te chunken tekst
            strategy_name: Strategie naam (None = auto-detect)
            config: Custom config (None = use defaults)
            metadata: Extra metadata voor auto-detection
            
        Returns:
            Lijst van chunks
        """
        # Auto-detect als geen strategie opgegeven
        if not strategy_name:
            strategy_name = self.auto_detect(text, metadata)
        
        # Haal strategie op
        strategy = self.get(strategy_name)
        if not strategy:
            logger.warning(f"Strategy '{strategy_name}' not found, using default")
            strategy = self.get("default")
            if not strategy:
                raise ValueError("No default strategy registered!")
        
        # Merge config met defaults
        final_config = {**strategy.default_config}
        if config:
            final_config.update(config)
        
        chunking_config = ChunkingConfig(
            max_chars=final_config.get("max_chars", 800),
            overlap=final_config.get("overlap", 0),
            extra_params=final_config
        )
        
        # Chunk!
        try:
            chunks = strategy.chunk(text, chunking_config)
            logger.info(f"Chunked with '{strategy_name}': {len(chunks)} chunks created")
            return chunks
        except Exception as e:
            logger.error(f"Chunking failed with '{strategy_name}': {e}")
            # Probeer fallback naar default
            default_strategy = self.get("default")
            if default_strategy and strategy_name != "default":
                logger.info("Falling back to default strategy")
                return default_strategy.chunk(text, chunking_config)
            raise


# Global registry instance
_registry = None


def get_registry() -> ChunkStrategyRegistry:
    """Get global registry instance (singleton)."""
    global _registry
    if _registry is None:
        _registry = ChunkStrategyRegistry()
    return _registry


# Convenience functions
def chunk_text(
    text: str,
    strategy: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Convenience function to chunk text."""
    return get_registry().chunk_text(text, strategy, config, metadata)


def list_strategies() -> List[Dict[str, Any]]:
    """List all available strategies."""
    return get_registry().list_available()


def detect_strategy(text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Auto-detect best strategy."""
    return get_registry().auto_detect(text, metadata)
