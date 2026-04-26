---
name: diagram-generator
description: "Generate Excalidraw diagrams (pipeline, mindmap, flowchart) from a JSON spec. Offline, no API. Use when: draw diagram, visualise architecture, mindmap, flowchart."
user-invocable: true
argument-hint: "<spec.json> [output.excalidraw]"
---

# Diagram Generator

Generates valid `.excalidraw` JSON files from a compact JSON spec. Works offline — no API calls.

## When to use

- The user asks to draw an architecture diagram, pipeline, mindmap, or flowchart.
- You want to share a visual artifact rather than text.

## Diagram types

| Type | Layout | Use case |
|---|---|---|
| `pipeline` | Vertical stages with blocks | Workflows, CI/CD, data pipelines |
| `mindmap` | Radial from center | Brainstorming, topic exploration |
| `flowchart` | Custom node positions | Architecture, decision trees |

## Spec format

```json
{
  "type": "pipeline",
  "title": "Build pipeline",
  "stages": [
    {
      "label": "lint",
      "color": "research",
      "blocks": [
        {"text": "ruff"},
        {"text": "black"},
        {"text": "mypy"}
      ]
    },
    {
      "label": "test",
      "color": "analysis",
      "blocks": [
        {"text": "pytest"},
        {"text": "bats"}
      ]
    },
    {
      "label": "deploy",
      "color": "final",
      "blocks": [
        {"text": "build"},
        {"text": "push"}
      ]
    }
  ]
}
```

Each block is an object `{"text": "...", "color": "..."}`. The `color` key is optional — defaults to the stage's color, or `default` if neither is set.

Colors: `research`, `analysis`, `review`, `final`, `factcheck`, `input`, `default`.

## Usage

```bash
python3 $CLAUDE_SKILL_DIR/scripts/excalidraw_gen.py spec.json out.excalidraw
```

The output `.excalidraw` file can be opened on https://excalidraw.com or imported into VS Code's Excalidraw extension.
