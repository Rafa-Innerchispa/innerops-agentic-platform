import unittest
from src.modules.wordpress_page_builder import WordPressPageBuilder

class TestWordPressPageBuilder(unittest.TestCase):
    def test_generate_page(self):
        builder = WordPressPageBuilder()
        result = builder.generate_page({})
        self.assertEqual(result, 'Página generada')

    def test_generate_blocks(self):
        builder = WordPressPageBuilder()
        result = builder.generate_blocks([{"type": "Hero"}])
        self.assertEqual(result, ['Bloque generado'])

    def test_validate_spec(self):
        builder = WordPressPageBuilder()
        result = builder.validate_spec({})
        self.assertTrue(result)

    def test_get_gutenberg_blocks(self):
        builder = WordPressPageBuilder()
        result = builder.get_gutenberg_blocks()
        self.assertEqual(result, ['Hero', 'Secciones', 'Testimonios', 'CTA', 'Galería', 'Carousel'])

    def test_get_elementor_blocks(self):
        builder = WordPressPageBuilder()
        result = builder.get_elementor_blocks()
        self.assertEqual(result, ['Hero', 'Secciones', 'Testimonios', 'CTA', 'Galería', 'Carousel'])

    def test_get_wpbakery_blocks(self):
        builder = WordPressPageBuilder()
        result = builder.get_wpbakery_blocks()
        self.assertEqual(result, ['Hero', 'Secciones', 'Testimonios', 'CTA', 'Galería', 'Carousel'])

if __name__ == '__main__':
    unittest.main()
