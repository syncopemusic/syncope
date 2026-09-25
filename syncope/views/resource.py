from itertools import zip_longest

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import View

from syncope.breadcrumbs import with_origin, DEFAULT_EVENT_ORIGIN
from syncope.models import (
    CustomUser, Role, Song, Event, Project, Person,
    SongResource, EventResource, ProjectResource, PersonResource, EventSongResource, Resource,
)
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list


def _song_can_edit(request_user, owner_user, song):
    return AccessControl.can_manage_song(request_user, song)


def _event_can_edit(request_user, owner_user, event):
    from syncope.views.event import is_event_admin
    return is_event_admin(request_user, owner_user)


def _project_can_edit(request_user, owner_user, project):
    return AccessControl.can_edit_project(request_user, owner_user.username)


def _person_can_edit(request_user, owner_user, person):
    is_admin = AccessControl.get_org_roles(request_user, owner_user.username).filter(id=Role.ADMIN).exists()
    return is_admin or person.user == request_user


def _event_song_resource_rows(event_songs, related_type, related_attr):
    """Read-only rows for the EventSongResources of these event-song setlist entries."""
    esrs = list(EventSongResource.objects.filter(event_song__in=event_songs).select_related(
        'resource', f'event_song__{related_attr}'
    ).order_by('order'))
    rows = resource_icon_list(esrs)
    for row, esr in zip(rows, esrs):
        row['related_type'] = related_type
        row['related_obj'] = getattr(esr.event_song, related_attr)
    return rows


def song_related_resource_rows(song):
    """Resources attached to this song within a specific event's setlist (read-only here)."""
    return _event_song_resource_rows(song.eventsong_set.all(), 'event', 'event')


def event_related_resource_rows(event):
    """Resources attached to this event's songs within its setlist (read-only here)."""
    return _event_song_resource_rows(event.eventsong_set.all(), 'song', 'song')


def song_setlist_options(song):
    """(EventSong.pk, label) pairs for 'attach this new resource within event X's setlist' - Song side."""
    return [
        {'pk': es.pk, 'label': str(es.event)}
        for es in song.eventsong_set.select_related('event').order_by('-event__started_at')
    ]


def event_setlist_options(event):
    """(EventSong.pk, label) pairs for 'attach this new resource to song X's setlist entry' - Event side."""
    return [
        {'pk': es.pk, 'label': es.song.title}
        for es in event.eventsong_set.select_related('song').order_by('order')
    ]


KIND_CONFIG = {
    'song': {
        'resource_model': SongResource,
        'fk_name': 'song',
        'related_name': 'song_resource',
        'get_owner': lambda owner_user, pk: get_object_or_404(Song, pk=pk, user=owner_user),
        'can_edit': _song_can_edit,
        'detail_url': 'song_detail',
        'related_rows': song_related_resource_rows,
        'related_column_label': 'Event',
        'setlist_options': song_setlist_options,
    },
    'event': {
        'resource_model': EventResource,
        'fk_name': 'event',
        'related_name': 'event_resource',
        'get_owner': lambda owner_user, pk: get_object_or_404(Event, pk=pk, user=owner_user),
        'can_edit': _event_can_edit,
        'detail_url': 'event_detail',
        'related_rows': event_related_resource_rows,
        'related_column_label': 'Song',
        'setlist_options': event_setlist_options,
    },
    'project': {
        'resource_model': ProjectResource,
        'fk_name': 'project',
        'related_name': 'project_resource',
        'get_owner': lambda owner_user, pk: get_object_or_404(Project, pk=pk, user=owner_user),
        'can_edit': _project_can_edit,
        'detail_url': 'project_detail',
        'related_rows': None,
        'related_column_label': None,
        'setlist_options': None,
    },
    'person': {
        'resource_model': PersonResource,
        'fk_name': 'person',
        'related_name': 'person_resource',
        'get_owner': lambda owner_user, pk: get_object_or_404(Person, pk=pk),
        'can_edit': _person_can_edit,
        'detail_url': 'org_member_detail',
        'related_rows': None,
        'related_column_label': None,
        'setlist_options': None,
    },
}


