#!/opt/data/dwg-env/bin/python3
"""Chart renderer — SVG via svgwrite (ultra-compact, < 3KB per chart)."""
import json, sys, io, math, re
import svgwrite

HERONE = {'primary': '#1e3a5f', 'blue': '#3b82f6', 'light': '#93c5fd',
          'orange': '#d97706', 'text': '#374151', 'gray': '#6b7280', 'line': '#e5e7eb'}
COLORS = ['#1e3a5f','#3b82f6','#93c5fd','#bfdbfe','#dbeafe','#1e40af']
W, H, M = 340, 200, 12  # width, height, margin


def _make_svg(width, height):
    dwg = svgwrite.Drawing(size=(width, height))
    dwg.attribs['class'] = 'cr-chart-svg'
    dwg.attribs['style'] = 'max-width:100%;height:auto;'
    return dwg


def _gridlines(dwg, top, bottom, n_lines=4):
    for i in range(n_lines + 1):
        y = top + (bottom - top) * (1 - i / n_lines)
        dwg.add(dwg.line((M + 35, y), (W - M, y), stroke=HERONE['line'], stroke_width=0.5))


def render_bar(data):
    dwg = _make_svg(W + 20, H + 20)
    labels = data.get('labels', [])
    values = data['datasets'][0]['data']
    colors = data.get('colors', COLORS)
    title = data.get('title', '')

    if not labels or not values:
        dwg.add(dwg.text("Aucune donnée", insert=(W//2, H//2), fill=HERONE['gray'], font_size=12, text_anchor='middle'))
        return dwg.tostring()

    # Layout
    left_margin = 42  # space for y-axis labels
    right_margin = 10
    top_margin = 24 if title else 12
    bottom_margin = 28
    plot_w = W - left_margin - right_margin
    plot_h = H - top_margin - bottom_margin
    n = len(labels)

    # Max value, ensure minimum
    max_val = max(values) if values else 1
    y_max = max_val * 1.15  # 15% headroom

    # Y-axis gridlines
    n_lines = min(5, max(2, int(y_max / 5)))
    for i in range(n_lines + 1):
        frac = i / n_lines
        y = top_margin + plot_h * (1 - frac)
        val = round(y_max * frac)
        dwg.add(dwg.line((left_margin, y), (left_margin + plot_w, y), stroke=HERONE['line'], stroke_width=0.5))
        dwg.add(dwg.text(str(val), insert=(left_margin - 4, y + 3), fill=HERONE['gray'], font_size=8, text_anchor='end'))

    # Y-axis line
    dwg.add(dwg.line((left_margin, top_margin), (left_margin, top_margin + plot_h), stroke=HERONE['line'], stroke_width=0.5))

    # Title
    if title:
        dwg.add(dwg.text(title, insert=(left_margin, 12), fill=HERONE['primary'], font_size=11, font_weight='bold'))

    # Bars
    bar_area_w = plot_w / n
    bar_w = min(bar_area_w * 0.55, 50)
    min_bar_h = 4  # minimum bar height for visibility

    for i, (label, val) in enumerate(zip(labels, values)):
        frac = val / y_max
        bar_h = max(frac * plot_h, min_bar_h if val > 0 else 0)
        bx = left_margin + i * bar_area_w + (bar_area_w - bar_w) / 2
        by = top_margin + plot_h - bar_h

        # Bar
        dwg.add(dwg.rect((bx, by), (bar_w, bar_h), fill=colors[i % len(colors)], rx=2, ry=2))

        # Value label on top
        dwg.add(dwg.text(str(val), insert=(bx + bar_w/2, by - 4), fill=HERONE['text'],
                         font_size=9, font_weight='bold', text_anchor='middle'))

        # Label below
        dwg.add(dwg.text(label, insert=(bx + bar_w/2, top_margin + plot_h + 14),
                         fill=HERONE['text'], font_size=8, text_anchor='middle'))

    # Unit
    unit = data.get('unit', '')
    if unit:
        dwg.add(dwg.text(unit, insert=(left_margin - 4, top_margin + 10), fill=HERONE['gray'], font_size=7.5, text_anchor='end'))

    return dwg.tostring()


def render_doughnut(data):
    dwg = _make_svg(280, 240)
    labels = data.get('labels', [])
    values = data['datasets'][0]['data']
    colors = data.get('colors', COLORS)
    title = data.get('title', '')

    if not labels or not values:
        dwg.add(dwg.text("Aucune donnée", insert=(140, 120), fill=HERONE['gray'], font_size=12, text_anchor='middle'))
        return dwg.tostring()

    total = sum(values)
    if total == 0:
        return dwg.tostring()

    cx, cy, r = 140, 135, 75
    start_angle = -90
    color_idx = 0

    for label, val in zip(labels, values):
        if val == 0:
            continue
        angle = (val / total) * 360
        end_angle = start_angle + angle
        sr = math.radians(start_angle)
        er = math.radians(end_angle)

        x1 = cx + r * math.cos(sr)
        y1 = cy + r * math.sin(sr)
        x2 = cx + r * math.cos(er)
        y2 = cy + r * math.sin(er)

        large = 1 if angle > 180 else 0
        ri = r * 0.55
        xi1 = cx + ri * math.cos(sr)
        yi1 = cy + ri * math.sin(sr)
        xi2 = cx + ri * math.cos(er)
        yi2 = cy + ri * math.sin(er)

        path_data = f"M {x1:.1f} {y1:.1f} A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} L {xi2:.1f} {yi2:.1f} A {ri:.1f} {ri:.1f} 0 {large} 0 {xi1:.1f} {yi1:.1f} Z"
        dwg.add(dwg.path(d=path_data, fill=colors[color_idx % len(colors)], stroke='white', stroke_width=1))

        # Percentage label (only if enough space)
        if angle > 12:
            mid = math.radians(start_angle + angle / 2)
            lr = r * 0.74
            lx = cx + lr * math.cos(mid)
            ly = cy + lr * math.sin(mid)
            dwg.add(dwg.text(f"{int(round(val/total*100))}%", insert=(lx, ly),
                             fill='white', font_size=9, font_weight='bold',
                             text_anchor='middle', dominant_baseline='central'))
        start_angle = end_angle
        color_idx += 1

    # Legend
    if labels:
        lx = 140 - min(len(labels), 4) * 65
        ly = 220
        for i, (label, val) in enumerate(zip(labels, values)):
            lx_i = lx + (i % 4) * 65
            dwg.add(dwg.rect((lx_i, ly - 4), (8, 8), fill=colors[i % len(colors)], rx=1))
            dwg.add(dwg.text(f"{label} ({int(round(val/total*100))}%)", insert=(lx_i + 11, ly + 4),
                             fill=HERONE['text'], font_size=7.5))

    if title:
        dwg.add(dwg.text(title, insert=(10, 12), fill=HERONE['primary'], font_size=12, font_weight='bold'))

    return dwg.tostring()


def render_line(data):
    dwg = _make_svg(W + 20, H + 20)
    labels = data.get('labels', [])
    datasets = data.get('datasets', [])
    title = data.get('title', '')

    if not labels or not datasets:
        dwg.add(dwg.text("Aucune donnée", insert=(W//2, H//2), fill=HERONE['gray'], font_size=12, text_anchor='middle'))
        return dwg.tostring()

    left_margin = 42
    top_margin = 24 if title else 12
    bottom_margin = 28
    plot_w = W - left_margin - 10
    plot_h = H - top_margin - bottom_margin

    all_vals = [v for ds in datasets for v in ds['data']]
    max_val = max(all_vals) if all_vals else 1
    y_max = max_val * 1.15

    # Grid + Y-axis
    n_lines = min(5, max(2, int(y_max / 5)))
    for i in range(n_lines + 1):
        frac = i / n_lines
        y = top_margin + plot_h * (1 - frac)
        val = round(y_max * frac)
        dwg.add(dwg.line((left_margin, y), (left_margin + plot_w, y), stroke=HERONE['line'], stroke_width=0.5))
        dwg.add(dwg.text(str(val), insert=(left_margin - 4, y + 3), fill=HERONE['gray'], font_size=8, text_anchor='end'))
    dwg.add(dwg.line((left_margin, top_margin), (left_margin, top_margin + plot_h), stroke=HERONE['line'], stroke_width=0.5))

    if title:
        dwg.add(dwg.text(title, insert=(left_margin, 12), fill=HERONE['primary'], font_size=11, font_weight='bold'))

    n = len(labels)
    for di, ds in enumerate(datasets):
        vals = ds['data']
        color = COLORS[di % len(COLORS)]
        points = []
        for i, val in enumerate(vals):
            x = left_margin + (i / (n - 1)) * plot_w if n > 1 else left_margin + plot_w / 2
            y = top_margin + plot_h * (1 - val / y_max)
            points.append((x, y))

        if len(points) > 1:
            path_d = 'M ' + ' L '.join(f'{x:.1f} {y:.1f}' for x, y in points)
            dwg.add(dwg.path(d=path_d, fill='none', stroke=color, stroke_width=2))

        for x, y in points:
            dwg.add(dwg.circle((x, y), 3.5, fill='white', stroke=color, stroke_width=1.5))

        # Labels + values
        for i, (label, (x, y)) in enumerate(zip(labels, points)):
            dwg.add(dwg.text(label, insert=(x, top_margin + plot_h + 14),
                             fill=HERONE['text'], font_size=7.5, text_anchor='middle'))
            dwg.add(dwg.text(str(vals[i]), insert=(x, y - 7), fill=HERONE['text'],
                             font_size=8, font_weight='bold', text_anchor='middle'))

        # Legend (only if multiple datasets)
        if len(datasets) > 1:
            leg = dwg.add(dwg.g(font_size=8))
            for di2, ds2 in enumerate(datasets):
                lx2 = left_margin + di2 * 80
                leg.add(dwg.rect((lx2, 0), (8, 8), fill=COLORS[di2 % len(COLORS)], rx=1))
                leg.add(dwg.text(ds2.get('label', ''), insert=(lx2 + 11, 6), fill=HERONE['text']))

    # Unit
    unit = data.get('unit', '')
    if unit:
        dwg.add(dwg.text(unit, insert=(left_margin - 4, top_margin + 10), fill=HERONE['gray'], font_size=7.5, text_anchor='end'))

    return dwg.tostring()


def render_chart(data):
    t = data.get('type', 'bar')
    if t in ('pie', 'doughnut'):
        return render_doughnut(data)
    elif t == 'line':
        return render_line(data)
    else:
        return render_bar(data)


if __name__ == '__main__':
    raw = sys.stdin.read()
    if not raw.strip():
        print("Usage: echo '{...}' | python3 chart_renderer.py", file=sys.stderr)
        sys.exit(1)
    svg = render_chart(json.loads(raw))
    # Clean up SVG
    svg = re.sub(r'<defs\s*/>', '', svg)
    svg = re.sub(r'\s+xmlns:ev="[^"]*"', '', svg)
    svg = re.sub(r'\s+xmlns:xlink="[^"]*"', '', svg)
    print(svg)
