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
from .models import Event, Attendance, EventSong, Song
from .views.drafts import DraftMixin as BaseDraftMixin
from .utils import YES_NO, filter_qs, parse_filters


class ListFilterMixin:
    """Filter panel for a list view. Set filter_spec (see parse_filters) and implement apply_filters; the page and its
    *ListSearchView subclass then share the filtering. filter_options() adds the panel's option lists to the context."""
    filter_spec = {}
    with_filter_options = True  # False on the *ListSearchView subclasses: their results partial has no panel

    def get_filters(self):
        return parse_filters(self.request.GET, self.filter_spec)

    def apply_filters(self, queryset, filters):
        return queryset

    def filter_options(self):
        return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.get_filters()
        if self.with_filter_options:
            context.update(self.filter_options())
        context.update(filters=filters, filter_qs=filter_qs(filters), filter_yes_no=YES_NO)
        return context


class SongOwnerMixin:
    """
    Handles owner fetching for all song views.
    Detail/Update/Delete/Create: also checks permission using permission_check_method.
    ListView just fetches owner_user; its queryset filters.
    """
    permission_check_method = None  # assign in view if needed

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        url_username = self.kwargs.get("username")
        self.owner_user = get_object_or_404(CustomUser, username=url_username)

    def dispatch(self, request, *args, **kwargs):
        # Enforce for every view on one song (Detail/Update/Delete) and for Create, which checks a song of this owner.
        if self.permission_check_method:
            if isinstance(self, CreateView):
                song = Song(user=self.owner_user)
            elif "pk" in self.kwargs and hasattr(self, "get_object"):
                song = super().get_object(queryset=self.get_queryset())
            else:
                song = None  # list views filter in get_queryset
            if song is not None and not self.permission_check_method(request.user, song):
                raise PermissionDenied("You do not have permission")
        return super().dispatch(request, *args, **kwargs)


class SkillListAndCreateMixin(BaseDraftMixin, FormMixin, ListView):
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


