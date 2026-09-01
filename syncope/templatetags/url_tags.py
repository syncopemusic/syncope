from django import template
from functools import lru_cache

register = template.Library()

@lru_cache(maxsize=32)
def _parse_url_list(url_list_str):
    return {s.strip() for s in url_list_str.split(',')}

@register.filter
def url_in(url_name, url_list_str):
    return url_name in _parse_url_list(url_list_str)
