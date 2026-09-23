from django import template
from django.template.defaultfilters import date as date_filter
from django.utils.html import format_html

register = template.Library()

_FALLBACKS = {
    'date': 'd M',
    'date-year': 'd M, Y',
    'date-dow': 'D d M',
    'time': 'H:i',
    'datetime': 'd M, Y, H:i',
    'datetime-dow-full': 'l d F, Y, H:i',
    'datetime-dow-short': 'D d M, Y, H:i',
}

@register.simple_tag
def dt(value, fmt, css_class=''):
    if not value:
        return ''
    class_attr = format_html(' class="{}"', css_class) if css_class else ''
    return format_html(
        '<span{} data-dt="{}" data-dt-fmt="{}">{}</span>',
        class_attr, date_filter(value, 'c'), fmt, date_filter(value, _FALLBACKS[fmt]),
    )

@register.simple_tag
def event_label(event):
    """Plain-text event label for headings/<title>: name if set, else "type (date)"."""
    if not event:
        return ''
    if event.name:
        return event.name
    when = date_filter(event.started_at, _FALLBACKS['date-year']) if event.started_at else 'no date yet'
    return f"{event.event_type} ({when})"
