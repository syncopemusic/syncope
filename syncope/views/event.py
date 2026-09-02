from functools import wraps
from django.http import HttpResponseForbidden, HttpResponseBadRequest, HttpResponse
from django.shortcuts import  get_object_or_404, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView,  DetailView, View
from django.views.generic.edit import DeleteView
from django.db.models import Max, Min, Case, When, Value, IntegerField, Prefetch
from django.shortcuts import redirect
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.http import url_has_allowed_host_and_scheme
from syncope.models import CustomUser, Person, Role
from syncope.models import Event, EventSong, Attendance, AttendanceType, EventResource, EventSongResource, Resource, SongResource
from syncope.forms import EventForm, EventSongFormSet, AttendanceFormSet, AddAttendanceForm
from syncope.forms import AddSongToEventForm, EventResourceFormSet, EventSongResourceFormSet
from syncope.views.drafts import DraftMixin, clear_draft
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list, add_query_param


def is_event_admin(user, org_user):
    """True if user can create/edit/delete org_user's events (ADMIN role, or the org's own account)."""
    return user == org_user or AccessControl.can_add_event(
        user, org_user
    ).filter(person__roles__id=Role.ADMIN).exists()


def can_view_event_content(user, org_user):
    """True if user can view an event's songs/meta content (ADMIN/MEMBER/SUPPORTER, or the org's own account)."""
    return user == org_user or AccessControl.can_view_event_content(user, org_user).exists()


def can_view_event_attendance(user, org_user):
    """True if user can view an event's attendance (ADMIN/MEMBER, or the org's own account)."""
    return user == org_user or AccessControl.can_edit_event(user, org_user).exists()


def _save_resource_formset(existing_manager, resource_model, owner_kwargs, resource_formset, owner_user):
    """Shared save logic for EventResourceFormSet / EventSongResourceFormSet."""
    existing_manager.all().delete()
    valid_forms = [
        f for f in resource_formset.forms
        if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
    ]
    for idx, f in enumerate(valid_forms):
        url = f.cleaned_data['url']
        description = f.cleaned_data.get('description', '')
        resource, created = Resource.objects.get_or_create(
            url=url,
            defaults={'owner': owner_user, 'description': description}
        )
        if not created:
            resource.description = description
            resource.save(update_fields=['description'])
        resource_model.objects.create(resource=resource, order=idx + 1, **owner_kwargs)


def save_event_resources(event, resource_formset, owner_user):
    """Persist an EventResourceFormSet against `event`."""
    _save_resource_formset(event.event_resource, EventResource, {'event': event}, resource_formset, owner_user)


def save_event_song_resources(event_song, resource_formset, owner_user):
    """Persist an EventSongResourceFormSet against `event_song`."""
    _save_resource_formset(
        event_song.event_song_resource, EventSongResource, {'event_song': event_song}, resource_formset, owner_user
    )


def event_admin_required(view_func):
    """Resolve org_user/event from the URL and 403 unless the viewer can admin this event.

    Wraps a view of the form `def foo(request, username, pk, **rest)` into one that
    receives `org_user`/`event` directly instead of re-deriving them itself.
    """
    @wraps(view_func)
    def wrapper(request, username, pk, **kwargs):
        org_user = get_object_or_404(CustomUser, username=username)
        event = get_object_or_404(Event, pk=pk, user=org_user)
        if not is_event_admin(request.user, org_user):
            return HttpResponseForbidden("Only admins can make this change.")
        return view_func(request, org_user=org_user, event=event, **kwargs)
    return wrapper


