from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name):
    """Inline SVG icon from the sprite in _icons.html (decorative; keep a title on the parent for meaning)."""
    return format_html('<svg class="icon" aria-hidden="true"><use href="#i-{}"/></svg>', name)
