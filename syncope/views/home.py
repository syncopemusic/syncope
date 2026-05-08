from django.views import generic
from django.views.generic import  View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import  TemplateView
from syncope.models import Person, Membership
from syncope.mixins import  SkillListAndCreateMixin


class HomeView(generic.TemplateView):
    template_name = "syncope/home.html"


class IndexView(LoginRequiredMixin, TemplateView):
    template_name = "syncope/index2.html"
    model = Person

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["memberships"] = Membership.objects.filter(person__user=user).select_related("user", "person", "role")
        return context


class SkillListAndCreateView(SkillListAndCreateMixin, View):
    pass
