"""
BOM → Proposal Input cell mappings.
Edit this file to add/change mappings. No other file needs to change.

Each mapping is a dict with:
  source_sheet  – sheet name in the BOM Excel
  source_cell   – cell address in the BOM sheet
  target_sheet  – sheet name in the Proposal Input Excel
  target_cell   – cell address in the Proposal Input sheet
  label         – human-readable description (optional, for the summary log)
"""

OPEX_MAPPINGS = [
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "G18",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C5",
        "label": "Plant capacity",
    },
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "G6",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C24",
        "label": "Module wattage",
    },
    {
        "source_sheet": "Input's from BD(Sales)",
        "source_cell": "B13",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C29",
        "label": "Tariff / rate",
    },
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "B76",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C26",
        "label": "Inverter make",
    },
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "B77",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C27",
        "label": "Inverter model",
    },
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "B79",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C8",
        "label": "Structure type",
    },
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "B19",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C32",
        "label": "Module make/model",
    },
    {
        "source_sheet": "Bidcell BOM (LTS)",
        "source_cell": "H31",
        "target_sheet": "Proposal Inputs",
        "target_cell": "C81",
        "label": "DC cable length",
    },
]

# Placeholder — will be populated when CAPEX requirements are provided
CAPEX_MAPPINGS = []
