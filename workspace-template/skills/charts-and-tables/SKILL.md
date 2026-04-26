---
name: charts-and-tables
description: "Create interactive charts, tables, and maps via Datawrapper API. Use when: build a chart, visualise data, create a table, plot trends."
user-invocable: true
argument-hint: "<title> <chart-type> <csv-data-or-file>"
---

# Charts and Tables

Create publishable charts/tables/maps using the Datawrapper API.

## When to use

- The user asks for a chart, graph, table, or map.
- You have tabular data and need to share it visually.

## Setup

```bash
mkdir -p ~/.claude-lab/shared/secrets
echo 'YOUR_DATAWRAPPER_TOKEN' > ~/.claude-lab/shared/secrets/datawrapper.key
chmod 600 ~/.claude-lab/shared/secrets/datawrapper.key
```

Free tier at https://datawrapper.de.

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/create.sh "Sales 2026" d3-bars data.csv
```

Output: a published URL like `https://datawrapper.dwcdn.net/abcde/1/`.

## Common chart types

- `d3-bars` — horizontal bars
- `column-chart` — vertical columns
- `d3-lines` — line chart
- `d3-pies` — pie / donut
- `tables` — sortable table
- `locator-maps` — single-point map
