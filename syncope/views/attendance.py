from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from datetime import timedelta
from django.utils import timezone
from django.views.generic import View
from django.views.generic.edit import DeleteView
from django.db.models import Count, Q
from django.shortcuts import redirect
from syncope.utils import group_by_section
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from syncope.models import CustomUser, Person, Role
from syncope.models import Event, Attendance, AttendanceType, EventType
from syncope.permissions import AccessControl


@method_decorator(login_required, name="dispatch")
class AttendanceDashboardView(View):
    template_name = 'syncope/attendance_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        """Handle permission checking before processing the request."""
        url_username = self.kwargs.get("username")
        self.org_user = get_object_or_404(CustomUser, username=url_username)

        if request.user != self.org_user:
            has_permission = AccessControl.can_edit_event(
                request.user, self.org_user
            ).exists()

            if not has_permission:
                return HttpResponseForbidden("You don't have permission to view this dashboard.")

        return super().dispatch(request, *args, **kwargs)

    def _is_counted_attendance(self, attendance_type_id):
        """Check if attendance type should count toward statistics (not TBD)."""
        return attendance_type_id is not None and attendance_type_id != AttendanceType.TBD

    def _get_members_for_events(self, events):
        """Get members active during the displayed events' date range.

        Returns all members whose MembershipPeriod overlaps with the date span
        of the displayed events. This ensures historical members remain in rows
        even after their membership ends, as long as events from their active
        period are shown.
        """
        if events:
            dates = [e.started_at.date() for e in events]
            earliest, latest = min(dates), max(dates)
        else:
            today = timezone.now().date()
            earliest = latest = today

        return Person.objects.active_during_date_range(self.org_user, earliest, latest).prefetch_related(
            'singer_set__voice',
            'instrumentalist_set__instrument',
            'person_skill__skill',
        )

    def _fetch_events(self, event_limit, start_date, end_date, include_prefetch=True):
        """
        Fetch and organize events for display.
        Returns (events list, editable_event_id, grayed_out_event_ids)

        Filter logic:
        - If start_date AND end_date: use date range, return all events in range
        - Otherwise: show one future event (if available), one present event (current or most recent past), and all other past events
        - Only one event is editable (either current event or most recent past)
        """
        now = timezone.now()

        # Build base query with optimization
        base_query = Event.objects.filter(
            user=self.org_user
        ).select_related('event_type')

        if include_prefetch:
            base_query = base_query.prefetch_related(
                'attendance_set__person',
                'attendance_set__attendance_type'
            )

        # Apply date filters if provided
        if start_date and end_date:
            base_query = base_query.filter(
                started_at__date__gte=start_date,
                started_at__date__lte=end_date
            )

        # Split into past and future events
        past_qs = base_query.filter(started_at__lt=now).order_by('-started_at')
        future_qs = base_query.filter(started_at__gte=now).order_by('started_at')

        # Fetch events: date range takes all, otherwise show simplified view
        if start_date and end_date:
            # Date range mode: fetch all events in range
            past_events = list(past_qs)
            future_events = list(future_qs)
        else:
            # Simplified mode: one future event, limited past events
            future_events = list(future_qs[:1])
            past_events = list(past_qs[:event_limit])

        # Final list: oldest past → most recent past → soonest future
        events = list(reversed(past_events)) + future_events

        # Determine which event is editable: current event or most recent past
        editable_event = None

        # First, check if there's a current event (started but not finished)
        current_event = base_query.filter(
            started_at__lte=now,
            ended_at__gt=now
        ).first()

        if current_event:
            editable_event = current_event
        elif past_events:
            editable_event = past_events[0]  # Most recent past event

        editable_event_id = editable_event.id if editable_event else None

        # Mark non-editable past events as grayed out (for POST skip logic)
        grayed_out_event_ids = set()
        for event in events:
            if event.started_at < now and event.id != editable_event_id:
                grayed_out_event_ids.add(event.id)
                event.is_grayed_out = True
            else:
                event.is_grayed_out = False

        return events, editable_event_id, grayed_out_event_ids

    def get(self, request, username):
        # Get date range from query params or default to last 8 events
        event_limit = int(request.GET.get('event_limit') or 8)
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        # Fetch and organize events
        events, editable_event_id, grayed_out_event_ids = self._fetch_events(
            event_limit, start_date, end_date, include_prefetch=True
        )

        # Get members active during the displayed events' date range
        members = self._get_members_for_events(events)

        # Get attendance types
        present_type = AttendanceType.objects.get(pk=AttendanceType.PRESENT)

        # Build attendance matrix
        dashboard_data = self._build_attendance_matrix(members, events, present_type)

        # Group by section
        grouped_dashboard_data = group_by_section(dashboard_data, lambda row: row['member'])

        # Calculate totals per event
        event_totals = self._calculate_event_totals(events, members, present_type)

        context = {
            'org_user': self.org_user,
            'members': members,
            'grouped_dashboard_data': grouped_dashboard_data,
            'events': events,
            'dashboard_data': dashboard_data,
            'event_totals': event_totals,
            'url_username': username,
        }

        return render(request, self.template_name, context)

    def post(self, request, username):
        """Handle bulk attendance updates."""
        with transaction.atomic():
            # Get all events and members being displayed
            event_limit = int(request.GET.get('event_limit') or 8)
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')

            # Fetch and organize events (no prefetch needed for POST)
            events, editable_event_id, grayed_out_event_ids = self._fetch_events(
                event_limit, start_date, end_date, include_prefetch=False
            )

            members = self._get_members_for_events(events)

            # Read submitted type IDs per cell
            VALID_TYPE_IDS = {
                AttendanceType.PRESENT,
                AttendanceType.WORK_SCHOOL,
                AttendanceType.ILLNESS,
                AttendanceType.PRIVATE_VACATION,
                AttendanceType.TBD,
            }
            submitted_types = {}
            for key, value in request.POST.items():
                if key.startswith('attendance_'):
                    parts = key.split('_')
                    if len(parts) == 3:
                        try:
                            submitted_types[(int(parts[1]), int(parts[2]))] = int(value)
                        except (ValueError, TypeError):
                            pass

            skipped_count = 0

            is_admin = AccessControl.can_add_event(
                request.user,
                self.org_user
            ).filter(person__roles__id=Role.ADMIN).exists()

            # Update all attendance records
            for event in events:
                # Skip if event is grayed out (past event, not the most recent)
                if event.id in grayed_out_event_ids:
                    skipped_count += members.count()
                    continue

                for member in members:
                    type_id = submitted_types.get((event.id, member.id), AttendanceType.TBD)
                    if type_id not in VALID_TYPE_IDS:
                        type_id = AttendanceType.TBD

                    # Get existing attendance if it exists
                    try:
                        attendance = Attendance.objects.get(event=event, person=member)
                        if attendance.attendance_type_id != type_id:
                            attendance.attendance_type_id = type_id
                            attendance.save()

                    except Attendance.DoesNotExist:
                        # Create new record
                        Attendance.objects.create(
                            event=event,
                            person=member,
                            attendance_type_id=type_id
                        )

                # NEW: Show appropriate success message
            if skipped_count > 0:
                messages.warning(
                    request,
                    f"Attendance updated!"
                )
            else:
                messages.success(request, "Attendance updated successfully!")

        # Redirect back to the same view with the same filters
        query_params = request.GET.urlencode()
        redirect_url = reverse('syncope:attendance', kwargs={'username': username})
        if query_params:
            redirect_url += f'?{query_params}'
        return redirect(redirect_url)

    def _build_attendance_matrix(self, members, events, present_type):
        """Build efficient attendance lookup matrix."""
        # Create lookup dict: {event_id: {person_id: attendance_type_id}}
        attendance_lookup = {}
        for event in events:
            attendance_lookup[event.id] = {
                att.person_id: {
                    'type_id': att.attendance_type_id,
                    # 'is_locked': att.is_locked
                }
                for att in event.attendance_set.all()
            }

        # Build row data for each member
        dashboard_data = []
        for member in members:
            row = {
                'member': member,
                'attendance_cells': [],
                'total_present': 0,
                'total_events': 0,
            }

            # Build list of attendance cells in same order as events
            for event in events:
                att_data = attendance_lookup.get(event.id, {}).get(member.id, {})
                attendance_type_id = att_data.get('type_id')

                # Only count this event in the denominator if attendance is counted (not TBD)
                if att_data and self._is_counted_attendance(attendance_type_id):
                    row['total_events'] += 1

                # Check if this event is grayed out
                is_grayed_out = getattr(event, 'is_grayed_out', False)

                row['attendance_cells'].append({
                    'event_id': event.id,
                    'attendance_type_id': attendance_type_id,
                    'is_grayed_out': is_grayed_out,
                })

                if attendance_type_id == present_type.id:
                    row['total_present'] += 1

            row['percentage'] = (row['total_present'] / row['total_events'] * 100) if row['total_events'] > 0 else 0
            dashboard_data.append(row)

        return dashboard_data

    def _calculate_event_totals(self, events, members, present_type):
        """Calculate attendance totals per event."""
        # Build a dict of event_id -> present count using a single query
        event_ids = [e.id for e in events]
        present_counts = {}

        if event_ids:
            results = Attendance.objects.filter(
                event_id__in=event_ids,
                attendance_type=present_type
            ).values('event_id').annotate(count=Count('id'))

            for result in results:
                present_counts[result['event_id']] = result['count']

        # Build a dict of event_id -> counted attendance per event
        non_tbd_counts = {}
        if event_ids:
            results = Attendance.objects.filter(
                event_id__in=event_ids
            ).counted().values('event_id').annotate(count=Count('id'))

            for result in results:
                non_tbd_counts[result['event_id']] = result['count']

        # Return list in same order as events
        totals = []
        for event in events:
            present_count = present_counts.get(event.id, 0)
            counted_total = non_tbd_counts.get(event.id, 0)
            totals.append({
                'event_id': event.id,
                'present': present_count,
                'total': counted_total,
                'percentage': (present_count / counted_total * 100) if counted_total > 0 else 0
            })

        return totals



