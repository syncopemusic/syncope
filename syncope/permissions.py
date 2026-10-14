# permissions.py

from django.db.models import Q

from .models import Organization, Role, Person, CustomUser, Membership, MembershipPeriod, Song, PersonRole


class AccessControl:
    """
    Centralized access control for the application.
    All permission checks go through this class.
    """

    # centralized list of rights
    ROLE_PERMISSIONS = {
        Role.ADMIN: {"view", "create", "update", "delete"},
        Role.MEMBER: {"view"},
        Role.SUPPORTER: set(),
        Role.EXTERNAL: set(),
    }

    # BASIC HELPERS -------------------------------------------------------------------

    @classmethod
    def get_auth_person(cls, auth_user):
        """
        Get the viewer's personal Person profile.
        This Person is directly linked to their auth account (and not to the org).
        Args: auth_user: the authenticated CustomUser
        Returns: Person object or None
        """
        if not auth_user.is_authenticated:
            return None

        return Person.objects.get(
            user=auth_user,
            owner__isnull=True
        )  # Raises exteption if not found


    @classmethod
    def get_username(cls, url_username):
        """Get CustomUser from URL."""

        try:
            return CustomUser.objects.get(username=url_username)
        except CustomUser.DoesNotExist:
            return None

    #   ----------------------------------------------------------

    @classmethod
    def get_org_roles(cls, user, url_username):
        """
        Get viewer's role in an organization.

        Two cases:
        1. User viewing their own memberships -> return ADMIN role
        2. User's person owns a person with membership in this org -> return that person's roles

        Args:
            user: Viewer's CustomUser
            url_username: Organization username being viewed

        Returns:
            QuerySet of Role objects
        """

        if not user.is_authenticated:
            return Role.objects.none()

        # Case 1: User viewing their own memberships
        if user.username == url_username:
            return Role.objects.filter(id=Role.ADMIN)

        # Case 2: User's person owns a person with membership in this org
        auth_person = cls.get_auth_person(user)
        if not auth_person:
            return Role.objects.none()

        # Find a person owned by auth_person that has a membership in the target org
        membership = Membership.objects.filter(
            user__username=url_username,
            person__owner=auth_person
        ).select_related('person').first()

        if not membership:
            return Role.objects.none()

        return membership.person.roles.all()





    @classmethod
    def org_role_ids(cls, auth_user, url_username):
        """Role ids the viewer holds in the org (ADMIN for the org's own account); empty for strangers."""
        try:
            return set(cls.get_org_roles(auth_user, url_username).values_list('id', flat=True))
        except Person.DoesNotExist:
            return set()

    @classmethod
    def sees_rehearsals(cls, auth_user, url_username):
        """Rehearsals (and attendance) are for ADMIN and MEMBER only; supporters get the other event types."""
        return bool(cls.org_role_ids(auth_user, url_username) & {Role.ADMIN, Role.MEMBER})

    @classmethod
    def _user_memberships(cls, auth_user):
        """
        Get all memberships where auth_user is involved.
        This includes:
        - Direct memberships (auth_user is the user)
        - Org memberships (auth_user owns a person in an org)
        """
        if not auth_user.is_authenticated:
            return Membership.objects.none()

        # Get the personal profile (owner=NULL)
        personal_profile = cls.get_auth_person(auth_user)
        if not personal_profile:
            return Membership.objects.none()

        # Find memberships where the person is owned by this personal profile
        return Membership.objects.filter(
            person__owner=personal_profile
        ).select_related("user", "person")

    @classmethod
    def get_member_person(cls, auth_user, org_user):
        """
        Return auth_user's Person record within org_user's organization, or None.
        Reuses _user_memberships to follow the same ownership chain used elsewhere.
        """
        if not auth_user.is_authenticated:
            return None
        membership = cls._user_memberships(auth_user).filter(
            user=org_user
        ).select_related('person').first()
        return membership.person if membership else None


    @classmethod
    def has_permission(cls, auth_user, action, url_username):
        """
            Check if a user has permission to perform an action.
            Args:
                auth_user: CustomUser instance (the viewer)
                action: String action name (e.g., 'view', 'create', 'update', 'delete')
                url_username: Username from URL (the context)
            Returns:
                Boolean indicating whether user has the specified permission
            """
        try:
            CustomUser.objects.get(username=url_username)
        except CustomUser.DoesNotExist:
            return False

        roles = cls.get_org_roles(auth_user, url_username)
        if not roles.exists():
            return False

        # Check if ANY of the user's roles grants the permission
        for role in roles:
            role_permissions = cls.ROLE_PERMISSIONS.get(role.id, set())
            if action in role_permissions:
                return True

        return False


    @classmethod
    def can_view_member_list(cls, auth_user, url_username):
        """
        Return queryset of Memberships that auth_user can view:
        - Personal memberships if owner_user is same as auth_user
        - Or org memberships if auth_user is ADMIN or MEMBER of that org
        """
        if not auth_user.is_authenticated:
            return Membership.objects.none()

        # personal memberships
        if url_username == auth_user:
            return Membership.objects.filter(user=auth_user)

        # org memberships - check if auth_user has proper role
        memberships = cls._user_memberships(auth_user).filter(
            user=url_username,  # Memberships under owner_user's "org"
            person__roles__id__in=[Role.ADMIN, Role.MEMBER]
        )
        if not memberships.exists():
            return Membership.objects.none()

        return Membership.objects.filter(user=url_username)


    @classmethod
    def get_viewable_people_queryset(cls, auth_user):
        """
        Get all Person objects from organizations where the user is a member.
        Args:  auth_user: CustomUser instance
        Returns: QuerySet of Person objects from user's organizations
        Note: Returns people who are linked to users that are members of the same organizations
        """
        if not auth_user.is_authenticated:
            return Person.objects.none()

        # Get all Person profiles from orgs where auth_user is a member
        org_user_ids = cls._user_memberships(auth_user).values_list("user_id", flat=True)

        return Person.objects.filter(
            memberships__user_id__in=org_user_ids,  # Person is in these orgs
            owner__isnull=False  # Exclude personal profiles
        ).distinct()


    @classmethod
    def filter_person_details(cls, auth_user, person, url_username):
        """
        Filter person details based on the viewer's role.
        Args:
            auth_user: The viewer
            person: Person object being viewed
            url_username: Username from URL (the context)
        Returns:
            Dictionary with allowed fields or None
        """
        target_user = cls.get_username(url_username)
        if not target_user:
            return None

        membership = cls._user_memberships(auth_user).filter(
            user=target_user
        ).select_related("person").first()

        if not membership:
            return None

        # Check if the person being viewed is in the same context
        person_in_context = Membership.objects.filter(
            user=target_user,
            person=person
        ).exists()

        if not person_in_context:
            return None

        # Get viewer's roles
        viewer_roles = membership.person.roles.values_list('id', flat=True)

        base_data = {
            "first_name": person.first_name,
            "last_name": person.last_name,
            "skills": person.skills.values_list("title", flat=True),
        }

        if Role.ADMIN in viewer_roles:
            return {
                **base_data,
                "email": person.email,
                "phone": person.phone,
                "address": person.address,
                "birth_date": person.birth_date,
                "created_at": person.created_at,
                "updated_at": person.updated_at,
            }

        if Role.MEMBER in viewer_roles:
            return base_data

        return None

    @classmethod
    def get_visible_members(cls, auth_user, url_username):
        """
        Memberships of an organization visible to a user, by membership periods.
        Viewer's role = highest role among their active periods in the org.
            - ADMIN: everyone (incl. past members and supporters)
            - MEMBER: active admins and members, plus externals
            - SUPPORTER: active admins, plus externals
            - EXTERNAL / none: nobody
        Externals = persons who never held admin/member/supporter in the org.
        """
        if isinstance(url_username, CustomUser):
            url_user = url_username
        else:
            url_user = cls.get_username(url_username)
            if url_user is None:
                return Membership.objects.none()

        memberships = Membership.objects.filter(
            user=url_user
        ).select_related("person").prefetch_related("person__roles")

        if auth_user.is_authenticated and auth_user == url_user:
            return memberships

        auth_person = cls.get_auth_person(auth_user)
        viewer_role_ids = set(MembershipPeriod.objects.filter(
            user=url_user, person__owner=auth_person, ended_at__isnull=True,
        ).values_list('role_id', flat=True)) if auth_person else set()

        if Role.ADMIN in viewer_role_ids:
            return memberships

        if Role.MEMBER in viewer_role_ids:
            visible_roles = [Role.ADMIN, Role.MEMBER]
        elif Role.SUPPORTER in viewer_role_ids:
            visible_roles = [Role.ADMIN]
        else:
            return Membership.objects.none()

        periods = MembershipPeriod.objects.filter(user=url_user)
        active = periods.filter(role_id__in=visible_roles, ended_at__isnull=True)
        ever_non_external = periods.filter(
            role_id__in=[Role.ADMIN, Role.MEMBER, Role.SUPPORTER])
        return memberships.filter(
            Q(person_id__in=active.values('person_id')) |
            ~Q(person_id__in=ever_non_external.values('person_id'))
        )

    @classmethod
    def can_view_song(cls, auth_user, song):
        """
        Admin + Member can view songs
        Supporter/External do not
        Include both organizational or individual song owners.
        """
        if not auth_user.is_authenticated:
            return False

        owner_user = song.user

        # Check if song belongs to an organization
        org = Organization.objects.filter(user=owner_user).first()
        if org:
            memberships = cls._user_memberships(auth_user).filter(
                user=org.user,
                person__roles__id__in=[Role.ADMIN, Role.MEMBER]
            )
            return memberships.exists()

        # Personal song - only owner can view
        return owner_user == auth_user

    @classmethod
    def can_view_song_list(cls, auth_user, owner_user):
        """
        Return queryset of Songs that auth_user can view:
        - Personal songs if owner_user is same as auth_user
        - Or org songs if auth_user is ADMIN or MEMBER of that org
        """
        if not auth_user.is_authenticated:
            return Song.objects.none()

        # personal songs
        if owner_user == auth_user:
            return Song.objects.filter(user=auth_user)

        # org songs
        org = Organization.objects.filter(user=owner_user).first()
        if not org:
            return Song.objects.none()

        memberships = cls._user_memberships(auth_user).filter(
            user=owner_user,
            person__roles__id__in=[Role.ADMIN, Role.MEMBER]
        )
        if not memberships.exists():
            return Song.objects.none()

        return Song.objects.filter(user=org.user)

    @classmethod
    def can_manage_song(cls, auth_user, song):
        """
        Returns True if auth_user can create/update/delete the given song.
        Rules:
        - Personal songs: owner must be auth_user
        - Org songs: auth_user must be ADMIN in the org
        """
        if not auth_user.is_authenticated:
            return False

        owner_user = song.user

        # Check if owner_user represents an organization
        org = Organization.objects.filter(user=owner_user).first()

        if not org:
            # Personal songs - only owner can manage
            return auth_user == owner_user

        # Organizational songs - must be ADMIN
        roles = cls.get_org_roles(auth_user, org.user.username)
        return roles.filter(id=Role.ADMIN).exists()

    @classmethod
    def _memberships_with_roles(cls, auth_user, url_username, role_ids):
        """
        Shared shape for the event-permission queryset methods below:
        - Personal memberships if url_username is the viewer themselves
        - Or org memberships if auth_user holds one of `role_ids` in that org
        """
        if not auth_user.is_authenticated:
            return Membership.objects.none()

        # personal memberships
        if url_username == auth_user:
            return Membership.objects.filter(user=auth_user)

        # org memberships - check if auth_user has proper role
        memberships = cls._user_memberships(auth_user).filter(
            user=url_username,  # Memberships under owner_user's "org"
            person__roles__id__in=role_ids
        )
        if not memberships.exists():
            return Membership.objects.none()

        return Membership.objects.filter(user=url_username)

    @classmethod
    def can_add_event(cls, auth_user, url_username):
        """
        Return queryset of Memberships that auth_user can view:
        - Personal memberships if owner_user is same as auth_user
        - Or org memberships if auth_user is ADMIN of that org
        """
        return cls._memberships_with_roles(auth_user, url_username, [Role.ADMIN])  # , Role.MEMBER

    @classmethod
    def can_edit_event(cls, auth_user, url_username):
        """
        Memberships that may change attendance, imports and members' details in the org (ADMIN only;
        MEMBERs are read-only, see can_view_event_attendance).
        """
        return cls._memberships_with_roles(auth_user, url_username, [Role.ADMIN])

    @classmethod
    def can_view_event_attendance(cls, auth_user, url_username):
        """Memberships that may view attendance and member details (ADMIN, MEMBER) without editing."""
        return cls._memberships_with_roles(auth_user, url_username, [Role.ADMIN, Role.MEMBER])

    @classmethod
    def can_view_event_content(cls, auth_user, url_username):
        """
        Return queryset of Memberships that can view an event's songs/meta content
        (not necessarily attendance). ADMIN, MEMBER, and SUPPORTER roles qualify;
        EXTERNAL does not.
        """
        return cls._memberships_with_roles(auth_user, url_username, [Role.ADMIN, Role.MEMBER, Role.SUPPORTER])

    @classmethod
    def _is_admin_for_org(cls, auth_user, url_username):
        """
        Check if auth_user is ADMIN in the organization.
        """
        if not auth_user.is_authenticated:
            return False

        roles = cls.get_org_roles(auth_user, url_username)
        return roles.filter(id=Role.ADMIN).exists()

    @classmethod
    def can_delete_project(cls, auth_user, url_username):
        """
        Check if auth_user can delete a project in the organization.
        Only ADMIN role can delete projects.
        """
        return cls._is_admin_for_org(auth_user, url_username)

    @classmethod
    def can_edit_project(cls, auth_user, url_username):
        """
        Check if auth_user can edit a project (meta fields, or its events/songs/guests).
        Only ADMIN role can edit projects.
        """
        return cls._is_admin_for_org(auth_user, url_username)

    @classmethod
    def can_manage_invite(cls, auth_user, url_username):
        """
        Check if auth_user can accept or create an invitation in the organization.
        Only ADMIN role can accept or create invitations.
        """
        return cls._is_admin_for_org(auth_user, url_username)

    @classmethod
    def is_person_owner(cls, auth_user, person):
        """
        Check if auth_user owns the given person record.
        A person is owned by a user if its owner field points to that user.
        """
        return person.owner_id is not None and person.owner.user_id == auth_user.id