import json

# Define the spec JSON type and blocks Gutenberg for hero, sections, testimonials, CTA, gallery, carousel with fallback without plugin
spec_json = {
    "hero": {
        "type": "hero",
        "content": "Hero content here"
    },
    "section": {
        "type": "section",
        "content": "Section content here"
    },
    "testimonial": {
        "type": "testimonial",
        "content": "Testimonial content here"
    },
    "cta": {
        "type": "cta",
        "content": "CTA content here"
    },
    "gallery": {
        "type": "gallery",
        "content": "Gallery content here"
    },
    "carousel": {
        "type": "carousel",
        "content": "Carousel content here"
    }
}

# Define the Gutenberg blocks
GUTENBERG_BLOCKS = {
    "hero": "hero_block",
    "section": "section_block",
    "testimonial": "testimonial_block",
    "cta": "cta_block",
    "gallery": "gallery_block",
    "carousel": "carousel_block"
}

# Define the WordPress REST API operations for read-only + dry-run for draft, media and design
WP_REST_API_OPERATIONS = {
    "draft": "draft_operation",
    "media": "media_operation",
    "design": "design_operation"
}

# Define the flow of creation of draft/mutation prepared with authorization explicit and Application Password by site in vault
CREATE_DRAFT_MUTATION = {
    "authorization": "explicit",
    "application_password": "site_password"
}

# Define the adapter MCP to catalogo by capability_search/describe/invoke with policies read_only and writes gated
ADAPTER_MCP = {
    "capability_search": "search",
    "describe": "describe",
    "invoke": "invoke",
    "policies": {
        "read_only": "read_only",
        "writes_gated": "writes_gated"
    }
}

# Define the estrategia import/export JSON Elementor validated by fixtures, without writing _elementor_data directly
ELEMENTOR_IMPORT_EXPORT = {
    "import": "import_elementor",
    "export": "export_elementor",
    "fixtures": "elementor_fixtures"
}

# Define the compatibility read-only WPBakery
WPBAKERY_COMPATIBILITY = {
    "read_only": "read_only"
}
