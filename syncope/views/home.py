from django.urls import reverse
from django.views import generic
from django.views.generic import RedirectView, View
from syncope.mixins import SkillListAndCreateMixin


class HomeView(RedirectView):
    """/home/ now just forwards to the user's own dashboard."""
    def get_redirect_url(self, *args, **kwargs):
        return reverse("syncope:org_dashboard", kwargs={"username": self.request.user.username})


class SkillListAndCreateView(SkillListAndCreateMixin, View):
    pass
