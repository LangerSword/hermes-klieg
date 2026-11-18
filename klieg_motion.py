"""klieg_motion: a 2D motion-design engine for Hermes.

Hermes authors a scene - a declarative spec of layers, keyframes and easing, or
raw HTML+GSAP - and klieg compiles it to an HTML+GSAP film and renders it to
MP4/GIF with the deterministic frame pipeline (see scripts/motion_render.py).
This is the authoring core: kinetic type, transitions, loops, lower-thirds, logo
stings, explainers. Local, no API keys.

The compiler turns a spec into HTML that exposes ``window.__tl`` (a GSAP
timeline); the renderer seeks that timeline frame by frame. Effects and eases
are a small, named vocabulary so a model can compose motion without writing raw
GSAP, and the raw-HTML path stays open for custom work.
"""

from __future__ import annotations

import html as _html
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(_HERE, "docs", "explainer", "fonts")
GSAP_SRC = os.path.join(_HERE, "docs", "explainer", "gsap.min.js")

# effect -> GSAP .from() vars (the state an element animates FROM)
EFFECTS = {
    "fade": {"opacity": 0},
    "rise": {"y": 60, "opacity": 0, "filter": "blur(10px)"},
    "drop": {"y": -60, "opacity": 0},
    "slide-left": {"x": -80, "opacity": 0},
    "slide-right": {"x": 80, "opacity": 0},
    "scale": {"scale": 0.6, "opacity": 0, "transformOrigin": "center center"},
    "pop": {"scale": 1.6, "opacity": 0, "transformOrigin": "center center"},
    "blur": {"filter": "blur(16px)", "opacity": 0},
    "spin": {"rotation": -90, "opacity": 0, "transformOrigin": "center center"},
}

_FONTS = {
    "display": ("SG", 700),
    "sans": ("SG", 400),
    "mono": ("JM", 400),
    "hand": ("CV", 400),
}

_GRAIN = ("body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:90;opacity:.06;"
          "background-image:url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
          "width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' "
          "numOctaves='4'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='.55'/></svg>\")}")
_VIGNETTE = ("body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:89;"
             "background:radial-gradient(120% 90% at 50% 42%,transparent 55%,rgba(0,0,0,.55) 100%)}")


def _layer_html(layer: dict) -> tuple[str, list[str]]:
    """Return (dom, timeline_calls) for one layer."""
    lid = layer["id"]
    ltype = layer.get("type", "text")
    x = layer.get("x", 96)
    y = layer.get("y", 200)
    style = [f"position:absolute", f"left:{x}px", f"top:{y}px", "will-change:transform,opacity"]
    calls: list[str] = []

    if ltype == "text":
        if "text" not in layer:
            raise ValueError(f"text layer {lid!r} needs 'text'")
        fam, weight = _FONTS.get(layer.get("font", "display"), _FONTS["display"])
        style += [f"font-family:{fam},sans-serif", f"font-size:{layer.get('size', 64)}px",
                  f"font-weight:{layer.get('weight', weight)}",
                  f"color:{layer.get('color', '#ece4d6')}",
                  f"letter-spacing:{layer.get('letter_spacing', '-0.03em')}",
                  f"line-height:{layer.get('line_height', 1.1)}"]
        text = str(layer["text"])
        anims = layer.get("animate") or []
        split = next((a.get("split") for a in anims if a.get("split")), None)
        if split == "char":
            inner = "".join(f'<span style="display:inline-block;white-space:pre">{_html.escape(c)}</span>'
                            for c in text)
        elif split == "word":
            inner = " ".join(f'<span style="display:inline-block">{_html.escape(w)}</span>'
                             for w in text.split(" "))
        else:
            inner = _html.escape(text).replace("\n", "<br/>")
        dom = f'<div id="{lid}" style="{";".join(style)}">{inner}</div>'
    elif ltype == "box":
        style += [f"width:{layer.get('w', 200)}px", f"height:{layer.get('h', 200)}px",
                  f"background:{layer.get('color', '#d4652a')}",
                  f"border-radius:{layer.get('radius', 0)}px"]
        dom = f'<div id="{lid}" style="{";".join(style)}"></div>'
    elif ltype == "image":
        style += [f"width:{layer.get('w', 300)}px"]
        dom = (f'<div id="{lid}" style="{";".join(style)}">'
               f'<img src="{_html.escape(layer.get("src", ""))}" style="width:100%;display:block"/></div>')
    else:
        raise ValueError(f"unknown layer type {ltype!r} in {lid!r}")

    for a in layer.get("animate") or []:
        effect = a.get("effect", "fade")
        if effect not in EFFECTS:
            raise ValueError(f"unknown effect {effect!r} in layer {lid!r}; try {sorted(EFFECTS)}")
        vars_ = dict(EFFECTS[effect])
        vars_["duration"] = a.get("duration", 0.8)
        if a.get("ease"):
            vars_["ease"] = a["ease"]
        split = a.get("split")
        if split and a.get("stagger"):
            vars_["stagger"] = a["stagger"]
        target = f"#{lid} span" if split else f"#{lid}"
        start = a.get("start", 0)
        calls.append(f"tl.from({json.dumps(target)}, {json.dumps(vars_)}, {start});")
    return dom, calls


