from django.views.generic import ListView, DetailView, UpdateView, View, DeleteView
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponseForbidden
from django.db.models import Q
from django.utils import timezone
from django.utils.safestring import mark_safe
from datetime import timedelta
from syncope.models import CustomUser, PollAttendance, Poll, PollPerson, PollEvent, PollAttendanceType, Person, Role
from syncope.forms import PollCreateForm, PollPersonForm, PollAttendanceForm, PollEventForm, PollBulkImportForm
from syncope.permissions import AccessControl


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

    def get_queryset(self):
        org_user = get_object_or_404(CustomUser, username=self.kwargs.get("username"))
        return Poll.objects.filter(user=org_user).select_related('user').order_by('-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        return context


@method_decorator(login_required, name="dispatch")
class PollCreateUpdateView(PollAdminMixin, UpdateView):
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
        return reverse("syncope:poll_basic", kwargs={
            "username": self.kwargs.get("username"),
            "pk": self.object.pk
        })


@method_decorator(login_required, name="dispatch")
class PollBasicView(PollAdminMixin, DetailView):
    """Presents basic poll details."""
    model = Poll
    template_name = "syncope/poll_basic.html"
    context_object_name = "poll"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["url_username"] = self.kwargs["username"]
        context["poll_persons"] = self.object.poll_persons.select_related('person')
        context["poll_events"] = self.object.poll_events.select_related('event_type').order_by('started_at')

        return context

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
        return context

    def get_success_url(self):
        return reverse("syncope:poll_list", kwargs={
            "username": self.kwargs.get("username")
        })
    


@method_decorator(login_required, name="dispatch")
class PollPersonView(PollAdminMixin, View):
    """
    Access from admin to only persons within the same customuser-organization.
    Search menu for the persons, indexes first name, last name, role, skill, voice, instrument.
    """
    template_name = "syncope/poll_person.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'], user=self.org_user)

    def get(self, request, username, pk):
        q = request.GET.get('q', '').strip()
        form = PollPersonForm(initial={'poll': self.poll}, org_user=self.org_user, poll=self.poll, search_q=q or None)
        return render(request, self.template_name, {
            'form': form,
            'bulk_import_form': PollBulkImportForm(),
            'poll': self.poll,
            'poll_persons': self.poll.poll_persons.select_related('person'),
            'url_username': username,
            'q': q,
        })

    def post(self, request, username, pk):
        if request.POST.get('action') == 'bulk_import':
            return self.bulk_import_persons(request, username, pk)
        form = PollPersonForm(request.POST, org_user=self.org_user, poll=self.poll)
        if form.is_valid():
            form.save()
            return redirect('syncope:poll_persons', username=username, pk=pk)
        return render(request, self.template_name, {
            'form': form,
            'bulk_import_form': PollBulkImportForm(),
            'poll': self.poll,
            'poll_persons': self.poll.poll_persons.select_related('person'),
            'url_username': username,
        })

    def bulk_import_persons(self, request, username, pk):
        """Auto-import members filtered by role and/or skill."""
        role_criteria = request.POST.get('role_criteria')
        skill_criteria = request.POST.get('skill_criteria')

        persons = Person.objects.in_org_user(self.org_user)

        if role_criteria and role_criteria != 'all':
            persons = persons.filter(roles__title=role_criteria)

        if skill_criteria and skill_criteria != 'all':
            persons = persons.filter(skills__title=skill_criteria)

        existing_person_ids = self.poll.poll_persons.values_list('person_id', flat=True)
        persons = persons.exclude(id__in=existing_person_ids).distinct()

        poll_persons = [PollPerson(poll=self.poll, person=person) for person in persons]

        created_count = len(poll_persons)
        if created_count > 0:
            PollPerson.objects.bulk_create(poll_persons, ignore_conflicts=True)
            messages.success(request, f'Successfully imported {created_count} persons.')
        else:
            messages.info(request, 'No new persons to import.')

        return redirect('syncope:poll_persons', username=username, pk=pk)


@method_decorator(login_required, name="dispatch")
class PollEventView(PollAdminMixin, View):
    """
    Adds date and location possibilities to the poll.
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
        })

    def post(self, request, username, pk):
        form = PollEventForm(request.POST)
        if form.is_valid():
            event = form.save()
            date_str = event.started_at.strftime('%d %b')
            time_str = event.started_at.strftime('%H:%M')
            end_time_str = event.ended_at.strftime('%H:%M') if event.ended_at else ''
            msg = f"Event slot added: {event.event_type.name} on {date_str} at {time_str}"
            if end_time_str:
                msg += f" - {end_time_str}"
            if event.location:
                msg += f" (Location: {event.location})"
            if event.details:
                msg += f" - {event.details}"
            messages.success(request, msg)
            return redirect('syncope:poll_events', username=username, pk=pk)
        return render(request, self.template_name, {
            'form': form,
            'poll': self.poll,
            'poll_events': self.poll.poll_events.select_related('event_type').order_by('started_at'),
            'url_username': username,
        })


@method_decorator(login_required, name="dispatch")
class PollEventUpdateView(PollAdminMixin, UpdateView):
    """Edit an existing poll event slot."""
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
        context['poll_events'] = self.poll.poll_events.select_related('event_type').order_by('started_at')
        context['url_username'] = self.kwargs['username']
        context['editing'] = True
        return context

    def form_valid(self, form):
        event = form.save()
        date_str = event.started_at.strftime('%d %b')
        time_str = event.started_at.strftime('%H:%M')
        end_time_str = event.ended_at.strftime('%H:%M') if event.ended_at else ''
        msg = f"Event slot updated: {event.event_type.name} on {date_str} at {time_str}"
        if end_time_str:
            msg += f" - {end_time_str}"
        if event.location:
            msg += f" (Location: {event.location})"
        if event.details:
            msg += f" - {event.details}"
        messages.warning(self.request, msg)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("syncope:poll_events", kwargs={
            "username": self.kwargs["username"],
            "pk": self.kwargs["pk"]
        })


class PollPersonAttendanceView(View):
    """Public view — individual person fills in attendance via UUID token."""
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

    def get(self, request, token):
        poll_person = get_object_or_404(PollPerson, token=token)
        return render(request, self.template_name, self._get_context(poll_person))

    def post(self, request, token):
        poll_person = get_object_or_404(PollPerson, token=token)
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
        return redirect('syncope:poll_person_attendance', token=token)


class PollEventAttendanceView(View):
    """Public view — all poll persons list attendance per event slot."""
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
        poll_persons = list(poll.poll_persons.select_related('person'))

        person_attendance = {}
        for pa in PollAttendance.objects.filter(poll_person__poll=poll).select_related('poll_attendance_type'):
            person_attendance.setdefault(pa.poll_person_id, {})[pa.poll_event_id] = pa

        table_rows = []
        for pp in poll_persons:
            event_cells = []
            for event in poll_events:
                pa = person_attendance.get(pp.id, {}).get(event.id)
                event_cells.append({
                    'event': event,
                    'attendance_type_id': pa.poll_attendance_type_id if pa else 0,
                    'attendance_label': pa.poll_attendance_type.name if pa else 'TBD',
                    'comment': pa.comment if pa else '',
                })
            table_rows.append({'person': pp, 'event_cells': event_cells})

        context['poll_events'] = poll_events
        context['poll_persons'] = poll_persons
        context['table_rows'] = table_rows
        return context

    # accessible using special link to public


@require_POST
@login_required
def poll_person_remove(request, username, pk, person_pk):
    org_user = get_object_or_404(CustomUser, username=username)
    if not AccessControl.has_permission(request.user, "create", username):
        return HttpResponseForbidden("Only admins can manage polls.")
    poll_person = get_object_or_404(PollPerson, pk=person_pk, poll__pk=pk, poll__user=org_user)
    poll_person.delete()
    return redirect('syncope:poll_persons', username=username, pk=pk)


@require_POST
@login_required
def poll_event_remove(request, username, pk, event_pk):
    org_user = get_object_or_404(CustomUser, username=username)
    if not AccessControl.has_permission(request.user, "create", username):
        return HttpResponseForbidden("Only admins can manage polls.")
    poll_event = get_object_or_404(PollEvent, pk=event_pk, poll__pk=pk, poll__user=org_user)
    poll_event.delete()
    return redirect('syncope:poll_events', username=username, pk=pk)