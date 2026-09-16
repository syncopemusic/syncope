from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import  get_object_or_404, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView,  DetailView, View
from django.views.generic.edit import DeleteView
from django.db.models import Min, Case, When, Value, IntegerField, Prefetch, Count
from django.shortcuts import redirect
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.http import url_has_allowed_host_and_scheme
from syncope.models import CustomUser, Person, Role, Song
from syncope.models import Event, EventSong, Attendance, AttendanceType, EventResource, EventSongResource, Resource, SongResource
from syncope.forms import EventForm, AddAttendanceForm
from syncope.forms import AddSongToEventForm, EventResourceFormSet, EventSongResourceFormSet
from syncope.views.drafts import DraftMixin
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list, add_query_param
from syncope.breadcrumbs import event_breadcrumbs, DEFAULT_EVENT_ORIGIN


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
        context['breadcrumbs'], context['origin_key'] = event_breadcrumbs(
            self.request, self.kwargs.get('username'), self.object
        )
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




# --- Songs subpage -----------------------------------------------------------------

@method_decorator(login_required, name='dispatch')
class EventSongsEditView(View):
    """Staged/save-bar editor for an event's setlist (add via search, drag to reorder, remove/undo, one Save)."""
    template_name = 'syncope/event_songs_edit.html'

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if not can_view_event_content(request.user, self.customuser):
            return HttpResponseForbidden("You don't have permission to access this page.")
        self.is_admin = is_event_admin(request.user, self.customuser)
        if request.method == 'POST' and not self.is_admin:
            return HttpResponseForbidden("Only admins can make this change.")
        self.event = get_object_or_404(Event, pk=self.kwargs['pk'], user=self.customuser)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._get_context())

    def _get_context(self):
        event = self.event
        eventsongs = list(
            event.eventsong_set.select_related('song', 'song__composer', 'song__arranger').order_by('order').annotate(
                song_resource_count=Count('song__song_resource', distinct=True),
                es_resource_count=Count('event_song_resource', distinct=True),
            )
        )
        for idx, es in enumerate(eventsongs):
            es.index = idx + 1
            es.resources_count = es.song_resource_count + es.es_resource_count
        search_q = self.request.GET.get('song_q', '')
        breadcrumbs, origin_key = event_breadcrumbs(
            self.request, self.kwargs.get('username'), event, current_label='Songs'
        )
        songs_url = add_query_param(
            reverse('syncope:event_songs_edit', kwargs={'username': self.kwargs.get('username'), 'pk': event.pk}),
            {'origin': origin_key},
        )
        return {
            'object': event,
            'event': event,
            'eventsongs': eventsongs,
            'url_username': self.kwargs.get('username'),
            'is_admin': self.is_admin,
            'song_search_q': search_q,
            'breadcrumbs': breadcrumbs,
            'origin_key': origin_key,
            'songs_url': songs_url,
            'add_song_form': AddSongToEventForm(
                org_user=self.customuser, event=event, search_q=search_q
            ) if self.is_admin else None,
        }

    def post(self, request, *args, **kwargs):
        event = self.event
        order_tokens = [t for t in request.POST.get('song_order', '').split(',') if t]

        remove_pks = set()
        for key in request.POST:
            if key.startswith('remove_') and request.POST.get(key) == '1':
                pk = key[len('remove_'):]
                if pk.isdigit():
                    remove_pks.add(int(pk))

        with transaction.atomic():
            if remove_pks:
                # EventSongResource.event_song is on_delete=PROTECT — clear resources first.
                EventSongResource.objects.filter(event_song_id__in=remove_pks).delete()
                EventSong.objects.filter(event=event, pk__in=remove_pks).delete()

            surviving = list(EventSong.objects.filter(event=event).order_by('order'))
            surviving_by_pk = {str(es.pk): es for es in surviving}
            for idx, es in enumerate(surviving):
                es.order = -(idx + 1)
            if surviving:
                EventSong.objects.bulk_update(surviving, ['order'])

            new_song_pks = {t[len('new-'):] for t in order_tokens if t.startswith('new-')}
            valid_song_ids = set(
                Song.objects.filter(pk__in=new_song_pks, user=self.customuser).values_list('pk', flat=True)
            ) if new_song_pks else set()

            final_order = 0
            seen_new_songs = set()
            for token in order_tokens:
                if token.startswith('es-'):
                    es = surviving_by_pk.get(token[len('es-'):])
                    if es is None:
                        continue
                    final_order += 1
                    es.order = final_order
                    es.save(update_fields=['order'])
                elif token.startswith('new-'):
                    song_pk = token[len('new-'):]
                    if not song_pk.isdigit() or int(song_pk) not in valid_song_ids or song_pk in seen_new_songs:
                        continue
                    seen_new_songs.add(song_pk)
                    final_order += 1
                    EventSong.objects.create(event=event, song_id=song_pk, order=final_order)

            # A surviving row the client didn't mention in song_order (shouldn't normally happen) keeps a spot at the end.
            for es in surviving:
                if es.order < 0:
                    final_order += 1
                    es.order = final_order
                    es.save(update_fields=['order'])

        if request.POST.get('action') == 'new_song':
            song_new_url = reverse('syncope:song_new', kwargs={'username': self.kwargs.get('username')})
            next_url = reverse('syncope:event_songs_edit', kwargs={
                'username': self.kwargs.get('username'), 'pk': event.pk,
            })
            song_new_url = add_query_param(song_new_url, {'auto_add_event': event.pk, 'next': next_url})
            return HttpResponseRedirect(song_new_url)

        messages.success(request, "Songs updated successfully!")
        edit_url = reverse('syncope:event_songs_edit', kwargs={
            'username': self.kwargs.get('username'), 'pk': event.pk,
        })
        origin = request.GET.get('origin')
        if origin:
            edit_url = add_query_param(edit_url, {'origin': origin})
        return HttpResponseRedirect(edit_url)


