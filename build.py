#!/usr/bin/env python3
"""
Minimal build script — replaces the Gulp pipeline (Gulp 3 is broken on Node 24).

Concatenates JS and CSS source files in the same order Gulp used and writes them
to the existing hashed dist/ filenames, then injects the asset tags into
dist/index.html. No minification — fine for a self-hosted deployment and far
easier to debug.

Usage:  python3 build.py
"""
import glob
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Output filenames (must match dist/index.html asset references) ----------
JS_OUT          = "dist/js/app-d29a669ccd.min.js"
CSS_APP_OUT     = "dist/css/app-88e5754bef.css"
CSS_THEME_OUT   = "dist/css/ogrid-theme-blue-3bdf96e829.css"
CSS_LOGIN_OUT   = "dist/css/login-custom-40ebfc9dbf.css"

# --- Fixed asset tags injected into dist/index.html --------------------------
HEAD_CSS = '  <link rel="stylesheet" href="css/lib-3e73535c69.css">'
HEAD_JS  = '  <script src="js/lib-bundle-0e6b948858.min.js"></script>'
BODY_CSS = (
    '  <link rel="stylesheet" href="css/app-88e5754bef.css">\n'
    '  <link rel="stylesheet" href="css/login-custom-40ebfc9dbf.css">\n'
    '  <link rel="stylesheet" href="css/ogrid-theme-blue-3bdf96e829.css">'
)
BODY_JS = (
    '  <script src="js/app-d29a669ccd.min.js"></script>\n'
    '  <script src="config/EnvSettings-9d8e78364a.js"></script>'
)

# --- JS source order (mirrors gulpfile.js app_sources) -----------------------
APP_SOURCES = [
    "src/js/ogrid.js",
    "src/js/core/Class.js",
    "src/js/core/QSearchProcessor.js",
    "src/js/ux/Main.js",
    "src/js/ux/manage/SecuredFunctions.js",
    "src/js/util/service/BaseServiceErrorHandler.js",
    "src/js/custom/service/TemplateServiceErrorHandler.js",
    "src/js/data/ShapeMap.js",
    "src/js/custom/data/ChicagoZipShapeMap.js",
    "src/js/custom/data/ChicagoWardsShapeMap.js",
    "src/js/custom/data/ChicagoCityShapeMap.js",
    "src/js/custom/qsearch/LatLng.js",
    "src/js/custom/qsearch/Place.js",
    "src/js/custom/qsearch/FlexSearchBuilder.js",
    "src/js/custom/qsearch/FlexData.js",
    "src/js/custom/qsearch/AISearch.js",
    "src/js/custom/Config.js",
    "src/js/session/Session.js",
    "src/js/**/*.js",  # everything else, deduped
]


def _abs(p):
    return os.path.join(ROOT, p)


def _resolve_js_order():
    """Expand globs and dedupe, preserving the explicit dependency order."""
    ordered, seen = [], set()
    for entry in APP_SOURCES:
        matches = sorted(glob.glob(_abs(entry), recursive=True)) if "*" in entry else [_abs(entry)]
        for m in matches:
            if os.path.isfile(m) and m not in seen:
                seen.add(m)
                ordered.append(m)
    return ordered


def _concat(paths):
    parts = []
    for p in paths:
        rel = os.path.relpath(p, ROOT)
        with open(p, "r", encoding="utf-8") as f:
            parts.append(f"/* === {rel} === */\n{f.read()}\n")
    return "\n".join(parts)


def _write(rel_out, content):
    out = _abs(rel_out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  wrote {rel_out}  ({len(content):,} bytes)")


def build_js():
    paths = _resolve_js_order()
    _write(JS_OUT, _concat(paths))
    print(f"  ({len(paths)} JS files)")


def build_css():
    all_css = sorted(glob.glob(_abs("src/css/*.css")))
    theme = _abs("src/css/ogrid-theme-blue.css")
    login = _abs("src/css/login-custom.css")
    app_css = [p for p in all_css if p not in (theme, login)]
    _write(CSS_APP_OUT, _concat(app_css))
    if os.path.isfile(theme):
        _write(CSS_THEME_OUT, _concat([theme]))
    if os.path.isfile(login):
        _write(CSS_LOGIN_OUT, _concat([login]))


def _inject(html, open_marker, close_marker, payload):
    start = html.index(open_marker)
    end = html.index(close_marker, start)
    return html[:start + len(open_marker)] + "\n" + payload + "\n  " + html[end:]


def build_html():
    with open(_abs("src/index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = _inject(html, "<!-- inject:head:css -->", "<!-- endinject -->", HEAD_CSS)
    html = _inject(html, "<!-- inject:head:js -->", "<!-- endinject -->", HEAD_JS)
    html = _inject(html, "<!-- inject:css -->", "<!-- endinject -->", BODY_CSS)
    html = _inject(html, "<!-- inject:js -->", "<!-- endinject -->", BODY_JS)
    _write("dist/index.html", html)


if __name__ == "__main__":
    print("Building OpenGrid frontend → dist/ ...")
    build_js()
    build_css()
    build_html()
    print("Done.")
