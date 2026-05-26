import json
from functools import cache
from logging import getLogger
from pathlib import Path
from typing import Dict, List, Set, TypedDict, cast

from django.conf import settings
from django.template import Library
from django.templatetags.static import static
from django.utils.safestring import mark_safe

LOGGER = getLogger(__name__)

register = Library()

STATIC_URL = getattr(settings, "STATIC_URL")
VITE_FORCE_DEV = getattr(settings, "VITE_FORCE_DEV", False)
VITE_MANIFEST: Path | None = getattr(settings, "VITE_MANIFEST", None)
VITE_MANIFEST = Path(VITE_MANIFEST) if VITE_MANIFEST else None


class ManiFestEntry(TypedDict):
    file: str
    css: None | List[str]
    imports: None | List[str]


ManifestType = Dict[str, ManiFestEntry]

MANIFEST_CONTENTS: ManifestType | None = None
if VITE_MANIFEST and Path(VITE_MANIFEST).is_file():
    with open(VITE_MANIFEST) as f:
        MANIFEST_CONTENTS = json.load(f)


def make_script_tag(*, src: str, **attrs: str) -> str:
    """Construct an html script tag."""
    html_attrs = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"<script src={src} {html_attrs}></script>"


def make_style_tag(*, href: str, **attrs: str) -> str:
    """Construct an html link tag for styles."""
    html_attrs = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f'<link rel="stylesheet" href="{href}" {html_attrs} />'


def get_style_chunks(vite_path: str) -> Set[str]:
    """Recursively get all style chunks a JS chunk imports."""
    entry = cast(ManifestType, MANIFEST_CONTENTS)[vite_path]
    css_files = set(entry.get("css") or tuple())
    # If a JS chunk imports another chunk we need the imported chunks style(s) as well.
    for imp_vite_path in entry.get("imports") or tuple():
        css_files |= get_style_chunks(imp_vite_path)
    return css_files


@register.simple_tag
@cache
@mark_safe
def vite(path: str) -> str:
    tag_type = "module" if path.endswith(".ts") else "application/javascript"
    # Force dev or no manifest
    if VITE_FORCE_DEV is True or MANIFEST_CONTENTS is None:
        return make_script_tag(src=static(f"/vite/{path}"), type=tag_type)

    descriptor = MANIFEST_CONTENTS.get(str(path))
    if descriptor is None:
        LOGGER.warning(f"No Manifest entry found for {path}")
        return make_script_tag(src=static(str(path)), type=tag_type)

    css_chunks = get_style_chunks(path)
    style_tags = (make_style_tag(href=static(stylesheet)) for stylesheet in css_chunks)
    path = descriptor["file"]
    script_tag = make_script_tag(src=static(path), type=tag_type)

    return "".join(style_tags) + script_tag
