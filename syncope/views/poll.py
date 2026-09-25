from django.views.generic import ListView, DetailView, UpdateView, View, DeleteView
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from syncope.models import CustomUser, PollAttendance, Poll, PollPerson, PollEvent, PollAttendanceType, Person, Role
from syncope.forms import PollCreateForm, PollPersonForm, PollAttendanceForm, PollEventForm
from syncope.permissions import AccessControl
from syncope.views.drafts import DraftMixin
from syncope.utils import group_by_section, add_query_param


class PollAdminMixin:
    def dispatch(self, request, *args, **kwargs):
        if not AccessControl.has_permission(request.user, "create", self.kwargs.get("username")):
            return HttpResponseForbidden("Only admins can manage polls.")
        return super().dispatch(request, *args, **kwargs)


@method_decorator(login_required, name="dispatch")
class PollListView(ListView):
    model = Poll
    context_object_name = "polls"
    template_name = "syncope/poll_list.html"

    def _get_sort_field(self, default_sort='updated'):
        """Extract and validate sort parameters from request."""
        sort = self.request.GET.get('sort', default_sort)
        reverse = self.request.GET.get('reverse', 'false') == 'true'

        # If no sort parameter provided, default to descending for backward compatibility
        if 'sort' not in self.request.GET:
            reverse = True

        sort_field_map = {
            'id': 'pk',
            'title': 'title',
            'updated': 'updated_at',
        }
        sort_field = sort_field_map.get(sort, 'updated_at')
        if reverse:
            sort_field = '-' + sort_field

        return sort_field, sort, reverse

    def get_queryset(self):
        org_user = get_object_or_404(CustomUser, username=self.kwargs.get("username"))
        sort_field, _, _ = self._get_sort_field()
        return Poll.objects.filter(user=org_user).select_related('user').order_by(sort_field)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['is_admin'] = AccessControl.has_permission(self.request.user, 'delete', self.kwargs.get('username'))
        _, sort, reverse = self._get_sort_field()
        context['current_sort'] = sort
        context['reverse'] = reverse
        return context


