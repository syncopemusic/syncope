# views/organization.py

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from datetime import datetime
from django.views.generic import  CreateView
from django.utils.text import slugify
import datetime
from django.views.generic import  TemplateView
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from syncope.models import MembershipPeriod,  PersonRole
from syncope.models import CustomUser, Organization, Person, Membership, Role
from syncope.forms import OrganizationForm
from syncope.permissions import AccessControl


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

        context["org_memberships"] = AccessControl.get_visible_members(
            self.request.user,
            self.kwargs["username"]
        )

        return context


@method_decorator(login_required, name='dispatch')
class OrganizationCreateView(CreateView):
    template_name = "syncope/organization_form.html"
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
            person_admin = Person.objects.create(
                # user=organization.user,    # this Person belongs to the organization
                owner=the_admin,    #  this person is claimed by the creator of the organization
                email=the_admin.email,
                first_name=the_admin.first_name,
                last_name=the_admin.last_name,
            )

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

