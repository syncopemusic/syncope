from django.http import HttpResponseForbidden
from django.shortcuts import  get_object_or_404
from django.urls import reverse
from datetime import date
from django.views.generic import ListView, CreateView, UpdateView,  DetailView
from django.views.generic.edit import DeleteView
from django.db.models import Count, Q
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.contrib import messages
from syncope.models import CustomUser,  Person,  Role
from syncope.models import Event,  EventType,   Project, EventSongResource, ProjectResource, Resource
from syncope.forms import  ProjectForm
from syncope.forms import  AddEventToProjectForm
from syncope.forms import AddSongToProjectForm, AddGuestToProjectForm, ProjectResourceFormSet
from syncope.utils import resource_icon_list
from syncope.permissions import AccessControl
from syncope.views.drafts import DraftMixin, clear_draft


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


@require_POST
@login_required
def project_add_event(request, username, pk):
    org_user = get_object_or_404(CustomUser, username=username)
    project = get_object_or_404(Project, pk=pk, user=org_user)

    is_admin = AccessControl.can_add_event(
        request.user, org_user
    ).filter(person__roles__id=Role.ADMIN).exists()
    if not is_admin:
        return HttpResponseForbidden("Only admins can add events to projects.")

    form = AddEventToProjectForm(request.POST, org_user=org_user, project=project)
    if form.is_valid():
        event = form.cleaned_data['event']
        event.project = project
        event.save()

    return redirect('syncope:project_update', username=username, pk=pk)


@require_POST
@login_required
def project_remove_event(request, username, pk, event_pk):
    org_user = get_object_or_404(CustomUser, username=username)
    project = get_object_or_404(Project, pk=pk, user=org_user)
    event = get_object_or_404(Event, pk=event_pk, project=project)

    is_admin = AccessControl.can_add_event(
        request.user, org_user
    ).filter(person__roles__id=Role.ADMIN).exists()
    if not is_admin:
        return HttpResponseForbidden("Only admins can remove events from projects.")

    event.project = None
    event.save()

    return redirect('syncope:project_update', username=username, pk=pk)


@require_POST
@login_required
def project_add_song(request, username, pk):
    org_user = get_object_or_404(CustomUser, username=username)
    project = get_object_or_404(Project, pk=pk, user=org_user)

    form = AddSongToProjectForm(request.POST, org_user=org_user, project=project)
    if form.is_valid():
        project.songs.add(form.cleaned_data['song'])

    return redirect('syncope:project_update', username=username, pk=pk)


@require_POST
@login_required
def project_remove_song(request, username, pk, song_pk):
    org_user = get_object_or_404(CustomUser, username=username)
    project = get_object_or_404(Project, pk=pk, user=org_user)
    project.songs.remove(song_pk)

    return redirect('syncope:project_update', username=username, pk=pk)


@require_POST
@login_required
def project_add_guest(request, username, pk):
    org_user = get_object_or_404(CustomUser, username=username)
    project = get_object_or_404(Project, pk=pk, user=org_user)

    form = AddGuestToProjectForm(request.POST, org_user=org_user, project=project)
    if form.is_valid():
        project.guests.add(form.cleaned_data['guest'])

    return redirect('syncope:project_update', username=username, pk=pk)


