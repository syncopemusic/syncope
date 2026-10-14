from django import template
from functools import lru_cache

register = template.Library()

@lru_cache(maxsize=32)
def _parse_url_list(url_list_str):
    return {s.strip() for s in url_list_str.split(',')}

@register.filter
def url_in(url_name, url_list_str):
    return url_name in _parse_url_list(url_list_str)


@register.inclusion_tag("syncope/_breadcrumbs.html", takes_context=True)
def render_breadcrumbs(context):
    """Explicit `breadcrumbs` from the view win; otherwise derive the trail from the URL name."""
    from syncope.breadcrumbs import auto_breadcrumbs
    return {"breadcrumbs": context.get("breadcrumbs") or auto_breadcrumbs(context["request"])}