@method_decorator(login_required, name='dispatch')
class ResourcesEditView(View):
    """Add/remove/reorder resources for a Song, Event, Project, or Person.

    One view + one template for all four owner kinds - their resource junction
    models (SongResource/EventResource/ProjectResource/PersonResource) are all
    identically shaped (owner FK + resource FK + order).
    """
    template_name = 'syncope/resources_edit.html'
    kind = None

    def _setup(self, username, pk):
        self.cfg = KIND_CONFIG[self.kind]
        self.owner_user = get_object_or_404(CustomUser, username=username)
        self.owner = self.cfg['get_owner'](self.owner_user, pk)

    def _owner_detail_url(self, request, username):
        """Where Return/Save go back to - for an Event, preserves ?origin= (Attendance vs
        Events root) the same way event_meta_edit/event_songs_edit/event_attendance_edit do."""
        url = reverse(f'syncope:{self.cfg["detail_url"]}', kwargs={'username': username, 'pk': self.owner.pk})
        if self.kind == 'event':
            url = with_origin(url, request.GET.get('origin', DEFAULT_EVENT_ORIGIN))
        return url

    def get(self, request, username, pk):
        self._setup(username, pk)
        if not self.cfg['can_edit'](request.user, self.owner_user, self.owner):
            return HttpResponseForbidden("You don't have permission to edit these resources.")

        own_manager = getattr(self.owner, self.cfg['related_name'])
        own_rows = resource_icon_list(own_manager.select_related('resource').order_by('order'))
        related_rows = self.cfg['related_rows'](self.owner) if self.cfg['related_rows'] else []
        setlist_options = self.cfg['setlist_options'](self.owner) if self.cfg['setlist_options'] else []

        return render(request, self.template_name, {
            'owner': self.owner,
            'own_rows': own_rows,
            'related_rows': related_rows,
            'related_column_label': self.cfg['related_column_label'],
            'setlist_options': setlist_options,
            'url_username': username,
            'owner_detail_url': self._owner_detail_url(request, username),
        })

    def post(self, request, username, pk):
        self._setup(username, pk)
        if not self.cfg['can_edit'](request.user, self.owner_user, self.owner):
            return HttpResponseForbidden("You don't have permission to edit these resources.")

        own_manager = getattr(self.owner, self.cfg['related_name'])
        order_tokens = [t for t in request.POST.get('order', '').split(',') if t]
        remove_ids = {
            int(key[len('remove_'):]) for key in request.POST
            if key.startswith('remove_') and request.POST[key] == '1'
        }
        new_urls = request.POST.getlist('new_url')
        new_descriptions = request.POST.getlist('new_description')
        new_setlist_ids = request.POST.getlist('new_setlist_id')

        with transaction.atomic():
            if remove_ids:
                own_manager.filter(pk__in=remove_ids).delete()

            # (resource_id, EventSong.pk_or_None) per staged addition, in submission order.
            # The EventSong pk always comes from `setlist_options` (Song side: events this song
            # is already on; Event side: songs already in this event's setlist), so it's always
            # an existing setlist entry - no lookup/create needed to resolve it.
            new_entries = []
            for url, description, setlist_id in zip_longest(new_urls, new_descriptions, new_setlist_ids, fillvalue=''):
                url = url.strip()
                if not url:
                    continue
                resource, created = Resource.objects.get_or_create(
                    url=url, defaults={'owner': self.owner_user, 'description': description}
                )
                if not created and description:
                    resource.description = description
                    resource.save(update_fields=['description'])
                new_entries.append((resource.pk, setlist_id.strip() or None))

            existing_rows = {row.pk: row for row in own_manager.all()}
            order = 1
            new_idx = 0
            for token in order_tokens:
                if token.startswith('r'):
                    row = existing_rows.get(int(token[1:]))
                    if row:
                        row.order = order
                        row.save(update_fields=['order'])
                        order += 1
                elif token.startswith('n'):
                    if new_idx < len(new_entries):
                        resource_id, setlist_id = new_entries[new_idx]
                        if setlist_id:
                            EventSongResource.objects.create(event_song_id=setlist_id, resource_id=resource_id, order=order)
                        else:
                            self.cfg['resource_model'].objects.create(**{
                                self.cfg['fk_name']: self.owner,
                                'resource_id': resource_id,
                                'order': order,
                            })
                        order += 1
                    new_idx += 1

        messages.success(request, "Resources updated successfully!")
        edit_url = reverse(f'syncope:{self.kind}_resources_edit', kwargs={'username': username, 'pk': pk})
        if self.kind == 'event':
            edit_url = with_origin(edit_url, request.GET.get('origin', DEFAULT_EVENT_ORIGIN))
        return redirect(edit_url)
