"""Shared dark intro-bar header used identically across docs/index.html, docs/dashboard.html,
and (mirrored by hand, since that page isn't script-generated) docs/methods.html - so the three
pages read as one site with consistent navigation, rather than three disconnected documents.

Collapsed by default on every page load (no persistence - "at landing the box should be closed"
means every landing, not just the first). Expanding is a single click ("Read what this is about");
collapsing is the X in the open box. Both states are pure CSS driven off a body class, so there is
no flash of the wrong state while JS loads.
"""

from __future__ import annotations

import html as _html

# Default GitHub Pages URL for this repo (eglerean/SciResGDPR, served from /docs, no custom
# domain / CNAME file) - used to build each page's og:url / canonical link for social previews.
BASE_URL = "https://eglerean.github.io/SciResGDPR/"

HEADER_CSS = """
  /* Dark intro bar: closed by default (title-strip), full box opens on click. Both states use
     the same dark colors so the bar never flips to a light background when collapsed. */
  #page-header { display: none; position: relative; padding: 20px 52px 20px 28px;
                 background: #14151a; color: #f5f5f7; }
  body.header-open #page-header { display: block; }
  body.header-open #title-strip { display: none; }
  #page-header .eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px;
                           color: #8fb2ff; font-weight: 600; margin-bottom: 6px; }
  #page-header h1.page-title { font-size: 21px; margin: 0 0 10px; font-weight: 700; color: #fff; }
  #page-header p.abstract { font-size: 13.5px; color: #c7cad1; max-width: 780px;
                             margin: 0 0 14px; line-height: 1.55; }
  #page-header p.abstract a { color: #8fb2ff; }
  #term-legend { display: flex; flex-wrap: wrap; gap: 18px; font-size: 12.5px; color: #c7cad1;
                 margin: 0 0 14px; padding: 10px 14px; background: rgba(255,255,255,0.06);
                 border-radius: 8px; }
  #term-legend b { color: #fff; font-weight: 600; }
  #page-header nav.top-nav { display: flex; gap: 18px; font-size: 13px; margin-bottom: 14px; }
  #page-header nav.top-nav a { color: #8fb2ff; text-decoration: none; font-weight: 500; }
  #page-header nav.top-nav a:hover { text-decoration: underline; }
  #page-header .builder-note { font-size: 12px; color: #9096a3; line-height: 1.55;
                                max-width: 780px; border-top: 1px solid rgba(255,255,255,0.12);
                                padding-top: 12px; margin: 0; }
  #page-header .builder-note a { color: #8fb2ff; }
  #page-header .builder-note .credit { color: #d7d9de; }
  #hide-header-btn {
    position: absolute; top: 16px; right: 16px; width: 28px; height: 28px; border-radius: 50%;
    border: 1px solid rgba(255,255,255,0.25); background: rgba(255,255,255,0.06); color: #f5f5f7;
    font-size: 14px; line-height: 1; cursor: pointer;
  }
  #hide-header-btn:hover { background: rgba(255,255,255,0.16); }

  /* Collapsed strip - the default state. Dark, same as the open box, never a light bar. */
  #title-strip {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    padding: 11px 20px; background: #14151a; color: #f5f5f7;
  }
  #title-strip .back-link { color: #8fb2ff; text-decoration: none; font-size: 13px;
                             font-weight: 500; white-space: nowrap; flex-shrink: 0; }
  #title-strip .back-link:hover { text-decoration: underline; }
  #title-strip .t { font-size: 13.5px; font-weight: 600; color: #fff; }
  #title-strip .sub { font-size: 12.5px; color: #9096a3; }
  #title-strip .credit { font-size: 12px; color: #9096a3; margin-left: auto; white-space: nowrap; }
  #title-strip .expand-btn {
    font-size: 12.5px; color: #8fb2ff; background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.22); border-radius: 6px; padding: 4px 10px;
    cursor: pointer; white-space: nowrap; font-family: inherit;
  }
  #title-strip .expand-btn:hover { background: rgba(255,255,255,0.16); }
  .cc-badge { display: inline-flex; align-items: center; color: inherit; opacity: 0.85; }
  .cc-badge:hover { opacity: 1; }

  /* Always-visible quick nav to the other pages/modes - a page-local rendering of the same
     pill-button look as the explorer's own By theme/By stance toggle, so all four read as one
     control regardless of which page you're on. Sits below the title strip, outside the
     collapsible box, so it's on screen whether or not that box is expanded. */
  .page-nav-bar { display: flex; gap: 6px; flex-wrap: wrap; padding: 10px 20px 0; }
  .page-nav-bar a { font: inherit; font-size: 12.5px; padding: 4px 10px; border-radius: 12px;
                     border: 1px solid var(--line); background: #fff; color: var(--muted);
                     text-decoration: none; }
  .page-nav-bar a:hover { background: #f3f4f6; }
  .page-nav-bar a.current { background: var(--accent); border-color: var(--accent); color: #fff; }
"""

