"""Sphinx configuration."""

from __future__ import annotations

import sys

from importlib.metadata import version as get_version
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

project = "humble-steam-key-redeemer"
author = "Jon Bogaty"
copyright = "2026, Jon Bogaty"  # noqa: A001

try:
    release = get_version("humble-steam-key-redeemer")
except Exception:  # pragma: no cover - docs may build from a source tree
    release = "0.0.0"
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinxext.opengraph",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns: list[str] = []

# -- HTML output -------------------------------------------------------------

html_theme = "furo"
html_title = f"{project} {release}"
html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "source_repository": "https://github.com/jbcom/humble-steam-key-redeemer/",
    "source_branch": "main",
    "source_directory": "docs/source/",
    "light_css_variables": {
        "color-brand-primary": "#1b6ac9",
        "color-brand-content": "#1b6ac9",
    },
    "dark_css_variables": {
        "color-brand-primary": "#7cb7ff",
        "color-brand-content": "#7cb7ff",
    },
}
pygments_style = "friendly"
pygments_dark_style = "monokai"

# -- Extension settings ------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
napoleon_google_docstring = True
napoleon_numpy_docstring = False
# Render "Attributes:" as prose rather than as a second set of :py:attribute:
# entries, which would duplicate the ones autodoc already emits.
napoleon_use_ivar = True

myst_enable_extensions = ["colon_fence", "deflist", "linkify"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

ogp_site_url = "https://jonbogaty.com/humble-steam-key-redeemer/"
ogp_description_length = 200

nitpicky = False
