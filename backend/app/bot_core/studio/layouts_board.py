"""Layout catalog for Studio infographic boards."""

from __future__ import annotations

BOARD_LAYOUTS = {
    "timeline": {
        "label": "Timeline",
        "fields": ["headline", "subhead", "steps", "footnote", "image_prompt"],
        "limits": {"headline": 56, "subhead": 100, "step_title": 28, "step_body": 80, "max_steps": 6, "footnote": 90},
    },
    "process": {
        "label": "Process 3-5",
        "fields": ["headline", "subhead", "steps", "footnote", "image_prompt"],
        "limits": {"headline": 56, "subhead": 100, "step_title": 28, "step_body": 90, "max_steps": 5, "footnote": 90},
    },
    "funnel": {
        "label": "Funnel",
        "fields": ["headline", "subhead", "steps", "footnote", "image_prompt"],
        "limits": {"headline": 56, "subhead": 100, "step_title": 32, "step_body": 70, "max_steps": 5, "footnote": 90},
    },
    "kpi_strip": {
        "label": "KPI strip",
        "fields": ["headline", "subhead", "kpis", "footnote", "image_prompt"],
        "limits": {"headline": 56, "subhead": 100, "kpi_value": 18, "kpi_label": 36, "max_kpis": 4, "footnote": 90},
    },
    "compare_cards": {
        "label": "Compare cards",
        "fields": ["headline", "subhead", "cards", "footnote", "image_prompt"],
        "limits": {"headline": 56, "subhead": 100, "card_title": 28, "card_body": 110, "max_cards": 3, "footnote": 90},
    },
    "hierarchy": {
        "label": "Hierarchy",
        "fields": ["headline", "subhead", "levels", "footnote", "image_prompt"],
        "limits": {"headline": 56, "subhead": 100, "level_title": 32, "level_body": 90, "max_levels": 4, "footnote": 90},
    },
    "composed": {
        "label": "AI-composed freeform board",
        "fields": ["elements", "headline", "image_prompt"],
        "limits": {"headline": 56, "max_elements": 16, "text": 160, "bullet": 70, "max_bullets": 5, "footnote": 90},
    },
}

BOARD_LAYOUT_IDS = frozenset(BOARD_LAYOUTS)
BOARD_ORIENTATIONS = frozenset({"landscape", "portrait"})
