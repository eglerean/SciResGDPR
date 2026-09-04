"""Build a self-contained interactive HTML explorer for the theme hierarchy.

Usage:
    python scripts/build_explorer.py

Reads  output/theme_tree.json (from build_themes.py)
Writes docs/index.html - the repository's landing page, served by GitHub Pages from /docs.

Everything is precomputed in Python and embedded as JSON - the page does no layout or analysis
at load time, which is what keeps it fast (the same approach used for the sigma.js graph in
experiments/).
"""

from __future__ import annotations

import json
from pathlib import Path

from site_header import HEADER_CSS, HEADER_JS, render_header, term_legend

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"

STANCE_COLORS = {
    "support": "#4C9F70",
    "oppose": "#D1495B",
    "request_clarification": "#3D7EA6",
    "propose_change": "#E8A33D",
    "concern": "#B07AA1",
    "other": "#9AA0A6",
}

LINKEDIN_URL = "__LINKEDIN_URL_PLACEHOLDER__"


def main():
    tree = json.loads((OUTPUT_DIR / "theme_tree.json").read_text(encoding="utf-8"))
    payload = {"tree": tree, "stance_colors": STANCE_COLORS}
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    n_themes = len(tree)
    n_sub = sum(len(t["subthemes"]) for t in tree)
    n_codes = sum(len(s["codes"]) for t in tree for s in t["subthemes"])

    header_html = render_header(
        title="What 132 Submissions Say About GDPR and Scientific Research",
        strip_subtitle="132 EDPB consultation submissions on GDPR and scientific research, organised by theme",
        abstract_html=(
            "This explorer organises 132 written submissions to the EDPB's public consultation on "
            "Draft Guidelines 1/2026 (the GDPR and scientific research) into a browsable hierarchy of "
            "themes, subthemes, and specific issues — built by having an LLM read every paragraph, name "
            "the individual arguments it raises, and cluster those arguments rather than the raw text. "
            "<strong>To use it:</strong> click a theme in the left-hand tree to expand its subthemes and "
            "issues; selecting any node shows how many submissions raised it, the balance of "
            "support/opposition/concern, and representative quotes linked back to the original source PDF. "
            'See the <a href="methods.html">methods page</a> for how this was built and its limitations, '
            'or the <a href="dashboard.html">dashboard</a> for a one-page stance overview across all themes.'
        ),
        nav_links_html='<a href="methods.html">Methods →</a>\n    <a href="dashboard.html">Dashboard →</a>',
        linkedin_url=LINKEDIN_URL,
        term_legend_html=term_legend(n_themes, n_sub, n_codes),
    )

    html = (
        HTML_TEMPLATE.replace("__DATA__", data_json)
        .replace("__HEADER_CSS__", HEADER_CSS)
        .replace("__HEADER_HTML__", header_html)
        .replace("__HEADER_JS__", HEADER_JS)
    )
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"Wrote {out_path} ({n_themes} themes, {n_sub} subthemes, {n_codes} codes)")
    if "PLACEHOLDER" in LINKEDIN_URL:
        print("WARNING: LINKEDIN_URL is still a placeholder.")


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>EDPB consultation — theme explorer</title>
<style>
  :root {
    --bg: #ffffff; --fg: #1c1c1e; --muted: #6b7280; --line: #e5e7eb;
    --panel: #fafafa; --accent: #2563eb; --hover: #f3f4f6;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               color: var(--fg); background: var(--bg); font-size: 14px; }
  html, body { display: flex; flex-direction: column; }
__HEADER_CSS__
  #app { display: flex; flex: 1; min-height: 0; }
  #sidebar { width: 420px; flex-shrink: 0; border-right: 1px solid var(--line); overflow-y: auto;
             background: var(--panel); }
  #detail { flex: 1; overflow-y: auto; padding: 24px 28px; }
  #sidebar h1 { font-size: 15px; margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line);
       position: sticky; top: 0; background: var(--panel); z-index: 2; }
  #sidebar h1 small { display: block; color: var(--muted); font-weight: 400; margin-top: 3px; font-size: 12px; }
  #drawer-close, #drawer-open { display: none; }
  .node { cursor: pointer; user-select: none; }
  .node-row { display: flex; align-items: center; gap: 7px; padding: 6px 10px; border-radius: 5px; }
  .node-row:hover { background: var(--hover); }
  .node-row.selected { background: #dbeafe; }
  .caret { width: 12px; color: var(--muted); flex-shrink: 0; font-size: 10px; }
  .label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .count { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 12px; flex-shrink: 0; }
  .theme > .node-row { font-weight: 600; }
  .subtheme { margin-left: 16px; }
  .subtheme > .node-row { font-weight: 500; font-size: 13.5px; }
  .leaf { margin-left: 32px; }
  .leaf > .node-row { font-size: 13px; color: #374151; }
  .children { display: none; }
  .children.open { display: block; }
  .stance-bar { display: flex; height: 9px; border-radius: 5px; overflow: hidden; margin: 10px 0 4px; }
  .stance-bar div { height: 100%; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--muted); margin-bottom: 20px; }
  .legend span.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; }
  .stat-row { display: flex; gap: 28px; margin: 4px 0 14px; }
  .stat { }
  .stat .v { font-size: 24px; font-weight: 600; }
  .stat .k { font-size: 12px; color: var(--muted); }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 16px; }
  .chip { background: #eef2f7; border-radius: 11px; padding: 2px 9px; font-size: 12px; color: #374151; }
  .quote { border-left: 3px solid var(--line); padding: 8px 0 8px 12px; margin-bottom: 14px; }
  .quote .meta { font-size: 12px; color: var(--muted); margin-bottom: 2px; }
  .quote .meta2 { font-size: 11.5px; color: var(--muted); margin-bottom: 4px; display: flex;
                   align-items: center; gap: 8px; flex-wrap: wrap; }
  .quote .claim { font-weight: 500; margin-bottom: 5px; }
  .quote .text { font-size: 13px; color: #4b5563; white-space: pre-wrap; max-height: 8.5em; overflow: hidden; }
  .quote .text.expanded { max-height: none; }
  .quote .more { font-size: 12px; color: var(--accent); cursor: pointer; margin-top: 3px; }
  .badge { display: inline-block; padding: 1px 7px; border-radius: 9px; font-size: 11px; color: #fff; }
  .badge-outline { display: inline-block; padding: 0px 6px; border-radius: 9px; font-size: 10.5px;
                    color: var(--muted); border: 1px solid var(--line); }
  .quote .source-link { color: var(--accent); text-decoration: none; }
  .quote .source-link:hover { text-decoration: underline; }
  h2 { font-size: 20px; margin: 0 0 3px; }
  .crumb { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
  section h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted);
               margin: 22px 0 8px; }
  .empty { color: var(--muted); margin-top: 60px; text-align: center; }

  /* Phone portrait: the theme tree becomes a drawer over the detail panel rather than a fixed
     column, since there isn't room for both side by side. It starts OPEN on load - that's the
     onboarding cue that themes/subthemes are the way in - and is sized to leave a visible strip
     of the detail panel showing on the right, so a reader sees that picking a theme changes the
     page underneath before they ever close the drawer themselves. */
  @media (max-width: 700px) and (orientation: portrait) {
    #app { position: relative; overflow: hidden; }
    #sidebar {
      position: absolute; inset: 0 16% 0 0; z-index: 10;
      box-shadow: 3px 0 24px rgba(0,0,0,0.22);
      transition: transform 0.25s ease;
    }
    #app.drawer-closed #sidebar { transform: translateX(-100%); }
    #sidebar h1 { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    #drawer-close {
      display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;
      width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--line);
      background: #fff; color: var(--muted); font-size: 13px; cursor: pointer;
    }
    #drawer-open {
      display: none; position: absolute; top: 14px; left: 14px; z-index: 11;
      padding: 8px 16px; border-radius: 20px; border: none;
      background: var(--accent); color: #fff; font-size: 13px; font-weight: 600;
      box-shadow: 0 3px 10px rgba(0,0,0,0.2); cursor: pointer;
    }
    #app.drawer-closed #drawer-open { display: block; }
    #detail { width: 100%; }
  }
