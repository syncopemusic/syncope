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
from syncope.forms import InvitationForm, InvitationAcceptForm
from syncope.models import (
    CustomUser, Invitation, InvitationType, InvitationStatus, Organization,
    Person, Membership, MembershipPeriod, PersonRole, Role,
    PersonSkill, Singer, Instrumentalist, PersonResource
)
from syncope.permissions import AccessControl
from syncope.views.drafts import DraftMixin
from syncope.utils import bulk_copy_m2m_relations


class SelectPersonInitialMixin:
    person_preset_fields = []
    person_preset_map = {}

    def get_initial(self):
        initial = super().get_initial()
        if self.person_preset_map:
            for query_key, form_key in self.person_preset_map.items():
                pk = self.request.GET.get(query_key)
                if pk:
                    initial[form_key] = pk
        else:
            for field in self.person_preset_fields:
                pk = self.request.GET.get(f'select_{field}')
                if pk:
                    initial[field] = pk
        return initial


class InvitationAccessMixin:
    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")
        self.customuser = get_object_or_404(CustomUser, username=url_username)
        if request.user != self.customuser and not AccessControl.can_manage_invite(request.user, self.customuser.username):
            return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)


# 1. Invitation List
@method_decorator(login_required, name='dispatch')
class InvitationListView(InvitationAccessMixin, ListView):
    model = Invitation
    context_object_name = "invitations"
    template_name = "syncope/invitation_list.html"

    def _get_sort_field(self, prefix='', default_sort='date'):
        """Extract and validate sort parameters from request."""
        sort_param = f'{prefix}_sort' if prefix else 'sort'
        reverse_param = f'{prefix}_reverse' if prefix else 'reverse'
        sort = self.request.GET.get(sort_param, default_sort)
        reverse = self.request.GET.get(reverse_param, 'false') == 'true'

        if sort_param not in self.request.GET:
            reverse = True

        sort_field_map = {
            'date': 'created_at',
            'expires': 'expires_at',
            'type': 'invitation_type',
            'status': 'status',
            'sent_by': 'sender__username',
            'received_by': 'recipient__username',
            'admin': 'admin_involved__username'
        }
        sort_field = sort_field_map.get(sort, 'created_at')
        if reverse:
            sort_field = '-' + sort_field

        return sort_field, sort, reverse

    def get_queryset(self):
        return Invitation.objects.filter(
            Q(sender=self.customuser) | Q(recipient=self.customuser)
        ).select_related("sender", "recipient", "invitation_type", "status", "admin_involved")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = self.get_queryset()

        pending_sort_field, pending_sort, pending_reverse = self._get_sort_field('pending')
        history_sort_field, history_sort, history_reverse = self._get_sort_field('history')

        context['pending_list'] = base_qs.filter(status_id=InvitationStatus.PENDING).order_by(pending_sort_field)
        context['history_invitations'] = base_qs.exclude(status_id=InvitationStatus.PENDING).order_by(history_sort_field)

        context['pending_sort'] = pending_sort
        context['pending_reverse'] = pending_reverse
        context['history_sort'] = history_sort
        context['history_reverse'] = history_reverse
        context['url_username'] = self.customuser.username
        context['is_org'] = Organization.objects.filter(user=self.customuser).exists()

        return context


