"""Layout catalog for Studio decks (16:9 slides)."""

from __future__ import annotations

DECK_LAYOUTS = {
    "title": {
        "label": "Title",
        "fields": ["title", "subtitle", "footer", "image_prompt"],
        "limits": {"title": 56, "subtitle": 120, "footer": 60},
    },
    "section": {
        "label": "Section divider",
        "fields": ["eyebrow", "title", "subtitle", "image_prompt"],
        "limits": {"eyebrow": 32, "title": 64, "subtitle": 100},
    },
    "bullets_focus": {
        "label": "Focused bullets",
        "fields": ["title", "bullets", "image_prompt"],
        "limits": {"title": 64, "bullet": 90, "max_bullets": 5},
    },
    "two_column": {
        "label": "Two columns",
        "fields": ["title", "left_title", "left_body", "right_title", "right_body"],
        "limits": {"title": 64, "left_title": 40, "left_body": 220, "right_title": 40, "right_body": 220},
    },
    "big_number": {
        "label": "Big number",
        "fields": ["title", "value", "caption", "note", "image_prompt"],
        "limits": {"title": 48, "value": 24, "caption": 80, "note": 100},
    },
    "quote": {
        "label": "Quote",
        "fields": ["quote", "attribution", "image_prompt"],
        "limits": {"quote": 180, "attribution": 60},
    },
    "comparison": {
        "label": "Comparison",
        "fields": ["title", "left_label", "left_items", "right_label", "right_items"],
        "limits": {"title": 56, "left_label": 28, "right_label": 28, "item": 70, "max_items": 4},
    },
    "chart_panel": {
        "label": "Chart panel",
        "fields": ["title", "caption", "chart"],
        "limits": {"title": 56, "caption": 100},
    },
    "closing": {
        "label": "Closing / ask",
        "fields": ["title", "subtitle", "cta", "image_prompt"],
        "limits": {"title": 56, "subtitle": 120, "cta": 60},
    },
    "statement": {
        "label": "Single powerful statement",
        "fields": ["title", "subtitle"],
        "limits": {"title": 90, "subtitle": 100},
    },
    "stack": {
        "label": "Vertical stack of names",
        "fields": ["title", "items"],
        "limits": {"title": 48, "item": 36, "max_items": 6},
    },
    "visual": {
        "label": "Full-bleed AI visual",
        "fields": ["title", "subtitle", "image_prompt", "anchor"],
        "limits": {"title": 72, "subtitle": 110},
    },
    "split_visual": {
        "label": "Text + AI image",
        "fields": ["title", "body", "bullets", "image_prompt", "image_side"],
        "limits": {"title": 56, "body": 180, "bullet": 70, "max_bullets": 4},
    },
    "poster": {
        "label": "Art-directed poster",
        "fields": ["title", "subtitle", "image_prompt", "anchor"],
        "limits": {"title": 80, "subtitle": 120},
    },
    "mosaic": {
        "label": "Asymmetric image mosaic",
        "fields": ["title", "subtitle", "tiles"],
        "limits": {"title": 56, "subtitle": 100, "caption": 48, "max_tiles": 3},
    },
    "metric_row": {
        "label": "Three invented metrics",
        "fields": ["title", "kpis"],
        "limits": {"title": 48, "kpi_value": 18, "kpi_label": 40, "max_kpis": 4},
    },
    "composed": {
        "label": "Invented freeform composition",
        "fields": ["elements", "image_prompt"],
        "limits": {"max_elements": 18, "text": 220, "bullet": 80, "max_bullets": 5},
    },
}

DECK_LAYOUT_IDS = frozenset(DECK_LAYOUTS)