@method_decorator(login_required, name="dispatch")
class PollCreateUpdateView(DraftMixin, PollAdminMixin, UpdateView):
    """Creates or updates basic poll details. Requires title, description, user."""
    model = Poll
    form_class = PollCreateForm
    template_name = "syncope/poll_form.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])

    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        if pk:
            return get_object_or_404(Poll, pk=pk, user=self.org_user)
        return Poll(user=self.org_user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["url_username"] = self.kwargs.get("username")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        if 'pk' not in self.kwargs and form.cleaned_data.get('import_active_members'):
            today = timezone.now().date()
            persons = Person.objects.in_org_user(self.org_user).filter(
                membership_period__role_id=Role.MEMBER,
                membership_period__started_at__lte=today
            ).filter(
                Q(membership_period__ended_at__isnull=True) | Q(membership_period__ended_at__gte=today)
            ).distinct()
            poll_persons = [PollPerson(poll=self.object, person=person) for person in persons]
            if poll_persons:
                PollPerson.objects.bulk_create(poll_persons, ignore_conflicts=True)
        return response

    def get_success_url(self):
        return reverse("syncope:poll_detail", kwargs={
            "username": self.kwargs.get("username"),
            "pk": self.object.pk
        })


@method_decorator(login_required, name="dispatch")
class PollDeleteView(PollAdminMixin, DeleteView):
    model = Poll
    template_name = "syncope/poll_confirm_delete.html"
    context_object_name = "poll"

    def get_queryset(self):
        org_user = get_object_or_404(CustomUser, username=self.kwargs.get("username"))
        return Poll.objects.filter(user=org_user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['is_admin'] = AccessControl.has_permission(self.request.user, 'delete', self.kwargs.get('username'))
        return context

    def get_success_url(self):
        return reverse("syncope:poll_list", kwargs={
            "username": self.kwargs.get("username")
        })
    


@method_decorator(login_required, name="dispatch")
class PollPersonView(PollAdminMixin, View):
    """
    Staged/save-bar editor for a poll's invited persons (add via search, remove/undo, one Save).
    Bulk import (by role/skill) stays a separate instant action.
    """
    template_name = "syncope/poll_person.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'], user=self.org_user)

    def _poll_persons_context(self):
        poll_persons_qs = list(self.poll.poll_persons.select_related('person').prefetch_related(
            'person__singer_set__voice',
            'person__instrumentalist_set__instrument',
            'person__person_skill__skill',
        ))
        grouped_poll_persons = group_by_section(poll_persons_qs, lambda pp: pp.person)
        row_number = 1
        for group in grouped_poll_persons:
            for pp in group['items']:
                pp.index = row_number
                row_number += 1
        return poll_persons_qs, grouped_poll_persons

    def get(self, request, username, pk):
        poll_persons_qs, grouped_poll_persons = self._poll_persons_context()
        return render(request, self.template_name, {
            'poll': self.poll,
            'poll_persons': poll_persons_qs,
            'grouped_poll_persons': grouped_poll_persons,
            'url_username': username,
            'is_admin': True,
        })

    def post(self, request, username, pk):
        with transaction.atomic():
            remove_pks = {
                int(key[len('remove_'):]) for key in request.POST
                if key.startswith('remove_') and request.POST[key] == '1' and key[len('remove_'):].isdigit()
            }
            if remove_pks:
                self.poll.poll_persons.filter(pk__in=remove_pks).delete()

            already_added = set(self.poll.poll_persons.values_list('person_id', flat=True))
            for raw_id in request.POST.getlist('add_person'):
                if not raw_id.isdigit():
                    continue
                person_id = int(raw_id)
                if person_id in already_added:
                    continue
                if not Person.objects.in_org_user(self.org_user).filter(pk=person_id).exists():
                    continue
                PollPerson.objects.create(poll=self.poll, person_id=person_id)
                already_added.add(person_id)

        if request.POST.get('action') == 'new_person':
            new_person_url = reverse('syncope:org_member_new', kwargs={'username': username})
            next_url = reverse('syncope:poll_persons', kwargs={'username': username, 'pk': pk})
            new_person_url = add_query_param(new_person_url, {'auto_add_poll': pk, 'next': next_url})
            return HttpResponseRedirect(new_person_url)

        messages.success(request, "Persons updated successfully!")
        return redirect('syncope:poll_persons', username=username, pk=pk)


@method_decorator(login_required, name="dispatch")
class PollEventView(PollAdminMixin, View):
    """
    Staged/save-bar editor for a poll's dates (add via form, remove/undo, one Save).
    """
    template_name = "syncope/poll_event.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'], user=self.org_user)

    def get(self, request, username, pk):
        last_event = self.poll.poll_events.order_by('-created_at').first()
        initial = {'poll': self.poll}
        if last_event:
            initial.update({
                'event_type': last_event.event_type,
                'started_at': last_event.started_at + timedelta(days=1),
                'ended_at': last_event.ended_at + timedelta(days=1) if last_event.ended_at else None,
                'location': last_event.location,
                'details': last_event.details,
            })
        form = PollEventForm(initial=initial)
        return render(request, self.template_name, {
            'form': form,
            'poll': self.poll,
            'poll_events': self.poll.poll_events.select_related('event_type').order_by('started_at'),
            'url_username': username,
            'is_admin': True,
        })

    def post(self, request, username, pk):
        skipped = 0
        with transaction.atomic():
            remove_pks = {
                int(key[len('remove_'):]) for key in request.POST
                if key.startswith('remove_') and request.POST[key] == '1' and key[len('remove_'):].isdigit()
            }
            if remove_pks:
                self.poll.poll_events.filter(pk__in=remove_pks).delete()

            new_rows = zip(
                request.POST.getlist('new_event_type'),
                request.POST.getlist('new_started_at'),
                request.POST.getlist('new_ended_at'),
                request.POST.getlist('new_location'),
                request.POST.getlist('new_details'),
            )
            for event_type, started_at, ended_at, location, details in new_rows:
                form = PollEventForm(data={
                    'poll': self.poll.pk,
                    'event_type': event_type,
                    'started_at': started_at,
                    'ended_at': ended_at,
                    'location': location,
                    'details': details,
                })
                if form.is_valid():
                    form.save()
                else:
                    skipped += 1

        if skipped:
            messages.warning(request, f"{skipped} date(s) couldn't be saved and were skipped.")
        messages.success(request, "Dates updated successfully!")
        return redirect('syncope:poll_events', username=username, pk=pk)


@method_decorator(login_required, name="dispatch")
class PollEventUpdateView(PollAdminMixin, UpdateView):
    """Edit an existing date's fields directly - its own focused page, no dates table."""
    model = PollEvent
    form_class = PollEventForm
    template_name = "syncope/poll_event.html"
    pk_url_kwarg = "event_pk"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'], user=self.org_user)

    def get_object(self, queryset=None):
        return get_object_or_404(PollEvent, pk=self.kwargs['event_pk'], poll=self.poll)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['poll'] = self.poll
        context['url_username'] = self.kwargs['username']
        context['editing'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, "Date updated successfully!")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("syncope:poll_events", kwargs={
            "username": self.kwargs["username"],
            "pk": self.kwargs["pk"]
        })


class PollPersonAttendanceView(View):
    """Public view - individual person fills in attendance via organization/poll/person pks."""
    template_name = "syncope/poll_attendance.html"

    def _get_context(self, poll_person):
        poll = poll_person.poll
        poll_events = list(poll.poll_events.select_related('event_type').order_by('started_at'))
        attendances = {
            pa.poll_event_id: pa
            for pa in PollAttendance.objects.filter(poll_person=poll_person).select_related('poll_attendance_type')
        }
        event_cells = [
            {
                'event': event,
                'person': poll_person,
                'attendance_type_id': attendances[event.id].poll_attendance_type_id if event.id in attendances else 0,
                'comment': attendances[event.id].comment if event.id in attendances else '',
            }
            for event in poll_events
        ]
        return {
            'poll': poll,
            'poll_events': poll_events,
            'table_rows': [{'person': poll_person, 'event_cells': event_cells}],
            'url_username': poll.user.username,
            'viewing_as': poll_person,
        }

    def get(self, request, username, pk, person_pk):
        poll_person = get_object_or_404(PollPerson.objects.select_related('poll__user'), pk=person_pk, poll__pk=pk)
        return render(request, self.template_name, self._get_context(poll_person))

    def post(self, request, username, pk, person_pk):
        poll_person = get_object_or_404(PollPerson.objects.select_related('poll__user'), pk=person_pk, poll__pk=pk)
        saved_count = 0
        updated_count = 0
        tbd_count = 0
        for event in poll_person.poll.poll_events.all():
            type_id_str = request.POST.get(f'attendance_{event.id}_{poll_person.id}')
            comment = request.POST.get(f'comment_{event.id}_{poll_person.id}', '').strip()
            if type_id_str is not None:
                type_id = int(type_id_str)
                attendance, created = PollAttendance.objects.update_or_create(
                    poll_person=poll_person,
                    poll_event=event,
                    defaults={
                        'poll_attendance_type_id': type_id,
                        'comment': comment or None,
                    }
                )
                if type_id == 0:
                    tbd_count += 1
                elif created:
                    saved_count += 1
                else:
                    updated_count += 1

        if updated_count > 0 and saved_count == 0:
            messages.success(request, f'Updated {updated_count} of events')
        elif updated_count == 0 and saved_count > 0:
            messages.success(request, f'Saved {saved_count} of events, {tbd_count} still waiting to be filled')
        else:
            messages.success(request, f'Saved {saved_count} of events, updated {updated_count} of events, {tbd_count} still waiting to be filled')
        return redirect('syncope:poll_person_attendance', username=username, pk=pk, person_pk=person_pk)


class PollEventAttendanceView(View):
    """Public view - all poll persons list attendance per event slot."""
    template_name = "syncope/poll_attendance.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'])

    def get(self, request, username, pk):
        poll_events = list(self.poll.poll_events.select_related('event_type').order_by('started_at'))
        poll_persons = list(self.poll.poll_persons.select_related('person'))

        # Build person_attendance dict: person_id -> {event_id -> PollAttendance object}
        person_attendance = {}
        for pa in PollAttendance.objects.filter(poll_person__poll=self.poll).select_related('poll_attendance_type'):
            person_attendance.setdefault(pa.poll_person_id, {})[pa.poll_event_id] = pa

        # Create table_rows with event_cells
        table_rows = []
        for pp in poll_persons:
            event_cells = []
            for event in poll_events:
                pa = person_attendance.get(pp.id, {}).get(event.id)
                event_cells.append({
                    'event': event,
                    'person': pp,
                    'attendance_type_id': pa.poll_attendance_type_id if pa else 0,
                    'comment': pa.comment if pa else ''
                })
            row = {
                'person': pp,
                'event_cells': event_cells
            }
            table_rows.append(row)

        return render(request, self.template_name, {
            'poll': self.poll,
            'poll_events': poll_events,
            'table_rows': table_rows,
            'url_username': username,
        })

    def post(self, request, username, pk):
        person_pk = request.POST.get('save_participant')
        poll_person = get_object_or_404(PollPerson, pk=person_pk, poll=self.poll)
        changed_count = 0
        for event in self.poll.poll_events.all():
            type_id_str = request.POST.get(f'attendance_{event.id}_{poll_person.id}')
            comment = request.POST.get(f'comment_{event.id}_{poll_person.id}', '').strip()
            if type_id_str is not None:
                type_id = int(type_id_str)
                new_comment = comment or None
                existing = PollAttendance.objects.filter(
                    poll_person=poll_person, poll_event=event
                ).first()
                if existing is None:
                    if type_id != 0 or new_comment:
                        changed_count += 1
                elif existing.poll_attendance_type_id != type_id or existing.comment != new_comment:
                    changed_count += 1
                PollAttendance.objects.update_or_create(
                    poll_person=poll_person,
                    poll_event=event,
                    defaults={
                        'poll_attendance_type_id': type_id,
                        'comment': new_comment,
                    }
                )
        if changed_count:
            label = 'field' if changed_count == 1 else 'fields'
            messages.success(request, f'Updated {changed_count} {label} for {poll_person.person.first_name} {poll_person.person.last_name}')
        else:
            messages.success(request, f'Saved successfully (no changes) for {poll_person.person.first_name} {poll_person.person.last_name}')
        return redirect('syncope:poll_attendance', username=username, pk=pk)


class PollDetailView(DetailView):
    model = Poll
    template_name = "syncope/poll_detail.html"
    context_object_name = "poll"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')

        poll = self.object
        poll_events = list(poll.poll_events.select_related('event_type').order_by('started_at'))
        poll_persons = list(poll.poll_persons.select_related('person').prefetch_related(
            'person__singer_set__voice',
            'person__instrumentalist_set__instrument',
            'person__person_skill__skill',
        ))

        person_attendance = {}
        for pa in PollAttendance.objects.filter(poll_person__poll=poll).select_related('poll_attendance_type'):
            person_attendance.setdefault(pa.poll_person_id, {})[pa.poll_event_id] = pa

        event_totals = {event.id: {'yes': 0, 'maybe': 0, 'counted': 0} for event in poll_events}

        table_rows = []
        for pp in poll_persons:
            event_cells = []
            total_yes = 0
            total_maybe = 0
            total_counted = 0
            for event in poll_events:
                pa = person_attendance.get(pp.id, {}).get(event.id)
                attendance_type_id = pa.poll_attendance_type_id if pa else 0
                if pa and attendance_type_id != PollAttendanceType.TBD:
                    total_counted += 1
                    event_totals[event.id]['counted'] += 1
                    if attendance_type_id == PollAttendanceType.YES:
                        total_yes += 1
                        event_totals[event.id]['yes'] += 1
                    elif attendance_type_id == PollAttendanceType.MAYBE:
                        total_maybe += 1
                        event_totals[event.id]['maybe'] += 1
                event_cells.append({
                    'event': event,
                    'attendance_type_id': attendance_type_id,
                    'attendance_label': pa.poll_attendance_type.name if pa else 'TBD',
                    'comment': pa.comment if pa else '',
                })
            table_rows.append({
                'person': pp,
                'event_cells': event_cells,
                'total_yes': total_yes,
                'total_maybe': total_maybe,
                'total_counted': total_counted,
                'percentage': (total_yes / total_counted * 100) if total_counted > 0 else 0,
            })

        grouped_table_rows = group_by_section(table_rows, lambda row: row['person'].person)
        row_number = 1
        for group in grouped_table_rows:
            for row in group['items']:
                row['index'] = row_number
                row_number += 1

        event_totals = [event_totals[event.id] for event in poll_events]
        grand_yes = sum(t['yes'] for t in event_totals)
        grand_maybe = sum(t['maybe'] for t in event_totals)
        grand_counted = sum(t['counted'] for t in event_totals)
        grand_percentage = (grand_yes / grand_counted * 100) if grand_counted > 0 else 0

        context['poll_events'] = poll_events
        context['poll_persons'] = poll_persons
        context['table_rows'] = table_rows
        context['grouped_table_rows'] = grouped_table_rows
        context['event_totals'] = event_totals
        context['grand_yes'] = grand_yes
        context['grand_maybe'] = grand_maybe
        context['grand_counted'] = grand_counted
        context['grand_percentage'] = grand_percentage
        context['is_admin'] = (
            self.request.user.is_authenticated and
            AccessControl.has_permission(self.request.user, "create", self.kwargs.get('username'))
        )
        return context

    # accessible using special link to public


@login_required
def poll_persons_search(request, username, pk):
    """AJAX person search for the Persons subpage's add-participant picker."""
    org_user = get_object_or_404(CustomUser, username=username)
    if not AccessControl.has_permission(request.user, "create", username):
        return HttpResponseForbidden("Only admins can manage polls.")
    poll = get_object_or_404(Poll, pk=pk, user=org_user)
    q = request.GET.get('q', '')
    exclude_raw = request.GET.get('exclude', '')
    exclude_ids = [int(x) for x in exclude_raw.split(',') if x.strip().isdigit()]
    form = PollPersonForm(org_user=org_user, poll=poll, search_q=q, exclude_ids=exclude_ids)
    return render(request, 'syncope/poll_person_search_results.html', {
        'form': form,
        'search_q': q,
    })