from django.views.generic import ListView, DetailView, CreateView
from django.shortcuts import  get_object_or_404

from models import CustomUser
from syncope.models import Poll
from syncope.forms import PollCreateForm


class PollListView(ListView):
    model = Poll
    context_object_name = "polls"
    template_name = "syncope/poll_list.html"

    def get_queryset(self):
        url_username = self.kwargs.get("username")
        customuser = get_object_or_404(CustomUser, username=url_username)
        return Poll.objects.filter(user=customuser).order_by('-updated_at').prefetch_related('user')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class PollCreateView(CreateView):
    model = Poll
    form_class = PollCreateForm
    template_name = "syncope/poll_create.html"

    def form_valid(self, form):
        pass


class PollDetailView(DetailView):
    model = Poll
    template_name = "syncope/poll_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        return context
