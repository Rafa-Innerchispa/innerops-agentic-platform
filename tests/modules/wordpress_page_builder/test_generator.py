import unittest
from src.modules.wordpress_page_builder.generator import spec_json, GUTENBERG_BLOCKS, WP_REST_API_OPERATIONS, CREATE_DRAFT_MUTATION, ADAPTER_MCP, ELEMENTOR_IMPORT_EXPORT, WPBAKERY_COMPATIBILITY

class TestGenerator(unittest.TestCase):
    def test_spec_json(self):
        self.assertTrue(isinstance(spec_json, dict))

    def test_gutenberg_blocks(self):
        self.assertTrue(isinstance(GUTENBERG_BLOCKS, dict))

    def test_wp_rest_api_operations(self):
        self.assertTrue(isinstance(WP_REST_API_OPERATIONS, dict))

    def test_create_draft_mutation(self):
        self.assertTrue(isinstance(CREATE_DRAFT_MUTATION, dict))

    def test_adapter_mcp(self):
        self.assertTrue(isinstance(ADAPTER_MCP, dict))

    def test_elementor_import_export(self):
        self.assertTrue(isinstance(ELEMENTOR_IMPORT_EXPORT, dict))

    def test_wpbakery_compatibility(self):
        self.assertTrue(isinstance(WPBAKERY_COMPATIBILITY, dict))

if __name__ == '__main__':
    unittest.main()
