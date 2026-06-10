# ========================================================================
# INVITATION FEATURE: CRUD / ACCEPT / REJECT / WITHDRAW
# ========================================================================
# Purpose: Manage invitations and requests between Users and Organizations.
#
# Domain Model:
#   - CustomUser: auth account. Orgs have a CustomUser (Organization.user) that never logs in.
#                 Users have their own CustomUser with a personal Person (user=CustomUser, owner=None).
#   - Organization.user: the org's CustomUser ("auth hook").
#   - Invitation.sender/recipient/reviewed_by: all FKs to CustomUser.
#
# Two invitation types:
#   - INVITE (InvitationType=1): Org admin invites a user to join.
#     sender = org.user (CustomUser) → recipient = invited_user (CustomUser)
#   - REQUEST (InvitationType=2): User requests to join an org.
#     sender = requesting_user (CustomUser) → recipient = org.user (CustomUser)
#
# Invitation lifecycle:
#   PENDING → APPROVED | REJECTED | WITHDRAWN (sender-initiated revoke)
#
# When an org admin acts (create, accept, reject), reviewed_by = their personal CustomUser
# (found via Membership/MembershipPeriod with role=ADMIN, then Person.user).
#
# SCOPE (THIS SLICE):
#   - CRUD: list, create, detail, accept, reject, withdraw invitations.
#   - Permission checks via AccessControl.has_permission() / .get_org_roles().
#   - OUT OF SCOPE: Person/Membership linking on accept (future), notifications (future).
#
# ========================================================================
# IMPLEMENTATION OUTLINE
# ========================================================================
#
# FORMS (syncope/forms.py - new InvitationCreateForm):
#   recipient_username (CharField): exact-match lookup of CustomUser username
#   expires_at (DateTimeField, optional): when the invitation expires
#   Clean: check username exists → generic "not found" error (no user enumeration)
#          pre-validate unique_pending_invitation_per_pair constraint
#
# VIEWS (invitation.py):
#
#   InvitationListView (GET <str:username>/invitations/)
#     - Permission: AccessControl.has_permission(user, 'delete', username)
#     - Context: pending_invitations, closed_invitations (APPROVED/REJECTED/WITHDRAWN)
#     - All invitations where sender=url_user OR recipient=url_user
#
#   InvitationCreateView (GET/POST <str:username>/invitations/new/)
#     - Permission: same as InvitationListView
#     - Determine type: is url_username an Organization? → INVITE : REQUEST
#     - Form: InvitationCreateForm
#     - POST success: create Invitation, redirect to invitation_list
#
#   InvitationDetailView (GET <str:username>/invitations/<pk>/)
#     - Permission: request.user is sender or recipient (or org admin if recipient is org)
#     - Context: invitation + computed action permissions (can_accept, can_reject, can_withdraw)
#     - Show conditional action buttons (simple POST forms)
#
#   InvitationAcceptView (POST <str:username>/invitations/<pk>/accept/)
#     - Permission: request.user is recipient (or org admin if recipient is org)
#     - Guard: status == PENDING
#     - Action: set status=APPROVED, reviewed_by=request.user, reviewed_at=now()
#     - POST only, no GET. Redirect to invitation_list.
#
#   InvitationRejectView (POST <str:username>/invitations/<pk>/reject/)
#     - Permission: request.user is recipient (or org admin if recipient is org)
#     - Guard: status == PENDING
#     - Action: set status=REJECTED, reviewed_by=request.user, reviewed_at=now()
#     - Redirect to invitation_list.
#
#   InvitationWithdrawView (POST <str:username>/invitations/<pk>/withdraw/)
#     - Permission: request.user is sender (personal match only, not org-delegated)
#     - Guard: status == PENDING
#     - Action: set status=WITHDRAWN, reviewed_by=request.user, reviewed_at=now()
#     - Redirect to invitation_list.
#
# URLs (syncope/urls.py - mirror <str:username>/members/... pattern):
#   <str:username>/invitations/               → InvitationListView (name='invitation_list')
#   <str:username>/invitations/new/           → InvitationCreateView (name='invitation_create')
#   <str:username>/invitations/<int:pk>/      → InvitationDetailView (name='invitation_detail')
#   <str:username>/invitations/<int:pk>/accept/   → InvitationAcceptView (name='invitation_accept')
#   <str:username>/invitations/<int:pk>/reject/   → InvitationRejectView (name='invitation_reject')
#   <str:username>/invitations/<int:pk>/withdraw/ → InvitationWithdrawView (name='invitation_withdraw')
#
# TEMPLATES (syncope/templates/syncope/):
#   invitation_list.html
#     - Table: type | counterpart (sender or recipient) | status | created_at | [detail link]
#     - Sections: "Pending Invitations" | "Closed Invitations"
#     - Create button (for admins of the org)
#
#   invitation_form.html
#     - Form: recipient_username (required), expires_at (optional)
#     - Form errors include unique_pending_invitation validation message
#
#   invitation_detail.html
#     - Details: sender, recipient, type, status, created_at, expires_at
#     - Closed invitations: reviewed_by, reviewed_at
#     - Conditional POST buttons:
#       * Accept (if recipient AND status=PENDING)
#       * Reject (if recipient AND status=PENDING)
#       * Withdraw (if sender AND status=PENDING)
#
# ========================================================================
