from django.views.generic import ListView, DetailView, UpdateView, View
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import HttpResponseForbidden
from syncope.models import CustomUser, PollAttendance, Poll, PollPerson, PollEvent
from syncope.forms import PollCreateForm, PollPersonForm, PollAttendanceForm, PollEventForm
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


@method_decorator(login_required, name="dispatch")
class PollCreateUpdateView(PollAdminMixin, UpdateView):
    model = Poll
    form_class = PollCreateForm
    template_name = "syncope/poll_create.html"

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

    def get_success_url(self):
        return reverse("syncope:poll_persons", kwargs={
            "username": self.kwargs.get("username"),
            "pk": self.object.pk
        })


@method_decorator(login_required, name="dispatch")
class PollPersonView(PollAdminMixin, View):
    template_name = "syncope/poll_person.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'], user=self.org_user)

    def get(self, request, username, pk):
        form = PollPersonForm(initial={'poll': self.poll}, org_user=self.org_user, poll=self.poll)
        return render(request, self.template_name, {
            'form': form,
            'poll': self.poll,
            'poll_persons': self.poll.poll_persons.select_related('person'),
            'url_username': username,
        })

    def post(self, request, username, pk):
        form = PollPersonForm(request.POST, org_user=self.org_user, poll=self.poll)
        if form.is_valid():
            form.save()
            return redirect('syncope:poll_persons', username=username, pk=pk)
        return render(request, self.template_name, {
            'form': form,
            'poll': self.poll,
            'poll_persons': self.poll.poll_persons.select_related('person'),
            'url_username': username,
        })


@method_decorator(login_required, name="dispatch")
class PollEventView(PollAdminMixin, View):
    template_name = "syncope/poll_event.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.org_user = get_object_or_404(CustomUser, username=kwargs['username'])
        self.poll = get_object_or_404(Poll, pk=kwargs['pk'], user=self.org_user)

    def get(self, request, username, pk):
        form = PollEventForm(initial={'poll': self.poll})
        return render(request, self.template_name, {
            'form': form,
            'poll': self.poll,
            'poll_events': self.poll.poll_events.select_related('event_type'),
            'url_username': username,
        })

    def post(self, request, username, pk):
        form = PollEventForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('syncope:poll_events', username=username, pk=pk)
        return render(request, self.template_name, {
            'form': form,
            'poll': self.poll,
            'poll_events': self.poll.poll_events.select_related('event_type'),
            'url_username': username,
        })


class PollEventAttendanceView(View):
    model = PollAttendance
    form_class = PollAttendanceForm
    template_name = "syncope/poll_attendance.html"

    # lists persons, dates and times, and a radio button for poll_type
    # extra comment optional per person per poll_event
    # accessible to the public using external link


class PollDetailView(DetailView):
    template_name = "syncope/poll_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        return context

    # accessible using special link to public, named "poll share"