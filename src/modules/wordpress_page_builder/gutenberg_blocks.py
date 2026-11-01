from typing import Dict, List

GUTENBERG_BLOCKS = {
    'hero': {
        'title': 'Hero Block',
        'description': 'A block for hero sections.',
        'attributes': {
            'title': {'type': 'string'},
            'content': {'type': 'string'}
        }
    },
    'section': {
        'title': 'Section Block',
        'description': 'A block for generic sections.',
        'attributes': {
            'title': {'type': 'string'},
            'content': {'type': 'string'}
        }
    },
    'testimonial': {
        'title': 'Testimonial Block',
        'description': 'A block for testimonials.',
        'attributes': {
            'name': {'type': 'string'},
            'content': {'type': 'string'}
        }
    },
    'cta': {
        'title': 'CTA Block',
        'description': 'A block for call-to-action buttons.',
        'attributes': {
            'text': {'type': 'string'},
            'url': {'type': 'string'}
        }
    },
    'gallery': {
        'title': 'Gallery Block',
        'description': 'A block for image galleries.',
        'attributes': {
            'images': {'type': 'list', 'items': {'type': 'string'}}
        }
    },
    'carousel': {
        'title': 'Carousel Block',
        'description': 'A block for carousels.',
        'attributes': {
            'images': {'type': 'list', 'items': {'type': 'string'}}
        }
    }
}

def generate_spec_block(block_name: str) -> Dict[str, any]:
    return GUTENBERG_BLOCKS.get(block_name, {})