# 2. Trigger: create invite
@method_decorator(login_required, name="dispatch")
class InvitationCreateView(DraftMixin, InvitationAccessMixin, SelectPersonInitialMixin, CreateView):
    model = Invitation
    form_class = InvitationForm
    template_name = "syncope/invitation_form.html"
    person_preset_map = {'select_person': 'existing_person'}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["customuser"] = self.customuser
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.customuser.username
        context['is_org'] = Organization.objects.filter(user=self.customuser).exists()
        return context

    def form_valid(self, form):
        is_org = Organization.objects.filter(user=self.customuser).exists()

        expires_at = form.cleaned_data.get("expires_at")
        if expires_at and expires_at <= timezone.now():
            messages.error(self.request, "Expiration date must be in the future.")
            return HttpResponseRedirect(self.request.path)

        existing_person = form.cleaned_data.get("existing_person")
        if is_org and existing_person and not existing_person.is_unlinked():
            messages.error(self.request, "This member record is no longer available to link.")
            return HttpResponseRedirect(self.request.path)

        recipient = CustomUser.objects.filter(
            username=form.cleaned_data["recipient_username"]
        ).exclude(pk=self.customuser.pk).first()

        if not recipient:
            messages.error(self.request, "Username not found.")
            return HttpResponseRedirect(self.request.path)

        recipient_is_org = Organization.objects.filter(user=recipient).exists()
        already_pending = Invitation.objects.filter(
            sender=self.customuser, recipient=recipient, status_id=InvitationStatus.PENDING
        ).exists()

        if already_pending:
            messages.error(self.request, "There is already a pending invitation with this user.")
            return HttpResponseRedirect(self.request.path)

        if recipient_is_org == is_org:
            messages.error(
                self.request,
                "Organization can only invite users, and users can only request to join organizations."
            )
            return HttpResponseRedirect(self.request.path)

        org_user = self.customuser if is_org else recipient
        human_user = recipient if is_org else self.customuser

        if AccessControl.get_member_person(human_user, org_user):
            messages.error(self.request, "This user is already a member of the organization.")
            return HttpResponseRedirect(self.request.path)

        form.instance.sender = self.customuser
        form.instance.recipient = recipient
        form.instance.invitation_type_id = InvitationType.INVITE if is_org else InvitationType.REQUEST
        form.instance.status_id = InvitationStatus.PENDING
        if is_org:
            form.instance.admin_involved = self.request.user
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

            extra_update_fields = []

            if invitation.invitation_type_id == InvitationType.INVITE:
                # Recipient (human) decides whether to copy their profile details
                # onto the org's member record.
                invitation.copy_details = request.POST.get("copy_details") == "on"
                extra_update_fields.append("copy_details")
            else:
                # Recipient (org) decides which (if any) existing unlinked member
                # record to link the requester to. copy_details was already set
                # by the requester at creation time and is left as-is.
                accept_form = InvitationAcceptForm(request.POST, organization_user=self.customuser)
                if not accept_form.is_valid():
                    messages.error(self.request, "Invalid selection.")
                    return HttpResponseRedirect(self.request.path)

                existing_person = accept_form.cleaned_data.get("existing_person")
                if existing_person and not existing_person.is_unlinked():
                    messages.error(self.request, "This member record is no longer available to link.")
                    return HttpResponseRedirect(self.request.path)

                invitation.existing_person = existing_person
                extra_update_fields.append("existing_person")

            copy_details = invitation.copy_details
            return self._update_status(
                invitation, InvitationStatus.APPROVED,
                copy_details=copy_details, extra_update_fields=extra_update_fields,
            )

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
        invitation = self.object
        is_pending = invitation.status_id == InvitationStatus.PENDING
        is_request = invitation.invitation_type_id == InvitationType.REQUEST
        is_recipient = self.customuser == invitation.recipient

        context['is_pending'] = is_pending
        context['is_request'] = is_request
        context['url_username'] = self.customuser.username

        if is_pending and is_request and is_recipient:
            context['accept_form'] = InvitationAcceptForm(organization_user=self.customuser)

        return context

    def _update_status(self, invitation, status_id, copy_details=False, extra_update_fields=None):
        with transaction.atomic():
            invitation.status_id = status_id
            invitation.reviewed_at = timezone.now()
            update_fields = ["status", "reviewed_at", "updated_at"]

            if extra_update_fields:
                update_fields.extend(extra_update_fields)

            if invitation.invitation_type_id == InvitationType.REQUEST and status_id in (
                InvitationStatus.APPROVED, InvitationStatus.REJECTED
            ):
                invitation.admin_involved = self.request.user
                update_fields.append("admin_involved")

            invitation.save(update_fields=update_fields)

            if status_id == InvitationStatus.APPROVED:
                self._link_persons(invitation, copy_details=copy_details)

        if status_id == InvitationStatus.APPROVED and invitation.invitation_type_id == InvitationType.INVITE:
            redirect_url = reverse_lazy("syncope:org_dashboard", kwargs={"username": invitation.sender.username})
        else:
            redirect_url = self.get_success_url()
        return HttpResponseRedirect(redirect_url)

    def _link_persons(self, invitation, copy_details):
        if invitation.invitation_type_id == InvitationType.INVITE:
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

        transfer_fields = [
            "first_name", "last_name", "email", "address", "phone",
            "birth_date", "birth_approximate", "death_date", "death_approximate",
        ]

        org_person = invitation.existing_person
        if org_person and not org_person.is_unlinked():
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
                self._copy_skills_voices_instruments(human_person, org_person)
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

        if copy_details:
            self._copy_skills_voices_instruments(human_person, org_person)
            self._copy_resources(human_person, org_person)

        role = Role.objects.get(id=Role.EXTERNAL)
        PersonRole.objects.create(person=org_person, role=role)
        MembershipPeriod.objects.create(
            user=org_user,
            person=org_person,
            role=role,
            started_at=timezone.now().date(),
        )

    def _copy_skills_voices_instruments(self, human_person, org_person):
        bulk_copy_m2m_relations(human_person, org_person, PersonSkill, id_field='skill_id')
        bulk_copy_m2m_relations(human_person, org_person, Singer, id_field='voice_id')
        bulk_copy_m2m_relations(human_person, org_person, Instrumentalist, id_field='instrument_id')

    def _expired(self, invitation):
        messages.error(self.request, "This invitation has expired and can no longer be accepted.")
        return HttpResponseRedirect(self.get_success_url())