@require_POST
@login_required
def project_remove_guest(request, username, pk, guest_pk):
    org_user = get_object_or_404(CustomUser, username=username)
    project = get_object_or_404(Project, pk=pk, user=org_user)
    project.guests.remove(guest_pk)

    return redirect('syncope:project_update', username=username, pk=pk)




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
        return reverse('syncope:project_update', kwargs={'username': self.kwargs.get('username'), 'pk': self.object.pk})

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
class ProjectUpdateView(DraftMixin, LoginRequiredMixin, SelectPersonInitialMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = 'syncope/project_update.html'
    success_url = None
    person_preset_map = {
        'select_person': 'guest',
        'select_song': 'song',
        'select_event': 'event',
    }

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        return Project.objects.filter(user=org_user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        kwargs['user'] = org_user
        return kwargs

    def get_success_url(self):
        return reverse('syncope:project_detail', kwargs={'username': self.kwargs.get('username'), 'pk': self.object.pk})

    def _save_resources(self, project, resource_formset):
        project.project_resource.all().delete()
        valid_forms = [
            f for f in resource_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
        ]
        for idx, f in enumerate(valid_forms):
            url = f.cleaned_data['url']
            description = f.cleaned_data.get('description', '')
            resource, created = Resource.objects.get_or_create(
                url=url,
                defaults={'owner': self.request.user, 'description': description}
            )
            if not created:
                resource.description = description
                resource.save(update_fields=['description'])
            ProjectResource.objects.create(project=project, resource=resource, order=idx + 1)

    def form_valid(self, form):
        self.object = form.save()
        rf = ProjectResourceFormSet(
            self.request.POST, instance=self.object, user=self.request.user
        )
        if rf.is_valid():
            self._save_resources(self.object, rf)

        clear_draft(self.request, self.get_draft_key())
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        project = self.object

        event_search_q = self.request.GET.get('event_q', '')
        song_search_q = self.request.GET.get('song_q', '')
        guest_search_q = self.request.GET.get('guest_q', '')

        context['url_username'] = url_username
        context['is_admin'] = AccessControl.has_permission(self.request.user, 'delete', url_username)
        context['event_search_q'] = event_search_q

        # Add events with resource counts to context
        events = list(project.events.all().order_by('started_at'))
        for event in events:
            event.resource_count = event.event_resource.count()
            event.event_song_resource_count = EventSongResource.objects.filter(
                event_song__event=event
            ).count()
        context['events'] = events

        presets = self._get_initial_with_presets()
        context['add_event_form'] = AddEventToProjectForm(
            org_user=org_user,
            project=project,
            search_q=event_search_q,
            initial={'event': presets['event']} if 'event' in presets else {},
        )
        context['song_search_q'] = song_search_q
        context['guest_search_q'] = guest_search_q
        context['add_song_form'] = AddSongToProjectForm(
            org_user=org_user,
            project=project,
            search_q=song_search_q,
            initial={'song': presets['song']} if 'song' in presets else {},
        )
        context['add_guest_form'] = AddGuestToProjectForm(
            org_user=org_user,
            project=project,
            search_q=guest_search_q,
            initial={'guest': presets['guest']} if 'guest' in presets else {},
        )

        # Add resource formset
        if self.request.POST:
            context['resource_formset'] = ProjectResourceFormSet(
                self.request.POST, instance=project, user=self.request.user
            )
        else:
            context['resource_formset'] = ProjectResourceFormSet(
                instance=project, user=self.request.user
            )

        return context


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
        context['url_username'] = self.kwargs.get('username')
        project = self.object

        # Get events ordered by start date and attach resource counts
        events = list(project.events.all().order_by('started_at'))
        for event in events:
            event.resource_count = event.event_resource.count()
            event.event_song_resource_count = EventSongResource.objects.filter(
                event_song__event=event
            ).count()
        context['events'] = events

        # Get songs
        context['songs'] = project.songs.all().order_by('title')

        # Get guests
        context['guests'] = project.guests.all().order_by('last_name', 'first_name')

        # Get members: those active at any point during project's date range
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)

        if project.start_date:
            reference_date = project.start_date
        else:
            reference_date = date.today()

        # Query: persons who have a membership period that overlaps with project date range
        # If project has no end_date, use today as the upper bound for the query
        end_date = project.end_date if project.end_date else date.today()

        members = Person.objects.filter(
            membership_period__user=org_user,
            membership_period__role_id=Role.MEMBER,
            membership_period__started_at__lte=end_date,
        ).filter(
            Q(membership_period__ended_at__gte=reference_date) |
            Q(membership_period__ended_at__isnull=True)
        ).distinct().order_by('last_name', 'first_name')

        context['members'] = members

        # Add project resources
        context['project_resources'] = resource_icon_list(project.project_resource.all().order_by('order'))

        # Check if user can delete this project
        context['can_delete'] = AccessControl.can_delete_project(self.request.user, url_username)

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
