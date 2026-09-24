from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from datetime import date
from django.db import transaction
from django.views.generic import ListView, CreateView, UpdateView, DetailView, View
from django.views.generic.edit import DeleteView
from django.db.models import Count, Q
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.contrib import messages
from syncope.models import CustomUser, Person, Role, Song
from syncope.models import Event, EventType, Project, EventSongResource
from syncope.forms import ProjectForm
from syncope.forms import AddEventToProjectForm
from syncope.forms import AddSongToProjectForm, AddGuestToProjectForm
from syncope.utils import resource_icon_list
from syncope.permissions import AccessControl
from syncope.views.drafts import DraftMixin


def project_admin_required(view_func):
    """Resolve org_user/project from the URL and 403 unless the viewer can edit this project.

    Wraps a view of the form `def foo(request, username, pk, **rest)` into one that
    receives `org_user`/`project` directly instead of re-deriving them itself.
    """
    @wraps(view_func)
    def wrapper(request, username, pk, **kwargs):
        org_user = get_object_or_404(CustomUser, username=username)
        project = get_object_or_404(Project, pk=pk, user=org_user)
        if not AccessControl.can_edit_project(request.user, username):
            return HttpResponseForbidden("Only admins can make this change.")
        return view_func(request, org_user=org_user, project=project, **kwargs)
    return wrapper


class ProjectAdminRequiredMixin:
    """Class-based-view counterpart to project_admin_required: resolves org_user/project
    onto self and 403s unless the viewer can edit this project."""

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        self.org_user = get_object_or_404(CustomUser, username=url_username)
        if not AccessControl.can_edit_project(request.user, url_username):
            return HttpResponseForbidden("Only admins can edit this project.")
        self.project = get_object_or_404(Project, pk=self.kwargs['pk'], user=self.org_user)
        return super().dispatch(request, *args, **kwargs)


def _events_with_resource_counts(project):
    """This project's events, ordered by start date, with resource_count/event_song_resource_count attached."""
    events = list(project.events.all().order_by('started_at'))
    for event in events:
        event.resource_count = event.event_resource.count()
        event.event_song_resource_count = EventSongResource.objects.filter(
            event_song__event=event
        ).count()
    return events


def _event_search_results(add_event_form):
    """add_event_form.search_results, annotated with each event's other-project warning (if any)."""
    for event in add_event_form.search_results:
        event.other_project_title = add_event_form.other_project_ids.get(event.pk)
    return add_event_form.search_results


def _project_members(project, org_user):
    """Persons with a membership period active at any point during project's date range,
    minus anyone explicitly removed from this project's participant list."""
    reference_date = project.start_date or date.today()
    end_date = project.end_date or date.today()
    return Person.objects.filter(
        membership_period__user=org_user,
        membership_period__role_id=Role.MEMBER,
        membership_period__started_at__lte=end_date,
    ).filter(
        Q(membership_period__ended_at__gte=reference_date) |
        Q(membership_period__ended_at__isnull=True)
    ).exclude(excluded_from_projects=project).distinct().prefetch_related(
        'singer_set__voice', 'instrumentalist_set__instrument', 'skills'
    )


def _project_participants(project, org_user):
    """Members + guests, deduped (a guest who is also an active member is shown once,
    as a member) and sorted together."""
    participants = list(_project_members(project, org_user))
    member_ids = {p.pk for p in participants}
    for guest in project.guests.all().prefetch_related('singer_set__voice', 'instrumentalist_set__instrument', 'skills'):
        if guest.pk in member_ids:
            continue
        guest.is_guest = True
        participants.append(guest)
    participants.sort(key=lambda p: (p.last_name, p.first_name))
    return participants


def _exclude_ids_from_request(request):
    exclude_raw = request.GET.get('exclude', '')
    return [int(x) for x in exclude_raw.split(',') if x.strip().isdigit()]


@login_required
@project_admin_required
def project_events_search(request, org_user, project):
    """AJAX event search for the Events subpage's add-event picker."""
    search_q = request.GET.get('q', '')
    add_event_form = AddEventToProjectForm(
        org_user=org_user, project=project, search_q=search_q, exclude_ids=_exclude_ids_from_request(request)
    )
    return render(request, 'syncope/project_event_search_results.html', {
        'event_results': _event_search_results(add_event_form),
        'search_q': search_q,
        'project': project,
        'url_username': org_user.username,
    })


@login_required
@project_admin_required
def project_songs_search(request, org_user, project):
    """AJAX song search for the Songs subpage's add-song picker."""
    search_q = request.GET.get('q', '')
    add_song_form = AddSongToProjectForm(
        org_user=org_user, project=project, search_q=search_q, exclude_ids=_exclude_ids_from_request(request)
    )
    return render(request, 'syncope/project_song_search_results.html', {
        'add_song_form': add_song_form,
        'search_q': search_q,
        'project': project,
        'url_username': org_user.username,
    })


