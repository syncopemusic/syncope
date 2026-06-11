from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, ListView, DetailView
from syncope.forms import InvitationForm
from syncope.models import (
    CustomUser, Invitation, InvitationType, InvitationStatus, Organization,
    Person, Membership, MembershipPeriod, PersonRole, Role
)
from syncope.permissions import AccessControl


class InvitationAccessMixin:
    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if request.user != self.customuser and not AccessControl.can_manage_invite(request.user, self.customuser):
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)


# 1. Invitation List
@method_decorator(login_required, name='dispatch')
class InvitationListView(InvitationAccessMixin, ListView):
    model = Invitation
    context_object_name = "invitations"
    template_name = "syncope/invitation_list.html"

    def _get_sort_field(self, default_sort='date'):
        """Extract and validate sort parameters from request."""
        sort = self.request.GET.get('sort', default_sort)
        reverse = self.request.GET.get('reverse', 'false') == 'true'

        if 'sort' not in self.request.GET:
            reverse = True

        sort_field_map = {
            'date': 'created_at',
            'expires': 'expires_at',
            'type': 'invitation_type',
            'status': 'status',
            'sent_by': 'sender',
            'received_by': 'recipient'
        }
        sort_field = sort_field_map.get(sort, 'created_at')
        if reverse:
            sort_field = '-' + sort_field

        return sort_field, sort, reverse

    def get_queryset(self):
        self._sort_field, self._sort, self._reverse = self._get_sort_field()
        return Invitation.objects.filter(
            Q(sender=self.customuser) | Q(recipient=self.customuser)
        ).select_related("sender", "recipient", "invitation_type", "status").order_by(self._sort_field)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_sort'] = self._sort
        context['reverse'] = self._reverse
        context['url_username'] = self.customuser.username
        return context


# 2. Trigger: create invite
@method_decorator(login_required, name="dispatch")
class InvitationCreateView(InvitationAccessMixin, CreateView):
    model = Invitation
    form_class = InvitationForm
    template_name = "syncope/invitation_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["customuser"] = self.customuser
        return kwargs

    def form_valid(self, form):
        recipient = form.cleaned_data["recipient"]
        is_org = Organization.objects.filter(user=self.customuser).exists()

        if Invitation.objects.filter(
            sender=self.customuser, recipient=recipient, status_id=InvitationStatus.PENDING
        ).exists():
            form.add_error("recipient", "There is already a pending invitation between these accounts.")
            return self.form_invalid(form)

        now = timezone.now()
        expires_at = form.cleaned_data.get("expires_at")
        if expires_at and expires_at <= now:
            form.add_error("expires_at", "Expiration date must be in the future.")
            return self.form_invalid(form)

        person = form.cleaned_data.get("person")
        if is_org and person and (person.owner_id is not None or person.user_id is not None):
            form.add_error("person", "This member record is no longer available to link.")
            return self.form_invalid(form)

        form.instance.sender = self.customuser
        form.instance.invitation_type_id = InvitationType.INVITE if is_org else InvitationType.REQUEST
        form.instance.status_id = InvitationStatus.PENDING

        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("syncope:invitation_list", kwargs={"username": self.customuser.username})


# 3. Response
@method_decorator(login_required, name="dispatch")
class InvitationUpdateView(InvitationAccessMixin, DetailView):
    model = Invitation
    template_name = "syncope/invitation_detail.html"
    context_object_name = "invitation"

    def get_success_url(self):
        return reverse_lazy("syncope:invitation_list", kwargs={"username": self.customuser.username})

    def post(self, request, *args, **kwargs):
        invitation = self.get_object()
        decision = request.POST.get("decision")

        if invitation.status_id != InvitationStatus.PENDING:
            return HttpResponseBadRequest("This invitation has already been resolved.")

        if decision == "accept":
            if self.customuser != invitation.recipient:
                return HttpResponseForbidden()
            if invitation.expires_at and invitation.expires_at <= timezone.now():
                return self._expired(invitation)
            copy_details = request.POST.get("copy_details") == "on"
            return self._update_status(invitation, InvitationStatus.APPROVED, copy_details=copy_details)

        if decision == "reject":
            if self.customuser != invitation.recipient:
                return HttpResponseForbidden()
            return self._update_status(invitation, InvitationStatus.REJECTED)

        if decision == "withdraw":
            if self.customuser != invitation.sender:
                return HttpResponseForbidden()
            return self._update_status(invitation, InvitationStatus.WITHDRAWN)

        return HttpResponseBadRequest("Unknown decision.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_pending'] = self.object.status_id == InvitationStatus.PENDING
        context['url_username'] = self.customuser.username
        return context

    def _update_status(self, invitation, status_id, copy_details=False):
        with transaction.atomic():
            invitation.status_id = status_id
            invitation.reviewed_by = self.request.user
            invitation.reviewed_at = timezone.now()
            invitation.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

            if status_id == InvitationStatus.APPROVED:
                self._link_persons(invitation, copy_details=copy_details)

        return HttpResponseRedirect(self.get_success_url())

    def _link_persons(self, invitation, copy_details):
        is_invite = invitation.invitation_type_id == InvitationType.INVITE
        if is_invite:
            human_user = invitation.recipient
            org_user = invitation.sender
        else:
            human_user = invitation.sender
            org_user = invitation.recipient

        try:
            human_person = Person.objects.get(user=human_user, owner__isnull=True)
        except Person.DoesNotExist:
            messages.warning(
                self.request,
                "Invitation accepted, but the user's personal profile could not be found; "
                "no member record was linked."
            )
            return

        transfer_fields = ["first_name", "last_name", "email", "address", "phone", "birth_date"]

        if is_invite:
            org_person = invitation.person
            if org_person and (org_person.owner_id is not None or org_person.user_id is not None):
                messages.warning(
                    self.request,
                    "The linked member record is no longer available; "
                    "a new member record was created instead."
                )
                org_person = None

            if org_person:
                org_person.owner = human_person
                if copy_details:
                    for field in transfer_fields:
                        setattr(org_person, field, getattr(human_person, field))
                    org_person.save(update_fields=["owner"] + transfer_fields)
                else:
                    org_person.save(update_fields=["owner"])
                Membership.objects.get_or_create(user=org_user, person=org_person)
                return

        create_kwargs = dict(owner=human_person, user=None)
        if copy_details:
            for field in transfer_fields:
                create_kwargs[field] = getattr(human_person, field)
        org_person = Person.objects.create(**create_kwargs)

        Membership.objects.get_or_create(user=org_user, person=org_person)

        role = Role.objects.get(id=Role.EXTERNAL)
        PersonRole.objects.create(person=org_person, role=role)
        MembershipPeriod.objects.create(
            user=org_user,
            person=org_person,
            role=role,
            started_at=timezone.now().date(),
        )

    def _expired(self, invitation):
        messages.error(self.request, "This invitation has expired and can no longer be accepted.")
        return HttpResponseRedirect(self.get_success_url())
