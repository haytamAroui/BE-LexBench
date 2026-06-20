# Synthetic Sample Items

This directory holds **illustrative synthetic items** that demonstrate the be-lexbench item format. These items:

- Are **not part of the be-lexbench scoring set**
- Are not expert-reviewed and carry no legal or factual authority
- Do not represent real legal scenarios accurately
- Exist only to show what a valid item looks like before you write your own

Do not draw any conclusions about benchmark difficulty or model performance from these items.

---

## Validating items against the schema

Before running the harness on your own items, validate them against the schema:

```bash
pip install jsonschema
python -c "
import json, jsonschema, pathlib
schema = json.loads(pathlib.Path('schema/eval_item.schema.json').read_text())
items  = pathlib.Path('your_items.jsonl').read_text().splitlines()
for i, line in enumerate(items, 1):
    if line.strip():
        jsonschema.validate(json.loads(line), schema)
        print(f'  line {i}: ok')
print('All items valid.')
"
```

The schema is at [`schema/eval_item.schema.json`](../../schema/eval_item.schema.json). A full field-by-field description is in the schema's `"description"` properties and in [`docs/methodology.md`](../../docs/methodology.md).

## Adding items

Add 2–3 synthetic items per track as `.json` files or as a single `sample.jsonl`. Every item must conform to [`schema/eval_item.schema.json`](../../schema/eval_item.schema.json).

Mark every synthetic item with:
- `"source": "synthetic-illustrative"` in the `provenance` block
- `"canary": "SAMPLE-ITEM-NOT-IN-SCORING-SET"` so there is no ambiguity

---

## Minimal example (MCQ)

```json
{
  "id": "sample-mcq-corporate-wvv-001",
  "track": "corporate_law_wvv",
  "language": "nl",
  "parity_group": null,
  "difficulty": "core",
  "jurisdiction": "FED",
  "format": "mcq",
  "prompt": "Wat zijn de twee testen die een BV moet doorstaan voordat zij een uitkering aan haar aandeelhouders mag doen volgens het WVV? [SYNTHETISCH — GEEN SCORINGSITEM]",
  "system": null,
  "context": null,
  "tools": null,
  "choices": [
    "(A) De netto-actieftest en de liquiditeitstest",
    "(B) De solvabiliteitstest en de rentabiliteitstest",
    "(C) De balanstest en de winst-en-verliestest",
    "(D) De kapitaaltest en de reservetest"
  ],
  "scoring": {
    "method": "mcq_exact",
    "answer": "A",
    "rubric_id": null,
    "reference": null,
    "must_include": [],
    "must_not_include": [],
    "valid_citations": [],
    "expected_refusal": null,
    "expected_tool": null,
    "expected_args": null
  },
  "provenance": {
    "author": "synthetic",
    "validated_by": null,
    "review_date": null,
    "source": "synthetic-illustrative",
    "canary": "SAMPLE-ITEM-NOT-IN-SCORING-SET"
  }
}
```

## Minimal example (open / rubric)

```json
{
  "id": "sample-open-civil-book6-001",
  "track": "belgian_civil_law",
  "language": "fr",
  "parity_group": null,
  "difficulty": "applied",
  "jurisdiction": "FED",
  "format": "open",
  "prompt": "Expliquez les trois éléments de la responsabilité extracontractuelle en droit belge depuis l'entrée en vigueur du Livre 6 du Code civil le 1er janvier 2025. Précisez ce qui a changé par rapport aux anciens articles 1382 et suivants. [SYNTHÉTIQUE — PAS UN ITEM DE NOTATION]",
  "system": null,
  "context": null,
  "tools": null,
  "choices": null,
  "scoring": {
    "method": "rubric",
    "answer": null,
    "rubric_id": "be-civil-law-v1",
    "reference": "Art. 6.5 BW: la faute (standard objectif de la personne normalement prudente), le dommage (réel, certain, personnel), le lien causal (conditio sine qua non avec correction pour causes concurrentes). Changements clés: abolition de la quasi-immunité des agents d'exécution; possibilité de concours entre responsabilité contractuelle et extracontractuelle.",
    "must_include": [],
    "must_not_include": [],
    "valid_citations": ["art. 6.5 BW"],
    "expected_refusal": null,
    "expected_tool": null,
    "expected_args": null
  },
  "provenance": {
    "author": "synthetic",
    "validated_by": null,
    "review_date": null,
    "source": "synthetic-illustrative",
    "canary": "SAMPLE-ITEM-NOT-IN-SCORING-SET"
  }
}
```
