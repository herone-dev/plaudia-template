# Chart generation — NOT in pipeline

## History

| Phase | Approach | Verdict |
|:------|:---------|:--------|
| V1 (July 14) | Chart.js CDN in template, DeepSeek generates `<canvas>` + `<script>` | ❌ Blocked by `dangerouslySetInnerHTML` (scripts don't execute) |
| V2 (July 15 AM) | matplotlib SVG via subprocess | ❌ 25K per chart, CRs bloated to 53K, DeepSeek can't edit |
| V3 (July 15 PM) | svgwrite SVG (1.5-2K per chart) | ✅ Compact, inline HTML, works without JS |

## Current state

The pipeline (`prompt_instructions` in `templates` table) no longer generates charts automatically. It only generates `chart-embed` markers if the transcription contains explicit numerical data. The rule is strict: "N'invente JAMAIS de données."

## Best practice

Charts are generated on-demand via the CR edit chat, not in the pipeline. The user provides data explicitly, or DeepSeek extracts from the transcript with the "n'invente jamais" rule.

## Related

See `plaudia-cr-backend` skill for the full chart rendering system (`chart_renderer.py`, `render_charts_in_cr()`, chart-embed format).