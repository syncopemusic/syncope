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
