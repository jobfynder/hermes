ATS_RULES: dict[str, dict] = {
    "greenhouse": {
        "display_name": "Greenhouse",
        "parser_tolerance": "high",
        "preferred_format": "PDF",
        "avoid": [],
        "notes": [
            "Modern parser with good tolerance for standard resume layouts.",
            "Still prefers standard section headers (Experience, Education, Skills).",
        ],
    },
    "workday": {
        "display_name": "Workday",
        "parser_tolerance": "low",
        "preferred_format": "DOCX",
        "avoid": [
            "tables",
            "multi_column_layouts",
            "headers_and_footers",
            "text_boxes",
            "graphics_or_icons",
        ],
        "notes": [
            "Workday's parser frequently fails on tables and multi-column layouts - use a single-column, "
            "linear layout.",
            "Do not put contact info in a header/footer - Workday often skips those regions entirely.",
        ],
    },
    "oracle_taleo": {
        "display_name": "Oracle Taleo",
        "parser_tolerance": "low",
        "preferred_format": "DOCX",
        "avoid": [
            "tables",
            "multi_column_layouts",
            "headers_and_footers",
            "text_boxes",
            "special_characters_in_headers",
            "non_standard_fonts",
        ],
        "notes": [
            "One of the weakest ATS parsers - use plain, linear formatting with standard fonts only.",
            "Use exact standard section header names: 'Work Experience', 'Education', 'Skills'.",
        ],
    },
    "kenexa_brassring": {
        "display_name": "Kenexa BrassRing (IBM)",
        "parser_tolerance": "low",
        "preferred_format": "DOCX",
        "avoid": [
            "tables",
            "multi_column_layouts",
            "special_characters_in_headers",
            "graphics_or_icons",
        ],
        "notes": [
            "Common in banking/defense/insurance - keep formatting conservative and text-only.",
        ],
    },
    "icims": {
        "display_name": "iCIMS",
        "parser_tolerance": "medium",
        "preferred_format": "PDF",
        "avoid": [
            "graphics_or_icons",
            "unusual_date_formats",
        ],
        "notes": [
            "Generally reliable with standard formats. Use consistent date formats (MM/YYYY).",
        ],
    },
    "lever": {
        "display_name": "Lever",
        "parser_tolerance": "high",
        "preferred_format": "PDF",
        "avoid": [],
        "notes": [
            "Modern parser, good tolerance for standard resume layouts.",
        ],
    },
}

DEFAULT_ATS_GUIDANCE = {
    "display_name": "Generic ATS",
    "parser_tolerance": "unknown",
    "preferred_format": "PDF",
    "avoid": [
        "tables",
        "multi_column_layouts",
        "headers_and_footers",
        "graphics_or_icons",
    ],
    "notes": [
        "No specific ATS selected - following conservative formatting guidance that works across most parsers.",
    ],
}


def get_ats_formatting_guidance(target_ats: str | None) -> dict:
    if not target_ats:
        return dict(DEFAULT_ATS_GUIDANCE)

    key = target_ats.strip().lower().replace(" ", "_").replace("(ibm)", "").strip("_")
    guidance = ATS_RULES.get(key)

    if guidance is None:
        return dict(DEFAULT_ATS_GUIDANCE)

    return dict(guidance)
