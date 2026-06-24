from django.contrib import messages
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.db.models import Q
from datetime import datetime
from django.views.generic import CreateView, DeleteView, UpdateView
from django.utils.text import slugify
import datetime
from django.views.generic import TemplateView
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from syncope.models import (
    MembershipPeriod, PersonRole, EventSongResource, ProjectResource, ShareVisit,
    PersonSkill, Singer, Instrumentalist, PersonResource,
    CustomUser, Organization, Person, Membership, Role, Song, Event, Project, Poll, Share
)
from syncope.forms import OrganizationForm
from syncope.permissions import AccessControl
from syncope.views.drafts import DraftMixin


class OrgAdminMixin:
    """Resolves org from URL kwarg and restricts access to ADMIN role members."""

    def get_object(self, queryset=None):
        return get_object_or_404(
            Organization.objects.select_related('user'),
            user__username=self.kwargs['username'],
        )

    def dispatch(self, request, *args, **kwargs):
        roles = AccessControl.get_org_roles(request.user, self.kwargs['username'])
        if not roles.filter(id=Role.ADMIN).exists():
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)


@method_decorator(login_required, name='dispatch')
class OrganizationDashboard(TemplateView):
    """Home page for specific organizations."""
    template_name = "syncope/org_dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs["username"]

        self.organization = get_object_or_404(
            Organization,
            user__username=url_username
        )

        self.viewer_roles = AccessControl.get_org_roles(
            request.user,
            url_username
        )

        if not self.viewer_roles:
            return HttpResponseForbidden()

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.organization
        context["url_username"] = self.kwargs["username"]
        context["is_admin"] = self.viewer_roles.filter(id=Role.ADMIN).exists()

        context["org_memberships"] = AccessControl.get_visible_members(
            self.request.user,
            self.kwargs["username"]
        )

        return context


@method_decorator(login_required, name='dispatch')
class OrganizationCreateView(DraftMixin, CreateView):
    template_name = "syncope/org_form.html"
    form_class = OrganizationForm
    context_object_name = "org_create"
    success_url = reverse_lazy("syncope:home")

    def form_valid(self, form):
        # atomic transaction - creates everything at once:
        with transaction.atomic():
            the_admin = Person.objects.filter(user=self.request.user).first()

            # create auth account for org
            org_user = CustomUser.objects.create(
                username=slugify(form.cleaned_data["name"]),
                email=form.cleaned_data["email"],
            )
            org_user.set_unusable_password()
            org_user.save()

            # create org
            organization = form.save(commit=False)
            organization.user = org_user
            organization.save()

            # create admin person of the org
            transfer_fields = [
                "first_name", "last_name", "email", "address", "phone",
                "birth_date", "birth_approximate", "death_date", "death_approximate",
            ]
            person_admin = Person.objects.create(
                owner=the_admin,
                **{field: getattr(the_admin, field) for field in transfer_fields}
            )

            # copy skills, voices, instruments
            skill_ids = PersonSkill.objects.filter(person=the_admin).values_list("skill_id", flat=True)
            voice_ids = Singer.objects.filter(person=the_admin).values_list("voice_id", flat=True)
            instrument_ids = Instrumentalist.objects.filter(person=the_admin).values_list("instrument_id", flat=True)

            PersonSkill.objects.bulk_create([
                PersonSkill(person=person_admin, skill_id=sid) for sid in skill_ids
            ], ignore_conflicts=True)
            Singer.objects.bulk_create([
                Singer(person=person_admin, voice_id=vid) for vid in voice_ids
            ], ignore_conflicts=True)
            Instrumentalist.objects.bulk_create([
                Instrumentalist(person=person_admin, instrument_id=iid) for iid in instrument_ids
            ], ignore_conflicts=True)

            # copy person resources (portfolio)
            human_resources = PersonResource.objects.filter(person=the_admin).values_list('resource_id', 'order')
            org_resource_ids = set(PersonResource.objects.filter(person=person_admin).values_list('resource_id', flat=True))
            PersonResource.objects.bulk_create([
                PersonResource(person=person_admin, resource_id=resource_id, order=order)
                for resource_id, order in human_resources
                if resource_id not in org_resource_ids
            ], ignore_conflicts=True)

            # make an admin role into membership
            membership = Membership.objects.create(
                user=organization.user,
                person=person_admin,
            )

            person_role = PersonRole.objects.create(
                person = person_admin,
                role_id=Role.ADMIN
            )

            # track the admin into period
            MembershipPeriod.objects.create(
                user=organization.user,
                person=person_admin,
                role_id=Role.ADMIN,
                started_at=datetime.date.today()
            )

        return super().form_valid(form)


@method_decorator(login_required, name='dispatch')
class OrganizationUpdateView(DraftMixin, OrgAdminMixin, UpdateView):
    model = Organization
    form_class = OrganizationForm
    template_name = "syncope/org_form.html"

    def get_success_url(self):
        return reverse("syncope:org_dashboard", kwargs={"username": self.kwargs['username']})


@method_decorator(login_required, name='dispatch')
class OrganizationDeleteView(OrgAdminMixin, DeleteView):
    model = Organization
    template_name = "syncope/org_confirm_delete.html"
    success_url = reverse_lazy("syncope:home")


    def delete_object(self, queryset=None):
        org_user = self.object.user

        with transaction.atomic():
            # Delete PROTECT-guarded junction tables first to unblock the cascade
            EventSongResource.objects.filter(
                Q(event_song__event__user=org_user) | Q(resource__owner=org_user)
            ).delete()
            ProjectResource.objects.filter(resource__owner=org_user).delete()

            # Capture person IDs before memberships are gone
            orphaned_person_ids = list(
                Person.objects.filter(memberships__user=org_user, user=None)
                .values_list('id', flat=True)
            )

            # Delete ShareVisit rows that would block cascade (PROTECT constraint)
            ShareVisit.objects.filter(
                Q(share__resource__owner=org_user) |
                Q(share__event__user=org_user) |
                Q(share__project__user=org_user) |
                Q(share__poll__user=org_user) |
                Q(share__song__user=org_user) |
                Q(share__poll_person__poll__user=org_user) |
                Q(share__person__id__in=orphaned_person_ids)
            ).delete()

            # Explicitly delete memberships (persons with user=None are not reached by org_user cascade)
            MembershipPeriod.objects.filter(user=org_user).delete()
            Membership.objects.filter(user=org_user).delete()

            # Delete the orphaned persons themselves
            Person.objects.filter(id__in=orphaned_person_ids).delete()

            # Delete the organization
            self.object.delete()

            # Delete the CustomUser - must be done explicitly since the FK is ON Organization
            # pointing TO CustomUser, so cascade doesn't work in reverse
            org_user.delete()

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        org_name = self.object.name
        self.delete_object()
        messages.success(request, f"Organization '{org_name}' has been deleted.")
        return HttpResponseRedirect(self.success_url)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs['username']
        context['is_admin'] = True
        return context

