from typing import Dict, List

class WordPressPageBuilder:
    def generate_page(self, spec: Dict) -> str:
        # Implementación básica de generación de página
        return 'Página generada'

    def generate_blocks(self, blocks: List[Dict]) -> List[str]:
        # Implementación básica de generación de bloques
        return ['Bloque generado']

    def validate_spec(self, spec: Dict) -> bool:
        # Implementación básica de validación de spec
        return True

    def get_gutenberg_blocks(self) -> List[str]:
        # Implementación básica de obtención de bloques Gutenberg
        return ['Hero', 'Secciones', 'Testimonios', 'CTA', 'Galería', 'Carousel']

    def get_elementor_blocks(self) -> List[str]:
        # Implementación básica de obtención de bloques Elementor
        return ['Hero', 'Secciones', 'Testimonios', 'CTA', 'Galería', 'Carousel']

    def get_wpbakery_blocks(self) -> List[str]:
        # Implementación básica de obtención de bloques WPBakery
        return ['Hero', 'Secciones', 'Testimonios', 'CTA', 'Galería', 'Carousel']
