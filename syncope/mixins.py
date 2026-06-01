# mixins.py
from django.http import Http404
from django.views.generic import ListView, DeleteView, CreateView, UpdateView
from django.views.generic.edit import FormMixin
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from .models import Organization, Role, Skill
from .forms import SkillForm
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied
from django.views.generic import DetailView
from .models import CustomUser
from .models import Event, Attendance, EventSong



class SongOwnerMixin:
    """
    Handles owner fetching for all song views.
    For Detail/Update/Delete: also checks permission using permission_check_method.
    ListView/CreateView will just fetch owner_user; queryset/form handle filtering.
    """
    permission_check_method = None  # assign in view if needed

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        url_username = self.kwargs.get("username")
        self.owner_user = get_object_or_404(CustomUser, username=url_username)

    def dispatch(self, request, *args, **kwargs):
        # Only enforce permission for Detail/Update/Delete views
        if self.permission_check_method and hasattr(self, "get_object") and isinstance(self, DetailView):
            song = super().get_object(queryset=self.get_queryset())
            allowed = self.permission_check_method(request.user, song)
            if not allowed:
                raise PermissionDenied("You do not have permission")
        return super().dispatch(request, *args, **kwargs)


class SkillListAndCreateMixin(FormMixin, ListView):
    model = Skill
    form_class = SkillForm
    template_name = "syncope/skill_list.html"
    context_object_name = "skills"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = self.get_form()
        context['is_admin'] = self.request.user.is_superuser or self.request.user.is_staff
        return context

    def post(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        if "delete_skill" in request.POST:
            skill_id = request.POST.get("skill_id")

            skill = get_object_or_404(Skill, id=skill_id)
            skill.delete()
            return redirect(self.get_success_url())
        else:
            form = self.get_form()
            if form.is_valid():
                return self.form_valid(form)
            else:
                return self.form_invalid(form)

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)


