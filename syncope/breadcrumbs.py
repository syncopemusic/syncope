from django.urls import reverse
from syncope.utils import add_query_param

ORIGIN_PARAM = "origin"

EVENT_ORIGINS = {
    "attendance": ("Attendance", "syncope:attendance"),
    "events": ("Events", "syncope:event_list"),
}
DEFAULT_EVENT_ORIGIN = "events"


def with_origin(url, origin_key):
    return add_query_param(url, {ORIGIN_PARAM: origin_key})


def get_origin_key(request):
    origin_key = request.GET.get(ORIGIN_PARAM, DEFAULT_EVENT_ORIGIN)
    return origin_key if origin_key in EVENT_ORIGINS else DEFAULT_EVENT_ORIGIN


def origin_root_crumb(request, username):
    """The Attendance/Events root crumb. Returns (crumb, origin_key)."""
    origin_key = get_origin_key(request)
    origin_label, origin_url_name = EVENT_ORIGINS[origin_key]
    return {"label": origin_label, "url": reverse(origin_url_name, kwargs={"username": username})}, origin_key


def event_breadcrumbs(request, username, event, current_label=None):
    """Attendance/Events > event name > [current subpage label].

    Returns (breadcrumbs, origin_key). origin_key is what templates append as
    ?origin=<key> on same-flow links (edit links, the save_draft_and_go 'next'
    target, etc.) so the trail survives further navigation.
    """
    root, origin_key = origin_root_crumb(request, username)
    event_url = reverse("syncope:event_detail", kwargs={"username": username, "pk": event.pk})
    crumbs = [
        root,
        {"label": event.name, "url": with_origin(event_url, origin_key) if current_label else None},
    ]
    if current_label:
        crumbs.append({"label": current_label, "url": None})
    return crumbs, origin_key


def event_song_breadcrumbs(request, username, event, song, current_label=None):
    """Attendance/Events > event name > song title > [current label].

    Used when something below a song (e.g. its composer/poet/etc.) was reached
    via a song that was itself reached via an event.
    """
    root, origin_key = origin_root_crumb(request, username)
    event_url = reverse("syncope:event_detail", kwargs={"username": username, "pk": event.pk})
    song_url = reverse("syncope:song_detail", kwargs={"username": username, "pk": song.pk})
    song_url = with_origin(add_query_param(song_url, {"from_event": event.pk}), origin_key)
    crumbs = [
        root,
        {"label": event.name, "url": with_origin(event_url, origin_key)},
        {"label": song.title, "url": song_url if current_label else None},
    ]
    if current_label:
        crumbs.append({"label": current_label, "url": None})
    return crumbs, origin_key
