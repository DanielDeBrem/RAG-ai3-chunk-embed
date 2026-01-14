"""
Menu & Dishes Chunking Strategy

Geoptimaliseerd voor menu/gerechten data.
Focus op aanbod, prijsniveau, complexiteit en inkoopkansen analyseren.

Kenmerken:
- 1 gerecht = 1 chunk (menu_item)
- NOOIT meerdere gerechten in 1 chunk
- Optionele enrichment (ingrediënten, allerge allergens, leverancierscategorieën)
- Section summaries (rollup per menusectie)

Chunk types:
- menu_item: Basis dish chunk (1 gerecht = 1 chunk)
- menu_item_enriched: Met LLM-gegenereerde culinaire labels
- menu_section_summary: Rollup per menusectie
"""
import re
from typing import List, Optional, Dict, Any
from ..base import ChunkStrategy, ChunkingConfig


class MenusStrategy(ChunkStrategy):
    """
    Chunking strategie voor menu/gerechten data.
    
    Ondersteunt:
    - Restaurant menus
    - Catering aanbod
    - Product catalogus (food & beverage)
    """
    
    name = "menus"
    description = "Optimized for menu/dish data: restaurants, catering (1 dish = 1 chunk)"
    default_config = {
        "chunk_type": "item",  # "item", "enriched", "summary"
        "preserve_metadata": True,
        "min_item_length": 5,  # Minimale naam lengte
        "detect_price": True,
        "detect_section": True
    }
    
    # Menu section keywords
    MENU_SECTIONS = {
        'starter': ['voorgerecht', 'starter', 'appetizer', 'vooraf', 'amuse'],
        'main': ['hoofdgerecht', 'main', 'entrée', 'hoofdgerechten'],
        'side': ['bijgerecht', 'side', 'garnering', 'bijgerechten'],
        'dessert': ['nagerecht', 'dessert', 'toetje', 'zoet'],
        'drinks': ['dranken', 'drinks', 'beverages', 'drankjes'],
        'wine': ['wijnen', 'wine', 'wijnkaart'],
        'beer': ['bier', 'beer', 'speciaalbier'],
        'breakfast': ['ontbijt', 'breakfast'],
        'lunch': ['lunch', 'lunchgerechten'],
        'dinner': ['diner', 'dinner', 'avondkaart'],
    }
    
    # Cuisine keywords
    CUISINE_KEYWORDS = {
        'westers': ['steak', 'schnitzel', 'burger', 'friet', 'pasta'],
        'italiaans': ['pizza', 'pasta', 'risotto', 'carpaccio'],
        'aziatisch': ['wok', 'noodles', 'sushi', 'curry', 'dim sum'],
        'frans': ['bouillabaisse', 'ratatouille', 'coq au vin'],
        'nederlands': ['stamppot', 'erwtensoep', 'hutspot', 'kroket'],
    }
    
    # Price level indicators (voor Nederlandse context)
    PRICE_LEVELS = [
        (0, 8, 'laag'),
        (8, 15, 'midden-laag'),
        (15, 25, 'midden'),
        (25, 35, 'midden-hoog'),
        (35, 999, 'hoog')
    ]
    
    # Complexity indicators
    COMPLEXITY_KEYWORDS = {
        'laag': ['gegrild', 'gebakken', 'gestoomd', 'gefrituurd'],
        'midden': ['geglaceerd', 'gepocheerd', 'gerookt', 'gemarineerd'],
        'hoog': ['sous-vide', 'getruffeerd', 'geflambeerd', 'deconstructie']
    }
    
    # Ingredient categories (voor supplier matching)
    INGREDIENT_CATEGORIES = {
        'vers vlees': ['rundvlees', 'varkensvlees', 'lamsvlees', 'kalfsvlees', 'steak'],
        'verse vis': ['zalm', 'tonijn', 'zeebaars', 'vis', 'schelpdieren'],
        'gevogelte': ['kip', 'eend', 'kalkoen', 'kipfilet'],
        'groenten': ['groenten', 'salade', 'tomaat', 'paprika'],
        'diepvries': ['friet', 'frieten', 'ijs'],
        'zuivel': ['kaas', 'roomsaus', 'crème'],
        'pasta/rijst': ['pasta', 'risotto', 'rijst', 'noodles'],
        'brood/bakkerij': ['brood', 'broodje', 'brioche'],
        'specerijen': ['kruiden', 'peper', 'zout', 'truffel'],
    }
    
    def detect_applicability(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Detecteer menu/gerechten data.
        
        Indicatoren:
        - Gerecht namen
        - Prijzen met valuta
        - Menu sectie headers
        - Ingrediënten beschrijvingen
        - Culinaire termen
        """
        sample = text[:1000]
        metadata = metadata or {}
        
        score = 0.3  # Base score
        
        # Check: prijzen met valuta
        price_patterns = [
            r'[€$£]\s*\d+[.,]\d{2}',  # € 12,50
            r'\d+[.,]\d{2}\s*(?:EUR|USD|euro)',  # 12,50 EUR
        ]
        price_count = sum(len(re.findall(p, sample)) for p in price_patterns)
        
        if price_count >= 3:
            score += 0.25
        elif price_count >= 1:
            score += 0.15
        
        # Check: menu sectie keywords
        section_count = sum(
            sum(1 for kw in keywords if kw in sample.lower())
            for keywords in self.MENU_SECTIONS.values()
        )
        
        if section_count >= 2:
            score += 0.20
        
        # Check: culinaire termen
        culinary_keywords = ['gerecht', 'ingredient', 'bereid', 'geserveerd', 'menu', 'kaart']
        culinary_count = sum(1 for kw in culinary_keywords if kw in sample.lower())
        
        if culinary_count >= 2:
            score += 0.15
        
        # Check: metadata hints
        if metadata.get("doc_type") in ["menu", "menu_item", "dish"]:
            score += 0.30
        
        if "price" in metadata or "dish_id" in metadata:
            score += 0.20
        
        # Check: filename hints
        fn = metadata.get("filename", "").lower()
        menu_hints = ["menu", "kaart", "gerecht", "dish", "food"]
        if any(hint in fn for hint in menu_hints):
            score += 0.15
        
        # Check: multiple items pattern (gerecht: ... prijs: ...)
        item_pattern = r'(?i)(?:gerecht|dish|item)\s*:.*?(?:prijs|price)\s*:'
        if len(re.findall(item_pattern, sample)) >= 2:
            score += 0.20
        
        return min(1.0, max(0.0, score))
    
    def chunk(self, text: str, config: ChunkingConfig) -> List[str]:
        """
        Chunk menus: 1 gerecht = 1 chunk.
        
        Strategie:
        1. Detecteer individuele gerechten
        2. Chunk per gerecht (NOOIT meerdere gerechten in 1 chunk)
        3. Optioneel: voeg enrichment toe (ingrediënten, allerge, leveranciers)
        4. Optioneel: maak section summaries
        """
        chunk_type = config.extra_params.get("chunk_type", "item")
        
        # Extraheer individuele menu items
        items = self._extract_menu_items(text)
        
        if not items:
            # Geen duidelijke structuur, probeer fallback
            return [text.strip()]
        
        chunks: List[str] = []
        
        for item in items:
            # Skip te kleine items
            min_length = config.extra_params.get("min_item_length", 5)
            if len(item.get('name', '')) < min_length:
                continue
            
            # Format chunk op basis van type
            if chunk_type == "enriched":
                chunk = self._format_enriched_item(item)
            elif chunk_type == "summary":
                # Summaries worden later per sectie gemaakt
                continue
            else:  # "item" (atomic)
                chunk = self._format_menu_item(item)
            
            chunks.append(chunk)
        
        # Maak section summaries indien gewenst
        if chunk_type == "summary":
            summaries = self._create_section_summaries(items)
            chunks.extend(summaries)
        
        return chunks if chunks else [text.strip()]
    
    def _extract_menu_items(self, text: str) -> List[Dict[str, Any]]:
        """
        Extraheer individuele menu items uit text.
        
        Returns:
            List van item dictionaries met name, section, description, price
        """
        items = []
        
        # Pattern 1: Structured format (Gerecht: ... Prijs: ...)
        pattern1 = r'(?i)(?:gerecht|dish|item)\s*:\s*([^\n]+)\s*\n.*?(?:prijs|price)\s*:\s*([€$£]?\s*[\d.,]+(?:\s*(?:EUR|USD|euro))?)'
        matches = re.finditer(pattern1, text, re.DOTALL)
        
        for match in matches:
            name = match.group(1).strip()
            price_str = match.group(2).strip()
            price = self._parse_price(price_str)
            
            # Extract description (tussen naam en prijs)
            full_match = match.group(0)
            desc_match = re.search(r'(?:omschrijving|description)\s*:\s*([^\n]+)', full_match, re.IGNORECASE)
            description = desc_match.group(1).strip() if desc_match else ""
            
            # Detect section
            section = self._detect_section(full_match)
            
            items.append({
                'name': name,
                'description': description,
                'price': price,
                'section': section,
                'raw_text': full_match
            })
        
        if items:
            return items
        
        # Pattern 2: Simple list format (Name ... Price)
        # Split op dubbele newlines
        blocks = text.split('\n\n')
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 1:
                continue
            
            # Skip sectie headers (=== Header ===)
            first_line = lines[0].strip()
            if re.match(r'^===.*===$', first_line) or re.match(r'^#{1,3}\s+', first_line):
                continue
            
            # Eerste regel = naam
            name = first_line
            
            # Zoek prijs (flexible regex voor Unicode € en verschillende formats)
            price = None
            description = ""
            
            for line in lines[1:]:
                # Meer flexible price regex
                price_match = re.search(r'[€$£\u20ac]?\s*(\d+[.,]\d{2})(?:\s*(?:EUR|USD|euro))?', line)
                if price_match:
                    price = float(price_match.group(1).replace(',', '.'))
                else:
                    description += line + " "
            
            # Accepteer items met naam EN prijs
            if name and price:
                items.append({
                    'name': name,
                    'description': description.strip(),
                    'price': price,
                    'section': self._detect_section(block),
                    'raw_text': block
                })
        
        return items
    
    def _parse_price(self, price_str: str) -> Optional[float]:
        """Parse price string to float."""
        # Extract nummer
        match = re.search(r'(\d+[.,]\d{2})', price_str)
        if match:
            return float(match.group(1).replace(',', '.'))
        return None
    
    def _detect_section(self, text: str) -> str:
        """Detecteer menu sectie."""
        text_lower = text.lower()
        
        for section, keywords in self.MENU_SECTIONS.items():
            if any(kw in text_lower for kw in keywords):
                return section
        
        return "other"
    
    def _format_menu_item(self, item: Dict[str, Any]) -> str:
        """Format basic menu item chunk."""
        parts = ["[MENU ITEM]", ""]
        
        parts.append(f"Gerecht: {item['name']}")
        
        if item.get('section'):
            section_nl = self._translate_section(item['section'])
            parts.append(f"Categorie: {section_nl}")
        
        if item.get('description'):
            parts.append(f"Omschrijving: {item['description']}")
        
        if item.get('price'):
            parts.append(f"Prijs: {item['price']:.2f} EUR")
        
        return "\n".join(parts)
    
    def _format_enriched_item(self, item: Dict[str, Any]) -> str:
        """Format enriched menu item with culinaire labels."""
        parts = ["[MENU ITEM ENRICHED]", ""]
        
        # Detecteer eigenschappen
        cuisine = self._detect_cuisine(item['name'] + " " + item.get('description', ''))
        price_level = self._get_price_level(item.get('price', 0))
        complexity = self._detect_complexity(item.get('description', ''))
        supplier_cats = self._detect_supplier_categories(
            item['name'] + " " + item.get('description', '')
        )
        
        section_nl = self._translate_section(item.get('section', 'other'))
        
        parts.append(f"{section_nl} met {cuisine} invloeden.")
        parts.append(f"Prijsniveau: {price_level}.")
        parts.append(f"Complexiteit: {complexity}.")
        
        if supplier_cats:
            parts.append(f"Geschikt voor leverancierscategorieën: {', '.join(supplier_cats)}.")
        
        parts.append("")
        parts.append(f'"{item["name"]}: {item.get("description", "")}"')
        
        return "\n".join(parts)
    
    def _translate_section(self, section: str) -> str:
        """Translate section to Dutch."""
        translations = {
            'starter': 'Voorgerecht',
            'main': 'Hoofdgerecht',
            'side': 'Bijgerecht',
            'dessert': 'Nagerecht',
            'drinks': 'Dranken',
            'wine': 'Wijnen',
            'beer': 'Bieren',
            'breakfast': 'Ontbijt',
            'lunch': 'Lunch',
            'dinner': 'Diner',
            'other': 'Overig'
        }
        return translations.get(section, section.capitalize())
    
    def _detect_cuisine(self, text: str) -> str:
        """Detecteer cuisine type."""
        text_lower = text.lower()
        
        for cuisine, keywords in self.CUISINE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return cuisine
        
        return "westers"
    
    def _get_price_level(self, price: float) -> str:
        """Bepaal prijsniveau."""
        for min_price, max_price, level in self.PRICE_LEVELS:
            if min_price <= price < max_price:
                return level
        return "onbekend"
    
    def _detect_complexity(self, text: str) -> str:
        """Detecteer bereidingscomplexiteit."""
        text_lower = text.lower()
        
        for complexity, keywords in self.COMPLEXITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return complexity
        
        return "midden"
    
    def _detect_supplier_categories(self, text: str) -> List[str]:
        """Detecteer relevante leverancierscategorieën."""
        text_lower = text.lower()
        categories = []
        
        for category, keywords in self.INGREDIENT_CATEGORIES.items():
            if any(kw in text_lower for kw in keywords):
                categories.append(category)
        
        return categories[:3]  # Max 3
    
    def _create_section_summaries(self, items: List[Dict[str, Any]]) -> List[str]:
        """Maak summaries per menu sectie."""
        # Groepeer per sectie
        sections = {}
        for item in items:
            section = item.get('section', 'other')
            if section not in sections:
                sections[section] = []
            sections[section].append(item)
        
        summaries = []
        
        for section, section_items in sections.items():
            if not section_items:
                continue
            
            # Bereken stats
            prices = [item['price'] for item in section_items if item.get('price')]
            item_count = len(section_items)
            min_price = min(prices) if prices else 0
            max_price = max(prices) if prices else 0
            
            # Detecteer focus (meest voorkomend ingredient type)
            all_text = " ".join(item.get('name', '') + " " + item.get('description', '') 
                               for item in section_items)
            focus = "divers aanbod"
            
            if "vlees" in all_text.lower() or "steak" in all_text.lower():
                focus = "vleesgerechten"
            elif "vis" in all_text.lower():
                focus = "visgerechten"
            elif "vegetar" in all_text.lower():
                focus = "vegetarische gerechten"
            
            # Format summary
            section_nl = self._translate_section(section)
            summary_parts = [
                "[MENU SECTION SUMMARY]",
                "",
                f"{section_nl} bevatten {item_count} items."
            ]
            
            if prices:
                summary_parts.append(f"Prijsrange: {min_price:.2f} – {max_price:.2f} EUR.")
            
            summary_parts.append(f"Focus op {focus}.")
            
            summaries.append("\n".join(summary_parts))
        
        return summaries