HEADER_JS = """
document.getElementById('hide-header-btn').onclick = () => document.body.classList.remove('header-open');
document.getElementById('expand-header-btn').onclick = () => document.body.classList.add('header-open');
"""

TERM_LEGEND_TEMPLATE = """  <div id="term-legend">
    <span><b>Theme</b>:  a broad topic area · {n_themes} total</span>
    <span><b>Subtheme</b>: a more specific grouping within a theme · {n_subthemes} total</span>
    <span><b>Code</b>: one specific issue or argument, the atomic unit read from the text · {n_codes} total</span>
  </div>
"""


def render_header(
    *,
    title: str,
    strip_subtitle: str,
    abstract_html: str,
    nav_links_html: str,
    linkedin_url: str,
    term_legend_html: str = "",
    strip_back_link_html: str = "",
) -> str:
    """The two-state header block: full dark box (#page-header, closed by default) plus the
    always-rendered collapsed strip (#title-strip) that's visible until the reader expands it."""
    return f"""<div id="page-header">
  <button id="hide-header-btn" title="Hide this panel" aria-label="Hide this panel">✕</button>
  <div class="eyebrow">EDPB Consultation | Draft Guidelines 1/2026</div>
  <h1 class="page-title">{title}</h1>
  <p class="abstract">{abstract_html}</p>
{term_legend_html}  <nav class="top-nav">
    {nav_links_html}
  </nav>
  <p class="builder-note"><span class="credit">Built by {cc_badge_link()}<strong>Enrico Glerean</strong> (done with Claude Code),  <a href="{linkedin_url}" target="_blank" rel="noopener">LinkedIn</a>.</span><br>
    Please note that I built this to make it easier for me to explore the content of the 132 submissions,
    I thought this could be useful for others too. Since the themes were extracted with an LLM the quality
    of the results cannot match what a human would have done with a proper thematic analysis.</p>
</div>
<div id="title-strip">
  {strip_back_link_html}<span class="t">{title}</span>
  <span class="sub">{strip_subtitle}</span>
  <span class="credit">{cc_badge_link()}Enrico Glerean</span>
  <button class="expand-btn" id="expand-header-btn">Read what this is about ▾</button>
</div>"""


def term_legend(n_themes: int, n_subthemes: int, n_codes: int) -> str:
    return TERM_LEGEND_TEMPLATE.format(n_themes=n_themes, n_subthemes=n_subthemes, n_codes=n_codes)


def back_link(href: str, label: str = "← Theme Explorer") -> str:
    return f'<a class="back-link" href="{href}">{label}</a>'


# Small inline SVG rather than a hosted badge image (e.g. licensebuttons.net) - self-contained,
# crisp at any size, and its `currentColor` fills/strokes automatically match whatever text
# color it's dropped into (the light-grey title-strip credit vs. the builder-note credit).
_CC_BADGE_SVG = (
    '<svg width="30" height="15" viewBox="0 0 30 15" aria-hidden="true" focusable="false" '
    'style="vertical-align:-2px;margin-right:3px">'
    '<circle cx="7.5" cy="7.5" r="6.8" fill="none" stroke="currentColor" stroke-width="1"/>'
    '<text x="7.5" y="10.5" text-anchor="middle" font-size="7.5" font-family="Georgia, serif" '
    'fill="currentColor">cc</text>'
    '<circle cx="22.5" cy="7.5" r="6.8" fill="none" stroke="currentColor" stroke-width="1"/>'
    '<text x="22.5" y="10.5" text-anchor="middle" font-size="6.5" font-family="Arial, sans-serif" '
    'fill="currentColor">BY</text>'
    '</svg>'
)


def cc_badge_link() -> str:
    """A small CC BY 4.0 icon linking to the license - this work's licensing, next to the
    credit line wherever "Enrico Glerean" is shown (see docstring at top of this module for
    the pages it appears on)."""
    return (
        '<a class="cc-badge" href="https://creativecommons.org/licenses/by/4.0/" '
        'target="_blank" rel="license noopener" title="Content licensed under CC BY 4.0">'
        f"{_CC_BADGE_SVG}</a>"
    )


def social_meta_html(*, title: str, description: str, path: str = "") -> str:
    """<meta> description + Open Graph + Twitter Card tags for a good social-media preview.

    `title`/`description` are meant to be the same short copy each page already shows in its
    own collapsed title-strip (the page-title and strip_subtitle passed to render_header) -
    reused here rather than duplicated, so the preview text and the on-page text never drift
    apart. `path` is the page's filename relative to BASE_URL (e.g. "methods.html"); leave it
    empty for the site's landing page (index.html), which canonicalises to the bare root URL.
    """
    t = _html.escape(title, quote=True)
    d = _html.escape(description, quote=True)
    url = BASE_URL + path
    return f"""<meta name="description" content="{d}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="EDPB Consultation: GDPR and Scientific Research">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">"""