@require_POST
@login_required
def self_attendance_update(request, username, event_pk):
    org_user = get_object_or_404(CustomUser, username=username)
    event = get_object_or_404(Event, pk=event_pk, user=org_user)

    my_person = AccessControl.get_member_person(request.user, org_user)
    if not my_person:
        return HttpResponseForbidden("You are not a member of this organization.")

    attendance = get_object_or_404(Attendance, event=event, person=my_person)
    attendance_type = get_object_or_404(AttendanceType, pk=request.POST.get('attendance_type'))
    attendance.attendance_type = attendance_type
    attendance.save()

    return redirect('syncope:event_detail', username=username, pk=event_pk)




@method_decorator(login_required, name='dispatch')
class AttendanceDeleteView(DeleteView):
    model = Attendance
    template_name = "syncope/attendance_confirm_delete.html"

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs['username']
        self.org_user = get_object_or_404(CustomUser, username=url_username)
        is_admin = AccessControl.can_add_event(
            request.user, self.org_user
        ).filter(person__roles__id=Role.ADMIN).exists()
        if not is_admin:
            return HttpResponseForbidden("Only admins can delete participants.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        event = get_object_or_404(Event, pk=self.kwargs['event_pk'], user=self.org_user)
        return Attendance.objects.filter(event=event)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs['username']
        context['event'] = self.object.event
        context['is_admin'] = True
        return context

    def get_success_url(self):
        return reverse_lazy('syncope:event_update', kwargs={
            'username': self.kwargs['username'],
            'pk': self.kwargs['event_pk'],
        })


@require_POST
@login_required
def quick_add_rehearsal(request, username):
    """Quickly create a rehearsal event with all members marked as absent."""
    org_user = get_object_or_404(CustomUser, username=username)

    # Check permissions
    if request.user != org_user:
        if not AccessControl.can_edit_event(request.user, org_user).exists():
            return HttpResponseForbidden("No permission")

    with transaction.atomic():
        # Get or create "Rehearsal" event type
        rehearsal_type, _ = EventType.objects.get_or_create(
            name='Rehearsal',
        )

        # Create event
        event = Event.objects.create(
            user=org_user,
            name=f"Rehearsal",  ### {timezone.now().strftime('%B %d, %Y')} - Do we want rehearsal titles with date?
            event_type=rehearsal_type,
            started_at=timezone.now(),
            ended_at=timezone.now() + timedelta(hours=3),
            location="usual"
        )

        # Get all active members as of today
        members = Person.objects.active_performers(org_user, timezone.now().date())

        # Get the "TBD" attendance type
        unknown_type = AttendanceType.objects.get(pk=AttendanceType.TBD)

        # Create attendance records for all members (default: TBD)
        attendance_records = [
            Attendance(
                event=event,
                person=member,
                attendance_type=unknown_type
            )
            for member in members
        ]
        Attendance.objects.bulk_create(attendance_records)

        messages.success(request, f"Rehearsal created with {len(attendance_records)} members!")

    # Redirect back to dashboard
    return redirect('syncope:attendance', username=username)

