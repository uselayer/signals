"""The page's look: dark by default (the owner's Hyperdash-style palette), every colour a token, text readable.

Presentation only, so these read the page's CSS, never the engine."""

import re

from signals import app as engine

PAGE = (engine.HERE / "static" / "index.html").read_text()
CSS = PAGE[PAGE.index("<style>") : PAGE.index("</style>")]
DARK = CSS[CSS.index("  :root {") : CSS.index("  }", CSS.index("  :root {"))]
LIGHT = CSS[CSS.index(':root[data-theme="light"] {') : CSS.index("  }", CSS.index(':root[data-theme="light"] {'))]
RULES = CSS[CSS.index("  * { box-sizing") :]  # every component rule: after the two token blocks


def tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", block))


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_dark_is_the_default_and_the_browser_chrome_matches() -> None:
    dark = tokens(DARK)
    assert "color-scheme: dark" in DARK and dark["--bg"] == "#0e0e0f" and dark["--card"] == "#161617"
    assert "prefers-color-scheme" not in CSS  # dark for everyone, whatever the system says
    assert f'<meta name="theme-color" content="{dark["--bg"]}">' in PAGE  # mobile browser bar = the page
    assert '<meta name="color-scheme" content="dark">' in PAGE  # no white flash, dark scrollbars and menus
    assert "color-scheme: light" in LIGHT  # the light palette stays, for a switch later


def test_every_token_the_page_uses_is_defined_in_both_themes() -> None:
    used = set(re.findall(r"var\((--[a-z0-9-]+)", PAGE)) - {"--h", "--c"}  # per-element: avatar hue, tier colour
    dark, light = tokens(DARK), tokens(LIGHT)
    assert used - set(dark) == set()
    assert set(dark) - {"--r", "--r-sm"} == set(light)  # the same palette in both themes; radii are shared


def test_component_rules_use_tokens_never_a_literal_colour() -> None:
    """No #fff, white or light rgba left in a component rule: a hard-coded light colour is what breaks a dark page.
    Only black, see-through shadows may be literal."""
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", RULES) == []
    assert re.findall(r"(?<![-\w])(white|black)(?![-\w])", RULES) == []  # white-space is fine
    assert [c for c in re.findall(r"rgba?\(([^)]*)\)", RULES) if not re.match(r"0,\s*0,\s*0,", c)] == []
    script = PAGE[PAGE.index("</style>") :]  # the markup and code: charts and inline styles take tokens too
    assert re.findall(r'(?:fill|stroke|color|background)[=:]\s*"?#[0-9a-fA-F]{3,8}', script) == []


def test_text_meets_wcag_aa_in_both_themes() -> None:
    for theme in (tokens(DARK), tokens(LIGHT)):
        for surface in ("--bg", "--card", "--soft"):
            for text in ("--fg", "--muted", "--faint"):
                assert contrast(theme[text], theme[surface]) >= 4.5, (text, surface, theme[text])
        for surface in ("--bg", "--card"):
            for text in ("--gain", "--loss", "--accent", "--danger"):
                assert contrast(theme[text], theme[surface]) >= 4.5, (text, surface, theme[text])
        assert contrast(theme["--on-accent"], theme["--accent"]) >= 4.5  # a button's words on the accent
        assert contrast(theme["--toast-fg"], theme["--toast-bg"]) >= 4.5


def test_profit_and_loss_are_the_only_green_and_red_and_the_cost_box_stays_uncoloured() -> None:
    dark = tokens(DARK)
    assert (dark["--gain"], dark["--loss"]) == ("#3ecf8e", "#f0506e")
    assert dark["--accent"] not in (dark["--gain"], dark["--loss"])  # Signals' own colour is never a gain or loss
    cost = [r for r in re.findall(r"[^{}]*\{[^}]*\}", RULES) if re.search(r"\.(receipt|copybox|qfacts|amount)\b", r.split("{")[0])]
    assert cost and not [r for r in cost if re.search(r"var\(--(gain|loss|green|green-soft)\)", r)]
