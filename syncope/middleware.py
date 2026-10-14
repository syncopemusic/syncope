from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from django.http import HttpResponseForbidden

from syncope.models import Role
from syncope.permissions import AccessControl

# Org-scoped pages (URLs with <username>) are readable by ADMIN and MEMBER; every other role only gets what is listed
# here. Write checks stay in the views. Pages outside this gate have their own rules.
_ALL_ROLES = {Role.SUPPORTER, Role.EXTERNAL}
OPEN_TO_OTHER_ROLES = {
    'org_dashboard': _ALL_ROLES,
    'project_list': _ALL_ROLES,
    'project_list_search': _ALL_ROLES,
    'event_list': {Role.SUPPORTER},
    'event_list_search': {Role.SUPPORTER},
    'event_detail': {Role.SUPPORTER},
}
# own-profile, invitation and public poll-vote URLs also carry a username but are not org content
NOT_ORG_CONTENT = {
    'profile_detail', 'person_update', 'profile_account', 'profile_resources',
    'invitation_list', 'invitation_list_search', 'invitation_new', 'invitation_detail',
    'poll_person_attendance',
}


class OrgAccessMiddleware:
    """One read gate for all org pages, instead of a check in every view."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        username = view_kwargs.get('username')
        name = request.resolver_match.url_name
        if not username or name in NOT_ORG_CONTENT or not request.user.is_authenticated:
            return None
        roles = AccessControl.org_role_ids(request.user, username)
        if roles & {Role.ADMIN, Role.MEMBER} or roles & OPEN_TO_OTHER_ROLES.get(name, set()):
            return None
        return HttpResponseForbidden("You don't have access to this page.")


class ProfileCompletionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile_url = reverse(
                'syncope:person_update',
                kwargs={'username': request.user.username}
            )
            exempt_prefixes = [
                profile_url,
                reverse('syncope:login'),
                reverse('syncope:logout'),
            ]
            if not any(request.path.startswith(p) for p in exempt_prefixes):
                from syncope.models import Person
                person = Person.objects.filter(
                    user=request.user, owner=None
                ).first()
                if person and (not person.first_name or not person.last_name):
                    messages.info(
                        request,
                        "Please complete your profile."
                    )
                    return redirect(profile_url)

        return self.get_response(request)