@login_required
@event_admin_required
def event_songs_search(request, org_user, event):
    """AJAX song search for the Songs subpage's add-song picker."""
    song_search_q = request.GET.get('song_q', '')
    exclude_raw = request.GET.get('exclude', '')
    exclude_ids = [int(x) for x in exclude_raw.split(',') if x.strip().isdigit()]
    add_song_form = AddSongToEventForm(
        org_user=org_user, event=event, search_q=song_search_q, exclude_ids=exclude_ids
    )
    return render(request, 'syncope/song_search_results.html', {
        'add_song_form': add_song_form,
        'song_search_q': song_search_q,
        'object': event,
        'event': event,
        'url_username': org_user.username,
    })


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
        if request.method == 'POST' and not self.is_admin:
            return HttpResponseForbidden("Only admins can save attendance changes.")
        self.event = get_object_or_404(Event, pk=self.kwargs['pk'], user=self.customuser)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        event = self.event
        attendances = get_ordered_attendance_queryset(event)
        search_q = request.GET.get('q', '')
        breadcrumbs, origin_key = event_breadcrumbs(
            request, self.kwargs.get('username'), event, current_label='Attendance'
        )
        context = {
            'object': event,
            'event': event,
            'attendances': attendances,
            'attendance_types': AttendanceType.objects.all().order_by('id'),
            'url_username': self.kwargs.get('username'),
            'is_admin': self.is_admin,
            'search_q': search_q,
            'breadcrumbs': breadcrumbs,
            'origin_key': origin_key,
            'add_form': AddAttendanceForm(
                org_user=self.customuser, event=event, search_q=search_q
            ) if self.is_admin else None,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        event = self.event
        valid_type_ids = set(AttendanceType.objects.values_list('pk', flat=True))

        with transaction.atomic():
            attendances = {a.pk: a for a in event.attendance_set.all()}

            remove_pks = set()
            for key in request.POST:
                if key.startswith('remove_') and request.POST.get(key) == '1':
                    try:
                        pk = int(key[len('remove_'):])
                    except ValueError:
                        continue
                    if pk in attendances:
                        remove_pks.add(pk)
            if remove_pks:
                event.attendance_set.filter(pk__in=remove_pks).delete()

            for pk, attendance in attendances.items():
                if pk in remove_pks:
                    continue
                try:
                    type_id = int(request.POST.get(f'type_{pk}'))
                except (TypeError, ValueError):
                    continue
                if type_id in valid_type_ids and type_id != attendance.attendance_type_id:
                    attendance.attendance_type_id = type_id
                    attendance.save(update_fields=['attendance_type'])

            already_attending = set(event.attendance_set.values_list('person_id', flat=True))
            for raw_person_id in request.POST.getlist('add_person'):
                try:
                    person_id = int(raw_person_id)
                except ValueError:
                    continue
                if person_id in already_attending:
                    continue
                if not Person.objects.filter(
                    pk=person_id, membership_period__user=self.customuser
                ).exists():
                    continue
                try:
                    type_id = int(request.POST.get(f'add_type_{person_id}'))
                except (TypeError, ValueError):
                    type_id = AttendanceType.PRESENT
                if type_id not in valid_type_ids:
                    type_id = AttendanceType.PRESENT
                Attendance.objects.create(event=event, person_id=person_id, attendance_type_id=type_id)
                already_attending.add(person_id)

        if request.POST.get('action') == 'new_person':
            new_person_url = reverse('syncope:org_member_new', kwargs={'username': self.kwargs.get('username')})
            next_url = reverse('syncope:event_attendance_edit', kwargs={
                'username': self.kwargs.get('username'),
                'pk': event.pk,
            })
            new_person_url = add_query_param(new_person_url, {'auto_add_event': event.pk, 'next': next_url})
            return HttpResponseRedirect(new_person_url)

        messages.success(request, "Attendance updated successfully!")
        edit_url = reverse('syncope:event_attendance_edit', kwargs={
            'username': self.kwargs.get('username'),
            'pk': event.pk,
        })
        origin = request.GET.get('origin')
        if origin:
            edit_url = add_query_param(edit_url, {'origin': origin})
        return HttpResponseRedirect(edit_url)


@login_required
@event_admin_required
def event_attendance_search(request, org_user, event):
    """AJAX participant search for the Attendance subpage's add-participant picker."""
    search_q = request.GET.get('q', '')
    exclude_raw = request.GET.get('exclude', '')
    exclude_ids = [int(x) for x in exclude_raw.split(',') if x.strip().isdigit()]
    add_form = AddAttendanceForm(org_user=org_user, event=event, search_q=search_q, exclude_ids=exclude_ids)
    return render(request, 'syncope/participant_search_results.html', {
        'add_form': add_form,
        'search_q': search_q,
        'object': event,
        'event': event,
        'url_username': org_user.username,
        'origin_key': request.GET.get('origin', DEFAULT_EVENT_ORIGIN),
    })


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
        context['eventsongs'] = event.eventsong_set.select_related('song').order_by('order')
        context['encore_eventsong_id'] = event.eventsong_set.filter(encore=True).values_list('pk', flat=True).first()
        context['breadcrumbs'], context['origin_key'] = event_breadcrumbs(
            self.request, self.kwargs.get('username'), event, current_label='Details'
        )
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        resource_formset = context['resource_formset']
        if not resource_formset.is_valid():
            messages.error(self.request, "Please fix errors in the resources section.")
            return self.form_invalid(form)

        encore_raw = self.request.POST.get('encore_song', '')
        encore_pk = int(encore_raw) if encore_raw.isdigit() else None

        with transaction.atomic():
            self.object = form.save()
            save_event_resources(self.object, resource_formset, self.customuser)
            eventsongs = self.object.eventsong_set.filter(encore=True) | self.object.eventsong_set.filter(pk=encore_pk)
            for es in eventsongs.distinct():
                new_encore = es.pk == encore_pk
                if es.encore != new_encore:
                    es.encore = new_encore
                    es.save(update_fields=['encore'])

        messages.success(self.request, "Event updated successfully!")
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        if form.errors:
            messages.error(self.request, f"Event form errors: {form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        url = reverse('syncope:event_detail', kwargs={
            'username': self.kwargs.get('username'),
            'pk': self.object.pk,
        })
        origin = self.request.GET.get('origin')
        if origin:
            url = add_query_param(url, {'origin': origin})
        return url


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['breadcrumbs'], context['origin_key'] = event_breadcrumbs(
            self.request, self.kwargs.get('username'), self.object, current_label='Delete'
        )
        return context

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