</style>
</head>
<body>
__HEADER_HTML__
<div id="app">
  <div id="sidebar">
    <h1><span>Themes<small id="subtitle"></small></span><button id="drawer-close" aria-label="Close theme menu" title="Close">✕</button></h1>
    <div id="tree"></div>
  </div>
  <button id="drawer-open" aria-label="Open theme menu">☰ Themes</button>
  <div id="detail"><div class="empty">Select a theme, subtheme or code on the left.</div></div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const TREE = DATA.tree, COLORS = DATA.stance_colors;
const STANCE_ORDER = ['support','oppose','request_clarification','propose_change','concern','other'];

document.getElementById('subtitle').textContent =
  TREE.length + ' themes · ' +
  TREE.reduce((a,t) => a + t.subthemes.length, 0) + ' subthemes · ' +
  TREE.reduce((a,t) => a + t.subthemes.reduce((b,s) => b + s.codes.length, 0), 0) + ' codes';

__HEADER_JS__

function stanceBar(stances) {
  const total = Object.values(stances).reduce((a,b)=>a+b, 0);
  if (!total) return '';
  let html = '<div class="stance-bar">';
  STANCE_ORDER.forEach(s => {
    const n = stances[s] || 0;
    if (n) html += '<div style="width:' + (100*n/total) + '%;background:' + COLORS[s] + '" title="' + s + ': ' + n + '"></div>';
  });
  html += '</div><div class="legend">';
  STANCE_ORDER.forEach(s => {
    const n = stances[s] || 0;
    if (n) html += '<span><span class="dot" style="background:' + COLORS[s] + '"></span>' + s.replace(/_/g,' ') + ' ' + n + '</span>';
  });
  return html + '</div>';
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function renderDetail(node, kind, crumb) {
  const d = document.getElementById('detail');
  const title = node.theme || node.subtheme || node.code;
  let html = '<div class="crumb">' + esc(crumb) + '</div><h2>' + esc(title) + '</h2>';
  html += '<div class="stat-row">' +
    '<div class="stat"><div class="v">' + node.n_submissions + '</div><div class="k">submissions</div></div>' +
    '<div class="stat"><div class="v">' + node.n_paragraphs + '</div><div class="k">paragraphs</div></div>';
  if (kind === 'theme') html += '<div class="stat"><div class="v">' + node.subthemes.length + '</div><div class="k">subthemes</div></div>';
  if (kind === 'subtheme') html += '<div class="stat"><div class="v">' + node.codes.length + '</div><div class="k">codes</div></div>';
  html += '</div>';
  html += stanceBar(node.stances || {});

  if (kind === 'theme') {
    html += '<section><h3>Subthemes</h3><div class="chips">' +
      node.subthemes.map(s => '<span class="chip">' + esc(s.subtheme) + ' · ' + s.n_submissions + '</span>').join('') +
      '</div></section>';
  }
  if (kind === 'subtheme') {
    html += '<section><h3>Codes</h3><div class="chips">' +
      node.codes.map(c => '<span class="chip">' + esc(c.code) + ' · ' + c.n_submissions + '</span>').join('') +
      '</div></section>';
  }
  if (kind === 'code') {
    if (node.countries && node.countries.length)
      html += '<section><h3>Countries</h3><div class="chips">' +
        node.countries.map(c => '<span class="chip">' + esc(c) + '</span>').join('') + '</div></section>';
    if (node.organisations && node.organisations.length)
      html += '<section><h3>Organisations</h3><div class="chips">' +
        node.organisations.map(o => '<span class="chip">' + esc(o) + '</span>').join('') + '</div></section>';
    if (node.targets && node.targets.length)
      html += '<section><h3>Provisions cited</h3><div class="chips">' +
        node.targets.map(t => '<span class="chip">' + esc(t) + '</span>').join('') + '</div></section>';
    html += '<section><h3>Representative comments</h3>';
    node.quotes.forEach(q => {
      const sourceLink = q.source_url
        ? '<a class="source-link" href="' + esc(q.source_url) + '" target="_blank" rel="noopener">View original PDF ↗</a>'
        : '';
      html += '<div class="quote">' +
        '<div class="meta"><span class="badge" style="background:' + (COLORS[q.stance] || '#999') + '">' +
          esc(q.stance).replace(/_/g,' ') + '</span> ' +
          esc(q.organisation_name) + (q.country ? ' · ' + esc(q.country) : '') +
          ' · <code>' + esc(q.paragraph_id) + '</code></div>' +
        '<div class="meta2">' +
          (q.organisation_type ? '<span class="badge-outline">' + esc(q.organisation_type) + '</span>' : '') +
          (q.submission_date ? '<span>' + esc(q.submission_date) + '</span>' : '') +
          (sourceLink ? '<span>' + sourceLink + '</span>' : '') +
        '</div>' +
        '<div class="claim">' + esc(q.claim) + '</div>' +
        '<div class="text">' + esc(q.text) + '</div>' +
        '<div class="more">show full paragraph</div></div>';
    });
    html += '</section>';
  }
  d.innerHTML = html;
  d.querySelectorAll('.more').forEach(el => {
    el.onclick = () => {
      const t = el.previousElementSibling;
      t.classList.toggle('expanded');
      el.textContent = t.classList.contains('expanded') ? 'collapse' : 'show full paragraph';
    };
  });
  d.scrollTop = 0;
}

function select(row, node, kind, crumb) {
  document.querySelectorAll('.node-row.selected').forEach(r => r.classList.remove('selected'));
  row.classList.add('selected');
  renderDetail(node, kind, crumb);
  // On phone-portrait the tree is a drawer over the detail panel; a code is the only kind of
  // node with excerpts to read, so picking one is the moment to get the drawer out of the way.
  // A no-op on desktop, where the media query never applies the drawer-closed transform.
  if (kind === 'code') document.getElementById('app').classList.add('drawer-closed');
}

const appEl = document.getElementById('app');
document.getElementById('drawer-close').onclick = () => appEl.classList.add('drawer-closed');
document.getElementById('drawer-open').onclick = () => appEl.classList.remove('drawer-closed');

function makeRow(label, count, cls, hasChildren) {
  const div = document.createElement('div');
  div.className = 'node ' + cls;
  const row = document.createElement('div');
  row.className = 'node-row';
  row.innerHTML = '<span class="caret">' + (hasChildren ? '▶' : '') + '</span>' +
                  '<span class="label">' + esc(label) + '</span>' +
                  '<span class="count">' + count + '</span>';
  div.appendChild(row);
  return { div, row, caret: row.querySelector('.caret') };
}

const treeEl = document.getElementById('tree');
TREE.forEach(theme => {
  const t = makeRow(theme.theme, theme.n_submissions, 'theme', true);
  const tChildren = document.createElement('div');
  tChildren.className = 'children';

  theme.subthemes.forEach(sub => {
    const s = makeRow(sub.subtheme, sub.n_submissions, 'subtheme', sub.codes.length > 0);
    const sChildren = document.createElement('div');
    sChildren.className = 'children';

    sub.codes.forEach(code => {
      const c = makeRow(code.code, code.n_submissions, 'leaf', false);
      c.row.onclick = (e) => {
        e.stopPropagation();
        select(c.row, code, 'code', theme.theme + ' › ' + sub.subtheme);
      };
      sChildren.appendChild(c.div);
    });

    s.row.onclick = (e) => {
      e.stopPropagation();
      sChildren.classList.toggle('open');
      s.caret.textContent = sChildren.classList.contains('open') ? '▼' : '▶';
      select(s.row, sub, 'subtheme', theme.theme);
    };
    s.div.appendChild(sChildren);
    tChildren.appendChild(s.div);
  });

  t.row.onclick = () => {
    tChildren.classList.toggle('open');
    t.caret.textContent = tChildren.classList.contains('open') ? '▼' : '▶';
    select(t.row, theme, 'theme', 'All themes');
  };
  t.div.appendChild(tChildren);
  treeEl.appendChild(t.div);
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
