from django.views import generic
from django.views.generic import View
from syncope.mixins import SkillListAndCreateMixin


class HomeView(generic.TemplateView):
    template_name = "syncope/home.html"


class SkillListAndCreateView(SkillListAndCreateMixin, View):
    pass
