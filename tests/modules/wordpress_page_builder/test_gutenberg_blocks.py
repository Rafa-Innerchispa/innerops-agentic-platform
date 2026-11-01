import unittest
from src.modules.wordpress_page_builder.gutenberg_blocks import GUTENBERG_BLOCKS, generate_spec_block

class TestGutenbergBlocks(unittest.TestCase):
    def test_block_definitions(self):
        self.assertIn('hero', GUTENBERG_BLOCKS)
        self.assertIn('section', GUTENBERG_BLOCKS)
        self.assertIn('testimonial', GUTENBERG_BLOCKS)
        self.assertIn('cta', GUTENBERG_BLOCKS)
        self.assertIn('gallery', GUTENBERG_BLOCKS)
        self.assertIn('carousel', GUTENBERG_BLOCKS)

    def test_generate_spec_block(self):
        hero_block = generate_spec_block('hero')
        self.assertEqual(hero_block['title'], 'Hero Block')
        self.assertIn('attributes', hero_block)

if __name__ == '__main__':
    unittest.main()
