"""The page's look: dark by default (the owner's Hyperdash-style palette), light (the palette from before) with the
header's switch, every colour a token, text readable in both.

Presentation only, so these read the page's CSS and run its head script, never the engine."""

import json
import re
import shutil
import subprocess

import pytest

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
    assert "color-scheme: light" in LIGHT


# The light palette Signals had before the dark default: the switch brings back this, not a new light look.
BEFORE = {"--bg": "#fafaf9", "--card": "#ffffff", "--fg": "#111112", "--muted": "#6c6c72", "--line": "#ececea",
          "--soft": "#f3f3f1", "--green": "#12a150", "--green-soft": "#e9f7ef", "--danger": "#c43d2f", "--gain": "#087f3d",
          "--loss": "#cf3426", "--amber": "#a86200", "--teal": "#0b7a83", "--blue": "#2557d6", "--accent": "#4b3fe0",
          "--on-accent": "#ffffff", "--av-l": "93%", "--av-fg-l": "48%", "--av-s": "42%"}  # fmt: skip


def test_light_is_the_palette_from_before_with_only_the_unreadable_grey_darkened() -> None:
    light = tokens(LIGHT)
    assert {k: light[k] for k in BEFORE} == BEFORE  # purple accent and all
    assert light["--faint"] == "#6e6e73"  # was #a1a1a6 (2.5:1): the nearest grey that reads at AA


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


def test_the_header_has_a_theme_switch_that_says_what_it_does() -> None:
    header = PAGE[PAGE.index('<header class="top">') : PAGE.index("</header>")]
    assert '<button type="button" class="theme-btn" id="theme" aria-label="Light theme"' in header  # dark first
    assert 'class="sun"' in header and 'class="moon"' in header
    assert '$("#theme").onclick' in PAGE
    assert "setTheme(" in PAGE[: PAGE.index("</head>")]  # applied in the head, before the first paint


def run_head(stored: str | None) -> dict[str, object]:
    """The head's theme script in Node, with this browser's storage holding ``stored`` ("blocked": every read and
    write throws), then one press of the switch."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node isn't installed: the page's JavaScript can't be run here")
    start = PAGE.index("<script>", PAGE.index("</style>"))
    script = PAGE[start + len("<script>") : PAGE.index("</script>", start)]
    stub = f"""
      const blocked = {json.dumps(stored == "blocked")}; const kept = new Map();
      if (!blocked && {json.dumps(stored)} !== null) kept.set("signals.theme", {json.dumps(stored)});
      globalThis.localStorage = {{
        getItem(k) {{ if (blocked) throw new Error("blocked"); return kept.has(k) ? kept.get(k) : null; }},
        setItem(k, v) {{ if (blocked) throw new Error("blocked"); kept.set(k, v); }} }};
      const el = () => ({{ attrs: {{}}, setAttribute(k, v) {{ this.attrs[k] = v; }} }});
      const root = {{ dataset: {{}} }}, bar = el(), scheme = el(), btn = el();
      globalThis.document = {{ documentElement: root, getElementById: (id) => (id === "theme" ? btn : null),
        querySelector: (s) => (s.includes("theme-color") ? bar : s.includes("color-scheme") ? scheme : null) }};
      globalThis.getComputedStyle = () => ({{ getPropertyValue: (n) =>
        n === "--bg" ? (root.dataset.theme === "light" ? " {tokens(LIGHT)["--bg"]}" : " {tokens(DARK)["--bg"]}") : "" }});
    """
    after = """
      const first = { theme: root.dataset.theme, bar: bar.attrs.content, scheme: scheme.attrs.content, label: btn.attrs["aria-label"] };
      setTheme(root.dataset.theme === "light" ? "dark" : "light", true);  // a press of the switch
      process.stdout.write(JSON.stringify({ first, pressed: root.dataset.theme, bar: bar.attrs.content,
        label: btn.attrs["aria-label"], kept: blocked ? null : kept.get("signals.theme") ?? null }));
    """
    r = subprocess.run([node, "-e", stub + script + after], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)  # type: ignore[no-any-return]


def test_the_theme_is_dark_by_default_remembered_and_works_with_storage_blocked() -> None:
    dark, light = tokens(DARK)["--bg"], tokens(LIGHT)["--bg"]
    new = run_head(None)  # a first visit: dark, and the browser's bar matches
    assert new["first"] == {"theme": "dark", "bar": dark, "scheme": "dark", "label": "Light theme"}
    assert (new["pressed"], new["bar"], new["label"], new["kept"]) == ("light", light, "Dark theme", "light")
    back = run_head("light")  # they chose light before: light from the first paint
    assert back["first"] == {"theme": "light", "bar": light, "scheme": "light", "label": "Dark theme"}
    assert (back["pressed"], back["kept"]) == ("dark", "dark")
    assert run_head("purple")["first"]["theme"] == "dark"  # anything else kept: dark
    blocked = run_head("blocked")  # a private window: dark, and the switch still works for the visit
    assert blocked["first"]["theme"] == "dark" and blocked["pressed"] == "light"
