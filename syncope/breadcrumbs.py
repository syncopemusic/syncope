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


PROJECT_ORIGIN_PREFIX = "project-"


def _origin_project(request, username):
    """The Project an `origin=project-<pk>` trail starts from (owner-scoped), else None."""
    origin = request.GET.get(ORIGIN_PARAM, "")
    pk = origin[len(PROJECT_ORIGIN_PREFIX):] if origin.startswith(PROJECT_ORIGIN_PREFIX) else ""
    if not pk.isdigit():
        return None
    from syncope.models import Project
    return Project.objects.filter(pk=pk, user__username=username).first()


def origin_root_crumbs(request, username):
    """Root crumbs of an event/song/person trail: [Attendance|Events] or [Projects, <project>].

    Returns (crumbs, origin_key). The origin is the one place a trail is allowed to start
    from; pages reached *from* a person (their projects, songs, ...) carry no origin, so
    the trail resets there instead of circling back through the same entities.
    """
    project = _origin_project(request, username)
    if project:
        crumbs = [
            {"label": "Projects", "url": reverse("syncope:project_list", kwargs={"username": username})},
            {"label": project.title, "url": reverse("syncope:project_detail", kwargs={"username": username, "pk": project.pk})},
        ]
        return crumbs, f"{PROJECT_ORIGIN_PREFIX}{project.pk}"
    origin_key = request.GET.get(ORIGIN_PARAM, DEFAULT_EVENT_ORIGIN)
    if origin_key not in EVENT_ORIGINS:
        origin_key = DEFAULT_EVENT_ORIGIN
    label, url_name = EVENT_ORIGINS[origin_key]
    return [{"label": label, "url": reverse(url_name, kwargs={"username": username})}], origin_key


def project_origin_breadcrumbs(request, username, current_label, *middle):
    """[Projects, <project>, *middle, current] when the page was reached from a project, else None."""
    roots, origin_key = origin_root_crumbs(request, username)
    if not origin_key.startswith(PROJECT_ORIGIN_PREFIX):
        return None
    return [*roots, *middle, {"label": current_label, "url": None}], origin_key


def event_breadcrumbs(request, username, event, current_label=None):
    """Attendance/Events > event name > [current subpage label].

    Returns (breadcrumbs, origin_key). origin_key is what templates append as
    ?origin=<key> on same-flow links (edit links, the save_draft_and_go 'next'
    target, etc.) so the trail survives further navigation.
    """
    roots, origin_key = origin_root_crumbs(request, username)
    event_url = reverse("syncope:event_detail", kwargs={"username": username, "pk": event.pk})
    crumbs = [
        *roots,
        {"label": event.name or str(event.event_type), "url": with_origin(event_url, origin_key) if current_label else None},
    ]
    if current_label:
        crumbs.append({"label": current_label, "url": None})
    return crumbs, origin_key


def event_song_breadcrumbs(request, username, event, song, current_label=None):
    """Attendance/Events > event name > song title > [current label].

    Used when something below a song (e.g. its composer/poet/etc.) was reached
    via a song that was itself reached via an event.
    """
    roots, origin_key = origin_root_crumbs(request, username)
    event_url = reverse("syncope:event_detail", kwargs={"username": username, "pk": event.pk})
    song_url = reverse("syncope:song_detail", kwargs={"username": username, "pk": song.pk})
    song_url = with_origin(add_query_param(song_url, {"from_event": event.pk}), origin_key)
    crumbs = [
        *roots,
        {"label": event.name or str(event.event_type), "url": with_origin(event_url, origin_key)},
        {"label": song.title, "url": song_url if current_label else None},
    ]
    if current_label:
        crumbs.append({"label": current_label, "url": None})
    return crumbs, origin_key


# --- Automatic "Section > object > page" trails -----------------------------------------
# Pages whose view builds `breadcrumbs` itself (events, song/member detail) skip this; every
# other page is described by one PAGES row and gets its trail from the `render_breadcrumbs`
# template tag, so the section names/labels stay in one place.

_MEMBER_SECTIONS = {
    "composers": ("Composers", "org_composers_list", "org_composer_detail"),
    "poets": ("Poets", "org_poets_list", "org_poet_detail"),
    "arrangers": ("Arrangers", "org_arrangers_list", "org_arranger_detail"),
    "translators": ("Translators", "org_translators_list", "org_translator_detail"),
}

# section -> (label, list url name, detail url name, object label fn(pk) or None)
def _model_label(model_name, attr=None):
    def label(pk):
        from syncope import models
        obj = getattr(models, model_name).objects.filter(pk=pk).first()
        return (getattr(obj, attr) if attr else str(obj)) if obj else None
    return label