def get_ordered_attendance_queryset(event):
    """Attendance for `event`, ordered by voice/instrument section then name."""
    return event.attendance_set.select_related('person', 'attendance_type').annotate(
        voice_order=Min('person__singer__voice__id'),
        instrument_order=Min('person__instrumentalist__instrument__id'),
    ).order_by(
        Case(
            When(voice_order__isnull=False, then=Value(0)),
            When(instrument_order__isnull=False, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
        'voice_order',
        'instrument_order',
        'person__last_name',
        'person__first_name',
    )


def reorder_event_song(event, song_pk, direction):
    """Move one EventSong up/down within `event`'s ordering. Returns True if a move happened."""
    songs = list(event.eventsong_set.all().order_by('order'))
    if not songs:
        return False

    song_idx = next((idx for idx, song in enumerate(songs) if song.pk == song_pk), None)
    if song_idx is None:
        return False

    moved = False
    if direction == 'up_one' and song_idx > 0:
        songs[song_idx], songs[song_idx - 1] = songs[song_idx - 1], songs[song_idx]
        moved = True
    elif direction == 'up_all' and song_idx > 0:
        songs.insert(0, songs.pop(song_idx))
        moved = True
    elif direction == 'down_one' and song_idx < len(songs) - 1:
        songs[song_idx], songs[song_idx + 1] = songs[song_idx + 1], songs[song_idx]
        moved = True
    elif direction == 'down_all' and song_idx < len(songs) - 1:
        songs.append(songs.pop(song_idx))
        moved = True

    if not moved:
        return False

    with transaction.atomic():
        for idx, song in enumerate(songs):
            song.order = -(idx + 1)
            song.save(update_fields=['order'])
        for idx, song in enumerate(songs):
            song.order = idx + 1
            song.save(update_fields=['order'])
    return True


class SelectPersonInitialMixin:
    person_preset_fields = []
    person_preset_map = {}

    def _get_initial_with_presets(self):
        initial = {}
        if self.person_preset_map:
            for query_key, form_key in self.person_preset_map.items():
                pk = self.request.GET.get(query_key)
                if pk:
                    initial[form_key] = pk
        else:
            for field in self.person_preset_fields:
                pk = self.request.GET.get(f'select_{field}')
                if pk:
                    initial[field] = pk
        return initial


@method_decorator(login_required, name='dispatch')
class EventCreateView(DraftMixin, CreateView):
    """Step 1: Create event with basic info only"""
    model = Event
    form_class = EventForm
    template_name = 'syncope/event_form.html'

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")

        if url_username:
            self.customuser = get_object_or_404(
                CustomUser,
                username=url_username
            )
            # Allow if viewing own account OR if has member access
            if request.user != self.customuser:
                member_queryset = AccessControl.can_add_event(
                    request.user,
                    self.customuser
                )
                if not member_queryset.exists():
                    return HttpResponseForbidden()

        else:
            self.customuser = None


        return super().dispatch(request, *args, **kwargs)


    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # kwargs['username'] = self.request.user
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Name and most other fields are optional (see EventForm); a start date is the one
        # thing we actually need up front to auto-generate a name and seed attendance.
        form.fields['started_at'].required = True
        return form

    def get_initial(self):
        initial = super().get_initial()
        project_pk = self.request.GET.get('project')
        if project_pk:
            initial['project'] = project_pk
        return initial

    def form_valid(self, form):
        user_to_assign = self.customuser if self.customuser else self.request.user
        form.instance.user = user_to_assign
        response = super().form_valid(form)

        # Initialize attendance records for all active performers at the event date
        event = self.object
        event_date = event.started_at or timezone.now()
        unknown_type = AttendanceType.objects.get(pk=AttendanceType.TBD)
        members = Person.objects.active_performers(user_to_assign, event_date)
        Attendance.objects.bulk_create(
            [Attendance(event=event, person=m, attendance_type=unknown_type) for m in members],
            ignore_conflicts=True,
        )
        return response



    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next', '')
        draft_key = self.request.GET.get('draft_key')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            if self.object.project_id:
                if draft_key:
                    next_url = add_query_param(next_url, {'draft_key': draft_key})
                return next_url
            return add_query_param(next_url, {'select_event': self.object.pk})
        return reverse_lazy("syncope:event_detail", kwargs={
            "username": self.customuser.username,
            "pk": self.object.pk
        })

@method_decorator(login_required, name='dispatch')
class EventUpdateView(DraftMixin, SelectPersonInitialMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = 'syncope/event_update.html'
    person_preset_map = {'select_person': 'person', 'select_song': 'song'}

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")
        self.customuser = get_object_or_404(CustomUser, username=url_username) if url_username else request.user

        if request.user != self.customuser:
            self.is_admin = AccessControl.can_add_event(
                request.user, self.customuser
            ).filter(person__roles__id=Role.ADMIN).exists()

            has_access = self.is_admin or AccessControl.can_edit_event(request.user, self.customuser).exists()
            if not has_access:
                return HttpResponseForbidden("You don't have permission to access this page.")

            if request.method == 'POST' and not self.is_admin:
                return HttpResponseForbidden("Only admins can save event changes.")
        else:
            self.is_admin = True

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.customuser
        return kwargs

    def post(self, request, *args, **kwargs):
        """Handle reorder actions before form validation."""
        if request.POST.get('reorder'):
            self.object = self.get_object()
            self._reorder_songs_db(self.object)
            # Always redirect after reorder, don't process form
            event_update_url = reverse('syncope:event_update', kwargs={
                'username': self.kwargs['username'],
                'pk': self.object.pk,
            })
            return redirect(event_update_url)
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        """Return only events belonging to the organization/user from URL."""
        return Event.objects.filter(
            user=self.customuser
        ).select_related('user', 'event_type').prefetch_related(
            'eventsong_set__song',
            'attendance_set__person'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        event_date = event.started_at or timezone.now()

        members = Person.objects.active_performers(
            self.customuser, event_date
        ).select_related('user').prefetch_related('roles')

        if not hasattr(self, '_song_formset'):
            attendance_qs = get_ordered_attendance_queryset(event)
            song_qs = event.eventsong_set.all().order_by('order')
            if self.request.POST:
                self._song_formset = EventSongFormSet(
                    self.request.POST,
                    instance=event,
                    queryset=song_qs,
                )
                self._attendance_formset = AttendanceFormSet(
                    self.request.POST,
                    instance=event,
                    queryset=attendance_qs,
                    form_kwargs={'person_queryset': members},
                )
                self._resource_formset = EventResourceFormSet(
                    self.request.POST,
                    instance=event,
                    user=self.customuser,
                )
            else:
                self._song_formset = EventSongFormSet(
                    instance=event,
                    queryset=song_qs,
                )
                self._attendance_formset = AttendanceFormSet(
                    instance=event,
                    queryset=attendance_qs,
                    form_kwargs={'person_queryset': members},
                )
                self._resource_formset = EventResourceFormSet(
                    instance=event,
                    user=self.customuser,
                )

            # Build per-song resource formsets keyed by EventSong PK
            self._song_resource_formsets_map = {}
            for eventsong in song_qs:
                if self.request.POST:
                    formset = EventSongResourceFormSet(
                        self.request.POST, instance=eventsong,
                        user=self.customuser, prefix=f"esresource_{eventsong.pk}",
                    )
                else:
                    formset = EventSongResourceFormSet(
                        instance=eventsong,
                        user=self.customuser, prefix=f"esresource_{eventsong.pk}",
                    )
                self._song_resource_formsets_map[eventsong.pk] = formset

        search_q = self.request.GET.get('q', '')
        song_search_q = self.request.GET.get('song_q', '')

        context['song_formset'] = self._song_formset
        context['song_formset_with_resources'] = [
            (form, self._song_resource_formsets_map.get(form.instance.pk))
            for form in self._song_formset.forms
        ]
        context['attendance_formset'] = self._attendance_formset
        context['resource_formset'] = self._resource_formset
        context['attendance_types'] = AttendanceType.objects.all()
        context['url_username'] = self.kwargs.get('username')
        context['is_admin'] = self.is_admin
        context['admin_override'] = self.request.GET.get('admin_override') == 'true' and self.is_admin
        context['search_q'] = search_q
        context['song_search_q'] = song_search_q
        context['add_song_url'] = reverse('syncope:event_new_song', kwargs={
            'username': self.kwargs.get('username'), 'pk': event.pk,
        })
        context['add_participant_url'] = reverse('syncope:event_new_attendance', kwargs={
            'username': self.kwargs.get('username'), 'pk': event.pk,
        })
        presets = self._get_initial_with_presets()
        preset_initial = {k: presets[k] for k in ['person', 'song'] if k in presets}
        context['add_form'] = AddAttendanceForm(
            org_user=self.customuser,
            event=event,
            search_q=search_q,
            initial={'person': preset_initial.get('person')} if 'person' in preset_initial else {},
        ) if self.is_admin else None
        context['add_song_form'] = AddSongToEventForm(
            org_user=self.customuser,
            event=event,
            search_q=song_search_q,
            initial={'song': preset_initial.get('song')} if 'song' in preset_initial else {},
        ) if self.is_admin else None
        return context



    def _save_songs(self, event, song_formset):
        valid_forms = [
            f for f in song_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('song')
        ]
        valid_pks = {f.instance.pk for f in valid_forms if f.instance.pk}
        existing_pks = set(event.eventsong_set.values_list('pk', flat=True))
        pks_to_delete = existing_pks - valid_pks

        # Clean up children before deleting EventSong rows (PROTECT constraint)
        if pks_to_delete:
            EventSongResource.objects.filter(event_song_id__in=pks_to_delete).delete()
            EventSong.objects.filter(pk__in=pks_to_delete).delete()

        # Two-pass order update (avoids unique_order_per_event constraint violations)
        # Pass 1: temp negative orders
        for idx, f in enumerate(valid_forms):
            if f.instance.pk:
                EventSong.objects.filter(pk=f.instance.pk).update(order=-(idx + 1))
        # Pass 2: final positive orders + update fields
        for idx, f in enumerate(valid_forms):
            if f.instance.pk:
                EventSong.objects.filter(pk=f.instance.pk).update(
                    song=f.cleaned_data['song'],
                    encore=f.cleaned_data.get('encore') or False,
                    order=idx + 1,
                )

    def _save_resources(self, event, resource_formset):
        save_event_resources(event, resource_formset, self.customuser)

    def _save_song_resources(self, event_song, resource_formset):
        save_event_song_resources(event_song, resource_formset, self.customuser)

    def _reorder_songs_db(self, event):
        """Reorder songs in the database based on reorder button click."""
        reorder_value = self.request.POST.get('reorder', '').strip()
        if not reorder_value or not reorder_value.startswith('song_'):
            return
        try:
            parts = reorder_value.split('_')
            song_pk = int(parts[1])
            direction = '_'.join(parts[2:])  # handles "up_one", "up_all", "down_one", "down_all"
        except (ValueError, IndexError):
            return
        reorder_event_song(event, song_pk, direction)

    def form_valid(self, form):
        self.get_context_data()  # ensures formsets are built and cached on self
        admin_override = self.request.POST.get('admin_override') == 'true' and self.is_admin
        clear_draft(self.request, self.get_draft_key())

        if not self._song_formset.is_valid():
            messages.error(self.request, "Please fix errors in the songs section.")
            return self.form_invalid(form)

        if not self._attendance_formset.is_valid():
            messages.error(self.request, "Please fix errors in the attendance section.")
            return self.form_invalid(form)

        if not self._resource_formset.is_valid():
            messages.error(self.request, "Please fix errors in the resources section.")
            return self.form_invalid(form)

        for rs_formset in self._song_resource_formsets_map.values():
            if not rs_formset.is_valid():
                messages.error(self.request, "Please fix errors in song resources.")
                return self.form_invalid(form)

        with transaction.atomic():
            self.object = form.save()
            self._save_songs(self.object, self._song_formset)
            self._attendance_formset.instance = self.object
            self._attendance_formset.save()
            self._save_resources(self.object, self._resource_formset)
            for eventsong_pk, rs_formset in self._song_resource_formsets_map.items():
                try:
                    eventsong = EventSong.objects.get(pk=eventsong_pk)
                    self._save_song_resources(eventsong, rs_formset)
                except EventSong.DoesNotExist:
                    pass  # Song was deleted; its resources already cleaned up in _save_songs

        action = self.request.POST.get('action', 'save')
        event_update_url = reverse('syncope:event_update', kwargs={
            'username': self.kwargs['username'],
            'pk': self.object.pk,
        })

        if action == 'add_member':
            add_url = reverse('syncope:org_member_new', kwargs={
                'username': self.kwargs['username'],
            })
            return redirect(f'{add_url}?next={event_update_url}')

        if admin_override:
            messages.success(self.request, "Event updated successfully! (Admin override used)")
        else:
            messages.success(self.request, "Event updated successfully!")
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        if form.errors:
            messages.error(self.request, f"Event form errors: {form.errors}")
        messages.error(self.request, "There was an error updating the event. Please check the form below.")
        return super().form_invalid(form)

    def get_success_url(self):
        """Redirect to event detail page after successful update."""  # ADDED: Docstring
        return reverse_lazy('syncope:event_detail', kwargs={
            'username': self.kwargs.get('username'),
            'pk': self.object.pk
        })


@method_decorator(login_required, name="dispatch")
class EventListView(ListView):
    template_name = "syncope/event_list.html"
    context_object_name = "events"
    model = Event

    def _get_sort_field(self, default_sort='date'):
        """Extract and validate sort parameters from request."""
        sort = self.request.GET.get('sort', default_sort)
        reverse = self.request.GET.get('reverse', 'false') == 'true'

        # If no sort parameter provided, default to descending for backward compatibility
        if 'sort' not in self.request.GET:
            reverse = True

        sort_field_map = {
            'date': 'started_at',
            'type': 'event_type__name',
            'project': 'project__title',
        }
        sort_field = sort_field_map.get(sort, 'started_at')
        if reverse:
            sort_field = '-' + sort_field

        return sort_field, sort, reverse

    def get_queryset(self):
        url_username = self.kwargs.get("username")
        customuser = get_object_or_404(CustomUser, username=url_username)
        sort_field, _, _ = self._get_sort_field()
        return Event.objects.filter(user=customuser).order_by(sort_field).prefetch_related('event_resource__resource')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for event in context['events']:
            event.resource_icons = resource_icon_list(event.event_resource.all())
            event.resource_count = event.event_resource.count()
            event_song_resources = EventSongResource.objects.filter(
                event_song__event=event
            ).select_related('resource').order_by('order')
            event.event_song_resource_icons = resource_icon_list(event_song_resources)
            event.event_song_resource_count = event_song_resources.count()
        _, sort, reverse = self._get_sort_field()
        context['current_sort'] = sort
        context['reverse'] = reverse
        return context


@method_decorator(login_required, name='dispatch')
class EventDetailView(DetailView):
    model = Event
    template_name = 'syncope/event_detail.html'

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if not can_view_event_content(request.user, self.customuser):
            return HttpResponseForbidden("You don't have permission to view this event.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Event.objects.filter(user=self.customuser).prefetch_related(
            'attendance_set__person',
            'attendance_set__attendance_type',
            'eventsong_set__song__composer',
            'eventsong_set__song__song_resource__resource',
            'event_resource__resource',
            Prefetch(
                'eventsong_set__event_song_resource',
                queryset=EventSongResource.objects.select_related('resource').order_by('order')
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['attendances'] = get_ordered_attendance_queryset(self.object)
        context['is_admin'] = is_event_admin(self.request.user, self.customuser)
        context['can_view_attendance'] = can_view_event_attendance(self.request.user, self.customuser)
        context['event_resources'] = resource_icon_list(
            self.object.event_resource.select_related('resource').order_by('order')
        )

        # Build eventsongs with resource icons
        eventsongs = list(
            self.object.eventsong_set.order_by('order')
            .select_related('song', 'song__composer')
            .prefetch_related(
                Prefetch('event_song_resource',
                         queryset=EventSongResource.objects.select_related('resource').order_by('order'))
            )
        )
        for eventsong in eventsongs:
            song_has_resources = eventsong.song.song_resource.exists()
            if song_has_resources:
                song_icons = resource_icon_list(eventsong.song.song_resource.all())
                eventsong.resource_icons = song_icons[:1]
            else:
                eventsong.resource_icons = resource_icon_list(eventsong.event_song_resource.all())
        context['eventsongs'] = eventsongs

        # Build combined resource list: event resources first, then event-song resources
        all_event_resources = [
            {'url': r['url'], 'icon': r['icon'], 'desc': r['desc'], 'song': None, 'share_url': r.get('share_url')}
            for r in context['event_resources']
        ]
        for eventsong in eventsongs:
            for r in resource_icon_list(eventsong.event_song_resource.all()):
                r['song'] = eventsong.song
                all_event_resources.append(r)
        context['all_event_resources'] = all_event_resources

        return context




def _add_attendance_from_post(event, org_user, post_data):
    form = AddAttendanceForm(post_data, org_user=org_user, event=event, limit_results=False)
    if not form.is_valid():
        return None
    attendance, _ = Attendance.objects.get_or_create(
        event=event,
        person=form.cleaned_data['person'],
        defaults={'attendance_type': form.cleaned_data['attendance_type']},
    )
    return attendance


def _add_song_from_post(event, org_user, post_data):
    form = AddSongToEventForm(post_data, org_user=org_user, event=event, limit_results=False)
    if not form.is_valid():
        return None
    next_order = (event.eventsong_set.aggregate(Max('order'))['order__max'] or 0) + 1
    return EventSong.objects.create(event=event, song=form.cleaned_data['song'], order=next_order)


@require_POST
@login_required
def event_add_attendance(request, username, pk):
    """Legacy add-participant endpoint used by event_update.html; redirects back to the monolithic edit page."""
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=pk, user=org_user)

    if not is_event_admin(request.user, org_user):
        return HttpResponseForbidden("Only admins can add participants.")

    _add_attendance_from_post(event, org_user, request.POST)

    return redirect('syncope:event_update', username=username, pk=pk)


@login_required
def event_participant_search(request, username, pk):
    """Legacy participant search used by event_update.html."""
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=pk, user=org_user)

    if not is_event_admin(request.user, org_user):
        return HttpResponseForbidden("Only admins can search participants.")

    search_q = request.GET.get('q', '')
    add_form = AddAttendanceForm(org_user=org_user, event=event, search_q=search_q)
    return render(request, 'syncope/participant_search_results.html', {
        'add_form': add_form,
        'search_q': search_q,
        'object': event,
        'url_username': username,
        'add_participant_url': reverse('syncope:event_new_attendance', kwargs={'username': username, 'pk': pk}),
    })


@require_POST
@login_required
def event_add_song(request, username, pk):
    """Legacy add-song endpoint used by event_update.html; redirects back to the monolithic edit page."""
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=pk, user=org_user)

    if not is_event_admin(request.user, org_user):
        return HttpResponseForbidden("Only admins can add songs to events.")

    _add_song_from_post(event, org_user, request.POST)

    return redirect('syncope:event_update', username=username, pk=pk)


@login_required
def event_song_search(request, username, pk):
    """Legacy song search used by event_update.html."""
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=pk, user=org_user)

    if not is_event_admin(request.user, org_user):
        return HttpResponseForbidden("Only admins can search songs.")

    song_search_q = request.GET.get('song_q', '')
    add_song_form = AddSongToEventForm(org_user=org_user, event=event, search_q=song_search_q)
    return render(request, 'syncope/song_search_results.html', {
        'add_song_form': add_song_form,
        'song_search_q': song_search_q,
        'object': event,
        'url_username': username,
        'add_song_url': reverse('syncope:event_new_song', kwargs={'username': username, 'pk': pk}),
    })


# --- Songs subpage -----------------------------------------------------------------

@method_decorator(login_required, name='dispatch')
class EventSongsEditView(View):
    template_name = 'syncope/event_songs_edit.html'

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if not can_view_event_content(request.user, self.customuser):
            return HttpResponseForbidden("You don't have permission to access this page.")
        self.is_admin = is_event_admin(request.user, self.customuser)
        self.event = get_object_or_404(Event, pk=self.kwargs['pk'], user=self.customuser)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._get_context())

    def _get_context(self):
        event = self.event
        eventsongs = list(
            event.eventsong_set.select_related('song', 'song__composer').order_by('order').prefetch_related(
                Prefetch(
                    'event_song_resource',
                    queryset=EventSongResource.objects.select_related('resource').order_by('order')
                )
            )
        )
        eventsongs_with_resources = [
            (idx + 1, es, EventSongResourceFormSet(
                instance=es, queryset=es.event_song_resource.all(),
                user=self.customuser, prefix=f"esresource_{es.pk}",
            ))
            for idx, es in enumerate(eventsongs)
        ]
        search_q = self.request.GET.get('song_q', '')
        return {
            'object': event,
            'event': event,
            'eventsongs': eventsongs,
            'eventsongs_with_resources': eventsongs_with_resources,
            'url_username': self.kwargs.get('username'),
            'is_admin': self.is_admin,
            'song_search_q': search_q,
            'add_song_form': AddSongToEventForm(
                org_user=self.customuser, event=event, search_q=search_q
            ) if self.is_admin else None,
            'add_song_url': reverse('syncope:event_song_add', kwargs=self.kwargs),
        }


@require_POST
@login_required
@event_admin_required
def event_song_add(request, org_user, event):
    """AJAX add-song endpoint for the Songs subpage; returns the new row fragment."""
    eventsong = _add_song_from_post(event, org_user, request.POST)
    if eventsong is None:
        return HttpResponseBadRequest("Invalid selection.")

    song_count = event.eventsong_set.count()
    return render(request, 'syncope/_song_row.html', {
        'eventsong': eventsong,
        'index': song_count,
        'total': song_count,
        'url_username': org_user.username,
        'is_admin': True,
        'resource_formset': EventSongResourceFormSet(
            instance=eventsong, user=org_user, prefix=f"esresource_{eventsong.pk}"
        ),
    })


@login_required
@event_admin_required
def event_songs_search(request, org_user, event):
    """AJAX song search for the Songs subpage (points 'Add' at event_song_add, not the legacy endpoint)."""
    song_search_q = request.GET.get('song_q', '')
    add_song_form = AddSongToEventForm(org_user=org_user, event=event, search_q=song_search_q)
    return render(request, 'syncope/song_search_results.html', {
        'add_song_form': add_song_form,
        'song_search_q': song_search_q,
        'object': event,
        'url_username': org_user.username,
        'add_song_url': reverse('syncope:event_song_add', kwargs={'username': org_user.username, 'pk': event.pk}),
    })


@require_POST
@login_required
@event_admin_required
def event_song_remove(request, org_user, event, eventsong_pk):
    eventsong = get_object_or_404(EventSong, pk=eventsong_pk, event=event)
    EventSongResource.objects.filter(event_song=eventsong).delete()
    eventsong.delete()
    return HttpResponse(status=204)


@require_POST
@login_required
@event_admin_required
def event_song_reorder(request, org_user, event, eventsong_pk):
    direction = request.POST.get('direction', '')
    if direction not in {'up_one', 'down_one'}:
        return HttpResponseBadRequest("Invalid direction.")
    reorder_event_song(event, eventsong_pk, direction)
    return HttpResponse(status=204)


@require_POST
@login_required
@event_admin_required
def event_song_encore_toggle(request, org_user, event, eventsong_pk):
    eventsong = get_object_or_404(EventSong, pk=eventsong_pk, event=event)
    eventsong.encore = request.POST.get('encore') == 'true'
    eventsong.save(update_fields=['encore'])
    return HttpResponse(status=204)


@require_POST
@login_required
@event_admin_required
def event_song_resources_save(request, org_user, event, eventsong_pk):
    """Rare, low-frequency edit — a plain form POST + redirect is fine here (no AJAX needed)."""
    eventsong = get_object_or_404(EventSong, pk=eventsong_pk, event=event)
    formset = EventSongResourceFormSet(
        request.POST, instance=eventsong, user=org_user, prefix=f"esresource_{eventsong.pk}",
    )
    if formset.is_valid():
        save_event_song_resources(eventsong, formset, org_user)
        messages.success(request, "Song resources updated.")
    else:
        messages.error(request, "Please fix errors in the song's resources.")
    songs_url = reverse('syncope:event_songs_edit', kwargs={'username': org_user.username, 'pk': event.pk})
    return redirect(f"{songs_url}#song-{eventsong.pk}")


# --- Attendance subpage -------------------------------------------------------------

@method_decorator(login_required, name='dispatch')
class EventAttendanceEditView(View):
    template_name = 'syncope/event_attendance_edit.html'

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if not can_view_event_attendance(request.user, self.customuser):
            return HttpResponseForbidden("You don't have permission to access this page.")
        self.is_admin = is_event_admin(request.user, self.customuser)
        self.event = get_object_or_404(Event, pk=self.kwargs['pk'], user=self.customuser)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        event = self.event
        attendances = get_ordered_attendance_queryset(event)
        search_q = request.GET.get('q', '')
        context = {
            'object': event,
            'event': event,
            'attendances': attendances,
            'attendance_types': AttendanceType.objects.all().order_by('id'),
            'url_username': self.kwargs.get('username'),
            'is_admin': self.is_admin,
            'search_q': search_q,
            'add_form': AddAttendanceForm(
                org_user=self.customuser, event=event, search_q=search_q
            ) if self.is_admin else None,
            'add_participant_url': reverse('syncope:event_attendance_add', kwargs=self.kwargs),
        }
        return render(request, self.template_name, context)


@require_POST
@login_required
@event_admin_required
def event_attendance_add(request, org_user, event):
    """AJAX add-participant endpoint for the Attendance subpage; returns the new row fragment."""
    attendance = _add_attendance_from_post(event, org_user, request.POST)
    if attendance is None:
        return HttpResponseBadRequest("Invalid selection.")

    return render(request, 'syncope/_attendance_row.html', {
        'attendance': attendance,
        'url_username': org_user.username,
        'is_admin': True,
    })


@login_required
@event_admin_required
def event_attendance_search(request, org_user, event):
    """AJAX participant search for the Attendance subpage (points 'Add' at event_attendance_add)."""
    search_q = request.GET.get('q', '')
    add_form = AddAttendanceForm(org_user=org_user, event=event, search_q=search_q)
    return render(request, 'syncope/participant_search_results.html', {
        'add_form': add_form,
        'search_q': search_q,
        'object': event,
        'url_username': org_user.username,
        'add_participant_url': reverse('syncope:event_attendance_add', kwargs={'username': org_user.username, 'pk': event.pk}),
    })


@require_POST
@login_required
@event_admin_required
def event_participant_remove(request, org_user, event, attendance_pk):
    attendance = get_object_or_404(Attendance, pk=attendance_pk, event=event)
    attendance.delete()
    return HttpResponse(status=204)


@require_POST
@login_required
@event_admin_required
def event_attendance_toggle(request, org_user, event, attendance_pk):
    attendance = get_object_or_404(Attendance, pk=attendance_pk, event=event)
    try:
        type_id = int(request.POST.get('attendance_type_id'))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid attendance type.")
    if not AttendanceType.objects.filter(pk=type_id).exists():
        return HttpResponseBadRequest("Invalid attendance type.")
    attendance.attendance_type_id = type_id
    attendance.save(update_fields=['attendance_type'])
    return HttpResponse(status=204)


# --- Meta subpage --------------------------------------------------------------------

@method_decorator(login_required, name='dispatch')
class EventMetaEditView(UpdateView):
    model = Event
    form_class = EventForm
    template_name = 'syncope/event_meta_edit.html'

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if not can_view_event_content(request.user, self.customuser):
            return HttpResponseForbidden("You don't have permission to access this page.")
        self.is_admin = is_event_admin(request.user, self.customuser)
        if request.method == 'POST' and not self.is_admin:
            return HttpResponseForbidden("Only admins can save event changes.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.customuser
        return kwargs

    def get_queryset(self):
        return Event.objects.filter(user=self.customuser)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        if self.request.POST:
            context['resource_formset'] = EventResourceFormSet(
                self.request.POST, instance=event, user=self.customuser,
            )
        else:
            context['resource_formset'] = EventResourceFormSet(
                instance=event, user=self.customuser,
            )
        context['url_username'] = self.kwargs.get('username')
        context['is_admin'] = self.is_admin
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        resource_formset = context['resource_formset']
        if not resource_formset.is_valid():
            messages.error(self.request, "Please fix errors in the resources section.")
            return self.form_invalid(form)

        with transaction.atomic():
            self.object = form.save()
            save_event_resources(self.object, resource_formset, self.customuser)

        messages.success(self.request, "Event updated successfully!")
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        if form.errors:
            messages.error(self.request, f"Event form errors: {form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('syncope:event_detail', kwargs={
            'username': self.kwargs.get('username'),
            'pk': self.object.pk,
        })


@method_decorator(login_required, name="dispatch")
class EventDeleteView(LoginRequiredMixin, DeleteView):
    model = Event
    template_name = 'syncope/event_confirm_delete.html'
    success_url = None

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        return Event.objects.filter(user=org_user)

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        is_admin = AccessControl.can_add_event(
            request.user, org_user
        ).filter(person__roles__id=Role.ADMIN).exists()
        if not is_admin:
            return HttpResponseForbidden("Only admins can delete events.")
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        event = self.get_object()
        event_name = event.name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f"Successfully deleted event '{event_name}'.")
        return response

    def get_success_url(self):
        return reverse('syncope:event_list', kwargs={'username': self.kwargs.get('username')})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['is_admin'] = True
        return context
