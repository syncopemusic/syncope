from django.http import HttpResponseForbidden
from django.shortcuts import  get_object_or_404
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.views.generic import ListView, CreateView, UpdateView,  DetailView
from django.views.generic.edit import DeleteView
from django.db.models import Max, Min, Case, When, Value, IntegerField, Prefetch
from django.shortcuts import redirect
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.contrib.auth.mixins import LoginRequiredMixin
from syncope.models import CustomUser, Person, Role
from syncope.models import Event, EventSong, Attendance, AttendanceType, EventResource, EventSongResource, Resource, SongResource
from syncope.forms import EventForm, EventSongFormSet, AttendanceFormSet, AddAttendanceForm
from syncope.forms import AddSongToEventForm, EventResourceFormSet, EventSongResourceFormSet
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list


@method_decorator(login_required, name='dispatch')
class EventCreateView(CreateView):
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
        return reverse_lazy("syncope:event_update", kwargs={
            "username": self.customuser.username,
            "pk": self.object.pk
        })

@method_decorator(login_required, name='dispatch')
class EventUpdateView(UpdateView):
    model = Event
    form_class = EventForm
    template_name = 'syncope/event_update.html'

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
            attendance_qs = event.attendance_set.select_related(
                'person', 'attendance_type'
            ).annotate(
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
        context['add_form'] = AddAttendanceForm(
            org_user=self.customuser,
            event=event,
            search_q=search_q,
        ) if self.is_admin else None
        context['add_song_form'] = AddSongToEventForm(
            org_user=self.customuser,
            event=event,
            search_q=song_search_q,
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
        event.event_resource.all().delete()
        valid_forms = [
            f for f in resource_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
        ]
        for idx, f in enumerate(valid_forms):
            url = f.cleaned_data['url']
            description = f.cleaned_data.get('description', '')
            resource, created = Resource.objects.get_or_create(
                url=url,
                defaults={'owner': self.customuser, 'description': description}
            )
            if not created:
                resource.description = description
                resource.save(update_fields=['description'])
            EventResource.objects.create(event=event, resource=resource, order=idx + 1)

    def _save_song_resources(self, event_song, resource_formset):
        event_song.event_song_resource.all().delete()
        valid_forms = [
            f for f in resource_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
        ]
        for idx, f in enumerate(valid_forms):
            url = f.cleaned_data['url']
            description = f.cleaned_data.get('description', '')
            resource, created = Resource.objects.get_or_create(
                url=url,
                defaults={'owner': self.customuser, 'description': description}
            )
            if not created:
                resource.description = description
                resource.save(update_fields=['description'])
            EventSongResource.objects.create(event_song=event_song, resource=resource, order=idx + 1)

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

        songs = list(event.eventsong_set.all().order_by('order'))
        if not songs:
            return

        song_idx = None
        for idx, song in enumerate(songs):
            if song.pk == song_pk:
                song_idx = idx
                break

        if song_idx is None:
            return

        # Perform the reordering
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
            return

        # Update order in database using temporary negative values to avoid constraint violations
        with transaction.atomic():
            # First, set all to temporary negative values
            for idx, song in enumerate(songs):
                song.order = -(idx + 1)
                song.save(update_fields=['order'])
            # Then, set to final positive values
            for idx, song in enumerate(songs):
                song.order = idx + 1
                song.save(update_fields=['order'])

    def form_valid(self, form):
        self.get_context_data()  # ensures formsets are built and cached on self
        admin_override = self.request.POST.get('admin_override') == 'true' and self.is_admin

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

    def get_queryset(self):
        url_username = self.kwargs.get("username")
        customuser = get_object_or_404(CustomUser, username=url_username)
        return Event.objects.filter(user=customuser).prefetch_related(
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
        context['attendances'] = self.object.attendance_set.select_related(
            'person', 'attendance_type'
        ).annotate(
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
        context['is_admin'] = AccessControl.can_add_event(
            self.request.user, self.object.user
        ).filter(person__roles__id=Role.ADMIN).exists()
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




@require_POST
@login_required
def event_add_attendance(request, username, pk):
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=pk, user=org_user)

    is_admin = AccessControl.can_add_event(
        request.user, org_user
    ).filter(person__roles__id=Role.ADMIN).exists()
    if not is_admin:
        return HttpResponseForbidden("Only admins can add participants.")

    form = AddAttendanceForm(request.POST, org_user=org_user, event=event)
    if form.is_valid():
        Attendance.objects.get_or_create(
            event=event,
            person=form.cleaned_data['person'],
            defaults={'attendance_type': form.cleaned_data['attendance_type']},
        )

    return redirect('syncope:event_update', username=username, pk=pk)



@require_POST
@login_required
def event_add_song(request, username, pk):
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=pk, user=org_user)

    is_admin = AccessControl.can_add_event(
        request.user, org_user
    ).filter(person__roles__id=Role.ADMIN).exists()
    if not is_admin:
        return HttpResponseForbidden("Only admins can add songs to events.")

    form = AddSongToEventForm(request.POST, org_user=org_user, event=event)
    if form.is_valid():
        next_order = (event.eventsong_set.aggregate(Max('order'))['order__max'] or 0) + 1
        EventSong.objects.create(
            event=event,
            song=form.cleaned_data['song'],
            order=next_order,
            encore=form.cleaned_data.get('encore', False),
        )

    return redirect('syncope:event_update', username=username, pk=pk)


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