SECTIONS = {
    "profile": ("Profile", "profile_detail", None, None),
    "invitations": ("Invitations", "invitation_list", "invitation_detail", lambda pk: f"Invitation #{pk}"),
    "events": ("Events", "event_list", "event_detail", None),
    "attendance": ("Attendance", "attendance", None, None),
    "songs": ("Songs", "song_list", "song_detail", _model_label("Song", "title")),
    "projects": ("Projects", "project_list", "project_detail", _model_label("Project", "title")),
    "polls": ("Polls", "poll_list", "poll_detail", _model_label("Poll", "title")),
    "members": ("Members", "org_member_list", "org_member_detail", _model_label("Person")),
    **{key: (label, lst, det, _model_label("Person")) for key, (label, lst, det) in _MEMBER_SECTIONS.items()},
}

# url name -> (section, kind, label). kinds: list = section page itself, page = section > label,
# detail = section > object, sub = section > object > label.
PAGES = {
    "profile_detail": ("profile", "list", None),
    "person_update": ("profile", "page", "Details"),
    "profile_resources": ("profile", "page", "Resources"),
    "profile_account": ("profile", "page", "Username & password"),
    "invitation_list": ("invitations", "list", None),
    "invitation_new": ("invitations", "page", "New"),
    "invitation_detail": ("invitations", "detail", None),
    "event_list": ("events", "list", None),
    "event_new": ("events", "page", "New"),
    "attendance": ("attendance", "list", None),
    "song_list": ("songs", "list", None),
    "song_new": ("songs", "page", "New"),
    "song_meta_edit": ("songs", "sub", "Details"),
    "song_lyrics_edit": ("songs", "sub", "Lyrics"),
    "song_resources_edit": ("songs", "sub", "Resources"),
    "song_quotes": ("songs", "sub", "Quotes"),
    "song_events_edit": ("songs", "sub", "Events"),
    "song_delete": ("songs", "sub", "Delete"),
    "project_list": ("projects", "list", None),
    "project_new": ("projects", "page", "New"),
    "project_detail": ("projects", "detail", None),
    "project_meta_edit": ("projects", "sub", "Details"),
    "project_resources_edit": ("projects", "sub", "Resources"),
    "project_events_edit": ("projects", "sub", "Events"),
    "project_songs_edit": ("projects", "sub", "Songs"),
    "project_participants_edit": ("projects", "sub", "Participants"),
    "project_delete": ("projects", "sub", "Delete"),
    "poll_list": ("polls", "list", None),
    "poll_new": ("polls", "page", "New"),
    "poll_detail": ("polls", "detail", None),
    "poll_update": ("polls", "sub", "Edit"),
    "poll_persons": ("polls", "sub", "Persons"),
    "poll_events": ("polls", "sub", "Dates"),
    "poll_event_update": ("polls", "sub", "Edit date"),
    "poll_attendance": ("polls", "sub", "Attendance"),
    "poll_person_attendance": ("polls", "sub", "Attendance"),
    "poll_delete": ("polls", "sub", "Delete"),
    "org_member_list": ("members", "list", None),
    "org_member_list_all": ("members", "list", None),
    "org_member_new": ("members", "page", "New"),
    "org_member_new_member": ("members", "page", "New"),
    "org_member_edit": ("members", "sub", "Edit"),
    "org_member_delete": ("members", "sub", "Delete"),
    "person_resources_edit": ("members", "sub", "Resources"),
}
for _key in _MEMBER_SECTIONS:
    _singular = _key[:-1]
    PAGES.update({
        f"org_{_key}_list": (_key, "list", None),
        f"org_member_new_{_singular}": (_key, "page", "New"),
        f"org_{_singular}_edit": (_key, "sub", "Edit"),
        f"org_{_singular}_delete": (_key, "sub", "Delete"),
    })


def section_crumb(request, username, section_key):
    """The section's root crumb (list link). Own contacts are 'Contacts' and live under 'all'."""
    label, list_name, _, _ = SECTIONS[section_key]
    if section_key == "members" and request.user.username == username:
        label, list_name = "Contacts", "org_member_list_all"
    return {"label": label, "url": reverse(f"syncope:{list_name}", kwargs={"username": username})}


def auto_breadcrumbs(request):
    match = request.resolver_match
    spec = PAGES.get(match.url_name) if match else None
    if not spec:
        return []
    section_key, kind, page_label = spec
    username = match.kwargs.get("username")
    root = section_crumb(request, username, section_key)
    if kind == "list":
        return [{"label": page_label or root["label"], "url": None}]
    if kind == "page":
        return [root, {"label": page_label, "url": None}]
    _, _, detail_name, label_fn = SECTIONS[section_key]
    pk = match.kwargs.get("pk")
    obj_label = label_fn(pk) if label_fn else None
    if not obj_label:
        return [root, {"label": page_label, "url": None}] if kind == "sub" else [root]
    if kind == "detail":
        return [root, {"label": obj_label, "url": None}]
    detail_url = reverse(f"syncope:{detail_name}", kwargs={"username": username, "pk": pk})
    return [root, {"label": obj_label, "url": detail_url}, {"label": page_label, "url": None}]
