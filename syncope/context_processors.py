# syncope/context_processors.py
from .models import Membership, Role, Invitation, InvitationStatus
from django.db.models import Q

from .permissions import AccessControl


def user_person(request):
    """Logged-in user's memberships available in every template automatically."""
    context = {
        "person": None,
        "memberships": [],
        "url_username": None,
        "ADMIN_ROLE": Role.objects.get(id=Role.ADMIN),
        "MEMBER_ROLE": Role.objects.get(id=Role.MEMBER),
    }

    if not request.user.is_authenticated:
        return context

    person = request.user.persons.first()
    if not person:
        return context

    context["person"] = person

    # Get username from URL (which org page are we on)
    context["url_username"] = request.resolver_match.kwargs.get("username")

    # get all memberships for this user
    context["memberships"] = list(
        Membership.objects.filter(
            Q(user=request.user) |  # Direct memberships (personal user)
            Q(person__owner=person)  # Org memberships where user owns the person
        )
        .select_related("user", "person")
        .prefetch_related(
            "user__organizations",
            "person__person_role__role"
        )
    )

    # for home page
    context["org_memberships"] = [
        m for m in context["memberships"]
        if m.user != request.user  # Exclude your own org
    ]

    # Compute total pending invitation count for user and all memberships
    user_org_ids = {request.user.id} | {m.user_id for m in context["memberships"]}

    pending_qs = (
        Invitation.objects.filter(
            Q(recipient_id__in=user_org_ids) | Q(sender_id__in=user_org_ids),
            status_id=InvitationStatus.PENDING,
        )
        .values("sender_id", "recipient_id")
    )

    counts = {}
    for row in pending_qs:
        for uid in (row["sender_id"], row["recipient_id"]):
            if uid in user_org_ids:
                counts[uid] = counts.get(uid, 0) + 1

    context["pending_invitations"] = counts.get(request.user.id, 0)

    for membership in context["memberships"]:
        membership.pending_invitations = counts.get(membership.user_id, 0)

    # Derive the single membership relevant to the current page (for child template checks)
    url_username = context["url_username"]
    if url_username:
        context["membership"] = next(
            (m for m in context["memberships"] if m.user.username == url_username),
            None,
        )
    else:
        context["membership"] = next(
            (m for m in context["memberships"] if m.user == request.user),
            None,
        )

    return context