def compile_scene(spec: dict) -> str:
    """Compile a declarative motion spec into an HTML+GSAP film exposing window.__tl."""
    if not isinstance(spec, dict):
        raise ValueError("scene spec must be an object")
    layers = spec.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ValueError("scene needs a non-empty 'layers' list")
    w = int(spec.get("width", 1920))
    h = int(spec.get("height", 1080))
    bg = spec.get("background") or {}
    bg_color = bg.get("color", "#070605")
    if bg.get("gradient"):
        bg_css = f"background:{bg['gradient']}"
    else:
        bg_css = f"background:{bg_color}"

    doms, calls = [], []
    for layer in layers:
        if not isinstance(layer, dict) or "id" not in layer:
            raise ValueError("each layer needs an 'id'")
        d, c = _layer_html(layer)
        doms.append(d)
        calls.extend(c)

    extra = ""
    if bg.get("grain"):
        extra += _GRAIN
    if bg.get("vignette"):
        extra += _VIGNETTE

    fonts = f"""
@font-face{{font-family:SG;src:url('{FONT_DIR}/SpaceGrotesk-Regular.otf');font-weight:400}}
@font-face{{font-family:SG;src:url('{FONT_DIR}/SpaceGrotesk-Bold.otf');font-weight:700}}
@font-face{{font-family:JM;src:url('{FONT_DIR}/JetBrainsMono.ttf');font-weight:400}}
@font-face{{font-family:CV;src:url('{FONT_DIR}/Caveat.ttf');font-weight:400}}
"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width={w}"/>
<script src="{GSAP_SRC}"></script>
<style>{fonts}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;{bg_css};color:#ece4d6;font-family:SG,sans-serif;cursor:none}}
{extra}
</style></head>
<body>
{chr(10).join(doms)}
<script>
const tl = gsap.timeline({{defaults:{{ease:"power4.out"}}}});
{chr(10).join(calls)}
window.__tl = tl;
</script>
</body></html>"""


# ------------------------------------------------------------------ templates
def _title_reveal(word="KLIEG", tagline="a DCC bridge for Hermes", **_):
    return {
        "width": 1920, "height": 1080, "fps": 30, "duration": 6,
        "background": {"color": "#070605", "grain": True, "vignette": True},
        "layers": [
            {"id": "word", "type": "text", "text": word, "x": 96, "y": 420, "size": 220,
             "font": "display", "color": "#ece4d6", "letter_spacing": "-0.06em",
             "animate": [{"effect": "rise", "start": 0.2, "duration": 0.9, "ease": "expo.out",
                          "stagger": 0.09, "split": "char"}]},
            {"id": "rule", "type": "box", "x": 100, "y": 700, "w": 640, "h": 2, "color": "#d4652a",
             "animate": [{"effect": "scale", "start": 0.9, "duration": 1.0, "ease": "expo.out"}]},
            {"id": "tag", "type": "text", "text": tagline, "x": 100, "y": 740, "size": 32,
             "font": "sans", "color": "#8a8276",
             "animate": [{"effect": "rise", "start": 1.3, "duration": 0.8}]},
        ],
    }


