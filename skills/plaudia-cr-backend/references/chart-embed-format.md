# Chart Embed Format — SVG inline charts

## Quick reference

DeepSeek puts this in the `<article>` HTML:
```html
<script type="application/json" class="chart-embed">
{"type":"bar","title":"Paliers","labels":["Free","Intermédiaire","Premium"],"datasets":[{"data":[0,55,99]}],"unit":"€/mois"}
</script>
```

Backend replaces with SVG via `chart_renderer.py` + svgwrite.

## Supported types

| type | Visual | Notes |
|------|--------|-------|
| `bar` | Vertical bars | Add `"indexAxis":"y"` for horizontal bars |
| `doughnut` | Donut chart | Uses path arcs, percentage labels, automatic legend |
| `line` | Line chart | With circle markers at data points, grid lines |

## Full options

```json
{
  "type": "bar",
  "title": "Chart title",
  "labels": ["A", "B", "C"],
  "datasets": [{"data": [10, 20, 30]}],
  "unit": "€/mois",
  "colors": ["#1e3a5f", "#3b82f6", "#93c5fd"],
  "indexAxis": "y"
}
```

## Flow

```
DeepSeek outputs marker in HTML
  → render_charts_in_cr() regex-detects the marker
  → subprocess call to chart_renderer.py with the JSON
  → svgwrite renders compact SVG (1.5-2K)
  → marker replaced with <svg class="cr-chart-svg">...</svg>
  → stored in crs.content as inline SVG
```

## CR size constraint — CRITICAL

DeepSeek cannot edit CRs larger than ~25K chars. CR size must stay under this limit.

**Why:** When the CR is sent to DeepSeek for editing, the full article content (~20K) + system prompt + transcript pushes the context window over the limit. DeepSeek responds with a short error message instead of HTML.

**Causes of bloat:**
- matplotlib SVG: 9-25K PER CHART (never use matplotlib)
- svgwrite SVG: 1.5-2K per chart ✅ (safe)
- Multiple charts: 3 charts × 2K = 6K added — still safe

**Check CR size after any modification** — especially when adding charts.

## Chart quality checklist — CRITICAL

After generating a chart, verify ALL of these:

- [ ] **Y-axis with gridlines** — scale values from 0 to max_val*1.15 with 4-5 gridlines. Without a scale the chart is meaningless.
- [ ] **X-axis labels** — category names below each bar/data point
- [ ] **Value labels** — numeric value on top of each bar, font-weight bold
- [ ] **Minimum bar height** — 4px minimum ensures tiny values (e.g. 1) are visible next to large values (e.g. 27). Use `max(frac * plot_h, 4)`.
- [ ] **Title** — #1e3a5f, bold, 11pt, left-aligned
- [ ] **Unit** — gray (#6b7280), 7.5pt, at top of y-axis
- [ ] **Doughnut legend** — labels + percentages below the chart, each with a color swatch
- [ ] **Doughnut percentages** — on each slice, white text, 9pt bold, only if slice > 12°
- [ ] **Line chart markers** — 3.5px circles, white fill, color stroke, 1.5px width
- [ ] **No leftover chart-embed markers** — check `content LIKE '%chart-embed%'` returns false
- [ ] **Tables preserved** — check `content LIKE '%cr-table%'` returns true
- [ ] **Size < 25K chars** — check `length(content) < 25000`

### Common bugs

| Bug | Cause | Fix |
|-----|-------|-----|
| Invisible small bar | No min height | `max(frac * plot_h, 4)` |
| Missing y-axis | No gridlines drawn | `n_lines = min(5, max(2, int(y_max / 5)))` |
| Double SVG in output | Two `print(svg)` calls in `__main__` | Only print after cleanup |
| Leftover `<defs />` | Empty defs tag | `re.sub(r'<defs\s*/>', '', svg)` |
| CR size 40K+ | Old matplotlib SVGs | Restore from cr_versions pre-SVG |
| "Aucune modification appliquée" | Stale frontend cache OR CR too large | Check debug log, refresh frontend, or restore CR |

## Auto-extraction flow

When DeepSeek is asked to "crée-moi un graphique" without explicit data:

1. DeepSeek MUST look at the transcription (appended to the enriched question, up to 80K chars)
2. Find numerical data: budget, counts, percentages, durations, comparisons
3. If found: create a chart-embed marker
4. If NOT found: respond "Je n'ai pas trouvé de données chiffrées..."
5. NEVER invent data

The edit prompt's `RÈGLE GRAPHIQUES` section contains the instructions for this.

## Pitfalls

- **svgwrite, never matplotlib**: matplotlib SVGs are 9-25K (too large, breaks subsequent edits). svgwrite produces 1.5-2K.
- **DeepSeek invents data**: if asked to "add a chart" without explicit data, it makes up numbers. Always require explicit data or strict extraction from transcript.
- **No re-rendering needed**: the SVG is stored inline in crs.content. GET /v1/crs/{id} returns it as-is.
- **No JS needed**: SVG is inline HTML, works with dangerouslySetInnerHTML, no iframe required.
- **The charts-row wrapper**: For multiple charts, wrap each in `<div class="charts-row">` for flexbox side-by-side display (CSS in template).
- **chart.js CDN was removed**: `get_template_shell()` no longer includes `<script src="cdn.jsdelivr.net/npm/chart.js">` — SVG is self-contained, no JS.