@login_required
@project_admin_required
def project_guests_search(request, org_user, project):
    """AJAX guest search for the Participants subpage's add-guest picker."""
    search_q = request.GET.get('q', '')
    add_guest_form = AddGuestToProjectForm(
        org_user=org_user, project=project, search_q=search_q, exclude_ids=_exclude_ids_from_request(request)
    )
    return render(request, 'syncope/project_guest_search_results.html', {
        'add_guest_form': add_guest_form,
        'search_q': search_q,
        'project': project,
        'url_username': org_user.username,
    })


@method_decorator(login_required, name="dispatch")
class ProjectListView(LoginRequiredMixin, ListView):
    model = Project
    template_name = 'syncope/project_list.html'
    context_object_name = 'projects'

    def _get_sort_field(self, default_sort='end_date'):
        """Extract and validate sort parameters from request."""
        sort = self.request.GET.get('sort', default_sort)
        reverse = self.request.GET.get('reverse', 'false') == 'true'

        # If no sort parameter provided, default to descending for backward compatibility
        if 'sort' not in self.request.GET:
            reverse = True

        sort_field_map = {
            'title': 'title',
            'start_date': 'start_date',
            'end_date': 'end_date',
            'events': 'num_main_events',
        }
        sort_field = sort_field_map.get(sort, default_sort)
        if reverse:
            sort_field = '-' + sort_field

        return sort_field, sort, reverse

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        sort_field, _, _ = self._get_sort_field()
        return (
            Project.objects
            .filter(user=org_user)
            .annotate(
                num_main_events=Count(
                    'events',
                    filter=Q(events__event_type_id__in=[
                        EventType.CONCERT,
                        EventType.PERFORMANCE,
                        EventType.RECORDING,
                    ])
                ),
                num_rehearsals=Count(
                    'events',
                    filter=Q(events__event_type_id=EventType.REHEARSAL)
                ),
            )
            .order_by(sort_field)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        _, sort, reverse = self._get_sort_field()
        context['current_sort'] = sort
        context['reverse'] = reverse
        return context


@method_decorator(login_required, name="dispatch")
class ProjectCreateView(DraftMixin, LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'syncope/project_form.html'
    success_url = None

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        return Project.objects.filter(user=org_user)

    def form_valid(self, form):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        form.instance.user = org_user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('syncope:project_meta_edit', kwargs={'username': self.kwargs.get('username'), 'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        kwargs['user'] = org_user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        return context


@method_decorator(login_required, name="dispatch")
class ProjectMetaEditView(ProjectAdminRequiredMixin, UpdateView):
    """Details subpage: title/description/details/dates, resources, and Delete."""
    model = Project
    form_class = ProjectForm
    template_name = 'syncope/project_meta_edit.html'
    success_url = None

    def get_object(self, queryset=None):
        return self.project

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.org_user
        return kwargs

    def get_success_url(self):
        return reverse('syncope:project_detail', kwargs={'username': self.kwargs.get('username'), 'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        return context

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Project updated successfully!")
        return redirect(self.get_success_url())


@method_decorator(login_required, name='dispatch')
class ProjectEventsEditView(ProjectAdminRequiredMixin, View):
    """Events subpage: this project's events, plus a live search to assign more."""
    template_name = 'syncope/project_events_edit.html'

    def get(self, request, *args, **kwargs):
        project = self.project
        search_q = request.GET.get('q', '')
        add_event_form = AddEventToProjectForm(org_user=self.org_user, project=project, search_q=search_q)
        context = {
            'project': project,
            'events': _events_with_resource_counts(project),
            'url_username': self.kwargs.get('username'),
            'search_q': search_q,
            'event_results': _event_search_results(add_event_form),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        project = self.project
        org_user = self.org_user

        with transaction.atomic():
            current_ids = set(project.events.values_list('pk', flat=True))
            remove_ids = {pk for pk in current_ids if request.POST.get(f'remove_{pk}') == '1'}
            if remove_ids:
                Event.objects.filter(pk__in=remove_ids).update(project=None)

            eligible_ids = set(
                Event.objects.filter(user=org_user).exclude(project=project).values_list('pk', flat=True)
            )
            add_ids = {int(v) for v in request.POST.getlist('add_event') if v.isdigit()} & eligible_ids
            if add_ids:
                Event.objects.filter(pk__in=add_ids).update(project=project)

        messages.success(request, "Events updated successfully!")
        return redirect('syncope:project_events_edit', username=self.kwargs.get('username'), pk=project.pk)


@method_decorator(login_required, name='dispatch')
class ProjectSongsEditView(ProjectAdminRequiredMixin, View):
    """Songs subpage: this project's songs, plus a live search to add more."""
    template_name = 'syncope/project_songs_edit.html'

    def get(self, request, *args, **kwargs):
        project = self.project
        search_q = request.GET.get('q', '')
        context = {
            'project': project,
            'songs': project.songs.all().order_by('title'),
            'url_username': self.kwargs.get('username'),
            'search_q': search_q,
            'add_song_form': AddSongToProjectForm(org_user=self.org_user, project=project, search_q=search_q),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        project = self.project
        org_user = self.org_user

        with transaction.atomic():
            current_ids = set(project.songs.values_list('pk', flat=True))
            remove_ids = {pk for pk in current_ids if request.POST.get(f'remove_{pk}') == '1'}
            if remove_ids:
                project.songs.remove(*remove_ids)

            eligible_ids = set(
                Song.objects.filter(user=org_user).exclude(projects=project).values_list('pk', flat=True)
            )
            add_ids = {int(v) for v in request.POST.getlist('add_song') if v.isdigit()} & eligible_ids
            if add_ids:
                project.songs.add(*add_ids)

        messages.success(request, "Songs updated successfully!")
        return redirect('syncope:project_songs_edit', username=self.kwargs.get('username'), pk=project.pk)


@method_decorator(login_required, name='dispatch')
class ProjectParticipantsEditView(ProjectAdminRequiredMixin, View):
    """Participants subpage: this project's members + guests, plus a live search to add more guests."""
    template_name = 'syncope/project_participants_edit.html'

    def get(self, request, *args, **kwargs):
        project = self.project
        search_q = request.GET.get('q', '')
        context = {
            'project': project,
            'participants': _project_participants(project, self.org_user),
            'url_username': self.kwargs.get('username'),
            'search_q': search_q,
            'add_guest_form': AddGuestToProjectForm(org_user=self.org_user, project=project, search_q=search_q),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        project = self.project
        org_user = self.org_user

        with transaction.atomic():
            current_participant_ids = {p.pk for p in _project_participants(project, org_user)}
            remove_ids = {pk for pk in current_participant_ids if request.POST.get(f'remove_{pk}') == '1'}
            if remove_ids:
                guest_ids = set(project.guests.filter(pk__in=remove_ids).values_list('pk', flat=True))
                if guest_ids:
                    project.guests.remove(*guest_ids)
                member_ids = remove_ids - guest_ids
                if member_ids:
                    project.excluded_members.add(
                        *Person.objects.filter(pk__in=member_ids, membership_period__user=org_user)
                    )

            eligible_ids = set(
                Person.objects.filter(membership_period__user=org_user).exclude(
                    projects=project
                ).values_list('pk', flat=True)
            )
            add_ids = {int(v) for v in request.POST.getlist('add_guest') if v.isdigit()} & eligible_ids
            if add_ids:
                project.guests.add(*add_ids)

        messages.success(request, "Participants updated successfully!")
        return redirect('syncope:project_participants_edit', username=self.kwargs.get('username'), pk=project.pk)


@method_decorator(login_required, name="dispatch")
class ProjectDetailView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = 'syncope/project_detail.html'
    context_object_name = 'project'

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        return Project.objects.filter(user=org_user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        url_username = self.kwargs.get('username')
        context['url_username'] = url_username
        project = self.object
        org_user = get_object_or_404(CustomUser, username=url_username)

        context['events'] = _events_with_resource_counts(project)
        context['songs'] = project.songs.all().order_by('title')
        context['participants'] = _project_participants(project, org_user)

        # Add project resources
        context['project_resources'] = resource_icon_list(project.project_resource.all().order_by('order'))

        # Check if user can edit/delete this project
        context['is_admin'] = AccessControl.can_edit_project(self.request.user, url_username)

        return context

@method_decorator(login_required, name="dispatch")
class ProjectDeleteView(LoginRequiredMixin, DeleteView):
    model = Project
    template_name = 'syncope/project_confirm_delete.html'
    success_url = None

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        return Project.objects.filter(user=org_user)

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        if not AccessControl.can_delete_project(request.user, url_username):
            return HttpResponseForbidden("Only admins can delete projects.")
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        project = self.get_object()
        project_title = project.title
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f"Successfully deleted project '{project_title}'.")
        return response

    def get_success_url(self):
        return reverse('syncope:project_list', kwargs={'username': self.kwargs.get('username')})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['can_delete'] = AccessControl.can_delete_project(self.request.user, self.kwargs.get('username'))
        return context