def _lower_third(name="Ada Lovelace", role="Engineer", **_):
    return {
        "width": 1920, "height": 1080, "fps": 30, "duration": 5,
        "background": {"color": "#070605"},
        "layers": [
            {"id": "bar", "type": "box", "x": 96, "y": 800, "w": 8, "h": 150, "color": "#d4652a",
             "animate": [{"effect": "scale", "start": 0.2, "duration": 0.6, "ease": "expo.out"}]},
            {"id": "name", "type": "text", "text": name, "x": 130, "y": 800, "size": 72,
             "font": "display", "color": "#ece4d6",
             "animate": [{"effect": "slide-left", "start": 0.4, "duration": 0.8, "ease": "expo.out"}]},
            {"id": "role", "type": "text", "text": role, "x": 132, "y": 895, "size": 34,
             "font": "mono", "color": "#d4652a", "letter_spacing": "0.08em",
             "animate": [{"effect": "fade", "start": 0.9, "duration": 0.7}]},
        ],
    }


def _kinetic_quote(quote="Truth is the artefact.", by="Klieg", **_):
    return {
        "width": 1920, "height": 1080, "fps": 30, "duration": 6,
        "background": {"color": "#070605", "grain": True},
        "layers": [
            {"id": "quote", "type": "text", "text": quote, "x": 96, "y": 400, "size": 96,
             "font": "display", "color": "#ece4d6", "letter_spacing": "-0.03em",
             "animate": [{"effect": "rise", "start": 0.2, "duration": 0.8, "ease": "expo.out",
                          "stagger": 0.12, "split": "word"}]},
            {"id": "by", "type": "text", "text": "- " + by, "x": 100, "y": 620, "size": 36,
             "font": "hand", "color": "#d4652a",
             "animate": [{"effect": "fade", "start": 1.6, "duration": 0.8}]},
        ],
    }


def _logo_sting(logo="K", tagline="motion design for Hermes", **_):
    return {
        "width": 1080, "height": 1080, "fps": 30, "duration": 4,
        "background": {"color": "#070605", "vignette": True},
        "layers": [
            {"id": "logo", "type": "text", "text": logo, "x": 420, "y": 360, "size": 300,
             "font": "display", "color": "#d4652a",
             "animate": [{"effect": "pop", "start": 0.2, "duration": 0.8, "ease": "back.out(2)"}]},
            {"id": "tag", "type": "text", "text": tagline, "x": 200, "y": 720, "size": 40,
             "font": "mono", "color": "#ece4d6", "letter_spacing": "0.04em",
             "animate": [{"effect": "blur", "start": 1.0, "duration": 0.9}]},
        ],
    }


TEMPLATES = {
    "title-reveal": (_title_reveal, "Big kinetic word + rule + tagline. Params: word, tagline."),
    "lower-third": (_lower_third, "Name + role bar sliding in. Params: name, role."),
    "kinetic-quote": (_kinetic_quote, "Quote revealed word by word + attribution. Params: quote, by."),
    "logo-sting": (_logo_sting, "Square logo pop + tagline (social). Params: logo, tagline."),
}


def template(template_name: str, **params) -> dict:
    if template_name not in TEMPLATES:
        raise ValueError(f"unknown template {template_name!r}; try {sorted(TEMPLATES)}")
    return TEMPLATES[template_name][0](**params)


def list_templates() -> list[dict]:
    return [{"name": n, "description": d} for n, (_, d) in TEMPLATES.items()]