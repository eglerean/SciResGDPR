"""Build a one-page stance-summary dashboard (Plotly) across all themes and subthemes.

Usage:
    python scripts/build_dashboard.py

The explorer (docs/index.html) shows the stance breakdown for one theme or subtheme at a time -
useful for reading, but you have to click through 17 themes one by one to compare them. This page
puts the whole picture in one view: a stacked bar per theme, and a theme-selectable second chart
for its subthemes.

Reads  output/themes.xlsx ("Theme Summary" and "Subthemes" sheets, from build_themes.py)
Writes docs/dashboard.html
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from site_header import HEADER_CSS, HEADER_JS, back_link, render_header, term_legend

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"

# Same hexes as docs/index.html (build_explorer.py) and the methods report, so a reader
# recognises the stance encoding across all three pages.
STANCE_COLORS = {
    "support": "#4C9F70",
    "oppose": "#D1495B",
    "request_clarification": "#3D7EA6",
    "propose_change": "#E8A33D",
    "concern": "#B07AA1",
    "other": "#9AA0A6",
}
STANCE_ORDER = list(STANCE_COLORS.keys())

LINKEDIN_URL = "__LINKEDIN_URL_PLACEHOLDER__"


def main():
    xl = pd.ExcelFile(OUTPUT_DIR / "themes.xlsx")
    theme_summary = pd.read_excel(xl, "Theme Summary")
    subtheme_summary = pd.read_excel(xl, "Subthemes")

    n_themes = len(theme_summary)
    n_subthemes = len(subtheme_summary)
    n_codes = int(pd.read_excel(xl, "Codes").shape[0]) if "Codes" in xl.sheet_names else 0

    # Row order matches themes.xlsx (already sorted by prevalence); Plotly draws bottom-to-top,
    # so reverse for the largest theme to land at the top of a horizontal chart.
    theme_summary = theme_summary.iloc[::-1].reset_index(drop=True)

    payload = {
        "themes": theme_summary.to_dict("records"),
        "subthemes_by_theme": {
            theme: sub.iloc[::-1][["subtheme", "n_submissions", *STANCE_ORDER]].to_dict("records")
            for theme, sub in subtheme_summary.groupby("theme")
        },
        "stance_colors": STANCE_COLORS,
        "stance_order": STANCE_ORDER,
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    header_html = render_header(
        title="Stance Dashboard",
        strip_subtitle="Support/oppose/concern breakdown for all 17 themes in one view",
        abstract_html=(
            "Every theme's stance breakdown (support / oppose / request clarification / propose change / "
            "concern / other) in one view, instead of clicking through each theme individually in the "
            "explorer. Bar length is submissions raising that theme; segments show how those submissions "
            "were coded. Select a theme below to see the same breakdown for its subthemes."
        ),
        nav_links_html=back_link("index.html") + '\n    <a href="methods.html">Methods →</a>',
        linkedin_url=LINKEDIN_URL,
        term_legend_html=term_legend(n_themes, n_subthemes, n_codes),
        strip_back_link_html=back_link("index.html") + " ",
    )

    html = (
        HTML_TEMPLATE.replace("__DATA__", data_json)
        .replace("__HEADER_CSS__", HEADER_CSS)
        .replace("__HEADER_HTML__", header_html)
        .replace("__HEADER_JS__", HEADER_JS)
    )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(theme_summary)} themes, {len(subtheme_summary)} subthemes)")
    if "PLACEHOLDER" in LINKEDIN_URL:
        print("WARNING: LINKEDIN_URL is still a placeholder.")


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDPB consultation — stance dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.3/plotly.min.js"></script>
<style>
  :root {
    --bg: #ffffff; --fg: #1c1c1e; --muted: #6b7280; --line: #e5e7eb;
    --panel: #fafafa; --accent: #2563eb;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--fg);
               font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
__HEADER_CSS__
  main { max-width: 1080px; margin: 0 auto; padding: 24px 28px 80px; }
  section { margin-top: 36px; }
  section h2 { font-size: 15px; margin: 0 0 4px; }
  section p.sub { font-size: 12.5px; color: var(--muted); margin: 0 0 14px; }
  select { font-size: 13px; padding: 5px 10px; border: 1px solid var(--line); border-radius: 6px;
           background: var(--panel); color: var(--fg); }
  #theme-chart, #subtheme-chart { width: 100%; }
</style>
</head>
<body>
__HEADER_HTML__
<main>
  <section>
    <h2>All themes</h2>
    <p class="sub">Ordered by number of submissions raising the theme.</p>
    <div id="theme-chart"></div>
  </section>

  <section>
    <h2>Subthemes within a theme</h2>
    <p class="sub"><label for="theme-select">Theme:</label> <select id="theme-select"></select></p>
    <div id="subtheme-chart"></div>
  </section>
</main>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const STANCE_ORDER = DATA.stance_order, COLORS = DATA.stance_colors;

__HEADER_JS__

function stanceTraces(rows, yKey) {
  return STANCE_ORDER.map(stance => ({
    type: 'bar',
    orientation: 'h',
    name: stance.replace(/_/g, ' '),
    y: rows.map(r => r[yKey]),
    x: rows.map(r => r[stance]),
    marker: { color: COLORS[stance] },
    hovertemplate: '%{y}<br>' + stance.replace(/_/g, ' ') + ': %{x}<extra></extra>',
  }));
}

const baseLayout = {
  barmode: 'stack',
  margin: { l: 280, r: 20, t: 10, b: 40 },
  legend: { orientation: 'h', y: -0.08 },
  font: { family: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', size: 12, color: '#1c1c1e' },
  xaxis: { title: 'Codes', gridcolor: '#eee' },
  yaxis: { automargin: true },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
};

Plotly.newPlot('theme-chart', stanceTraces(DATA.themes, 'theme'),
  { ...baseLayout, height: Math.max(320, DATA.themes.length * 34) },
  { responsive: true, displayModeBar: false });

const select = document.getElementById('theme-select');
Object.keys(DATA.subthemes_by_theme).sort().forEach(theme => {
  const opt = document.createElement('option');
  opt.value = theme; opt.textContent = theme;
  select.appendChild(opt);
});

function renderSubthemes(theme) {
  const rows = DATA.subthemes_by_theme[theme] || [];
  Plotly.react('subtheme-chart', stanceTraces(rows, 'subtheme'),
    { ...baseLayout, height: Math.max(280, rows.length * 34) },
    { responsive: true, displayModeBar: false });
}

// Default to the most-prevalent theme (top bar of the chart above), not alphabetically first.
const defaultTheme = DATA.themes[DATA.themes.length - 1].theme;
select.value = defaultTheme;
renderSubthemes(defaultTheme);
select.onchange = () => renderSubthemes(select.value);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
