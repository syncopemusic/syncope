from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_block_tag(takes_context=True)
def filter_panel(context, content, form_id):
    """Closed filter panel (same markup as the members page) around the filter rows; badge shows the active filter count."""
    total = len(context.get('filters') or {})
    return format_html(
        '<details class="filter-panel"><summary>'
        '<span>Filter <span class="filter-total" id="filter-total">{}</span></span>'
        '<svg class="filter-toggle-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>'
        '</summary><form method="get" class="filter-form" id="{}"><input type="hidden" name="f" value="1">{}</form></details>',
        f'({total})' if total else '', form_id, content,
    )
