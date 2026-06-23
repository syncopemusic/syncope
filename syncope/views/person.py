from django.http import Http404, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from syncope.forms import PersonForm, PersonResourceFormSet
from django.core.exceptions import PermissionDenied
from django.urls import reverse_lazy, reverse
from datetime import datetime
from django.views.generic import ListView,  UpdateView,  DetailView, FormView
from django.views.generic.edit import DeleteView
from django.db.models import Q, Max, Min, Value
from django.db.models.functions import Coalesce
import datetime
from django.db import transaction
from django.http import HttpResponseRedirect
from syncope.forms import OrgMemberForm
from syncope.models import MembershipPeriod,  PersonSkill,  PersonRole
from syncope.models import CustomUser, Organization, Person, Membership, Role, Skill, Singer, Instrumentalist
from syncope.models import Attendance, AttendanceType, EventType, Voice, Instrument,  Project, LyricsTranslation, PersonResource, Resource
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list

NON_EXTERNAL_ROLES = [Role.ADMIN, Role.MEMBER, Role.SUPPORTER]

SKILL_MAP = {
    'composers': Skill.COMPOSER,
    'poets': Skill.POET,
    'arrangers': Skill.ARRANGER,
    'translators': Skill.TRANSLATOR,
}


def _build_person_queryset(visible_memberships, q=''):
    """Build base person queryset with prefetch and search filtering."""
    queryset = visible_memberships.select_related('person').prefetch_related(
        'person__skills', 'person__roles',
        'person__singer_set__voice', 'person__instrumentalist_set__instrument',
        'person__person_resource__resource',
        'person__membership_period',
    )

    if q:
        queryset = queryset.filter(
            Q(person__first_name__icontains=q) |
            Q(person__last_name__icontains=q) |
            Q(person__skills__title__icontains=q) |
            Q(person__singer__voice__name__icontains=q) |
            Q(person__instrumentalist__instrument__name__icontains=q)
        ).distinct()

    return queryset


def _annotate_person_queryset(queryset):
    """Add performance-related annotations to person queryset."""
    return queryset.annotate(
        first_skill=Min('person__skills__title'),
        first_voice=Min('person__singer__voice__name'),
        first_instrument=Min('person__instrumentalist__instrument__name'),
    ).annotate(
        first_voice_or_instrument=Coalesce('first_voice', 'first_instrument', Value('')),
    )


def _filter_membership_periods_by_status(org_user, status):
    """Filter membership periods by active/inactive/all status."""
    base_query = MembershipPeriod.objects.filter(
        user=org_user,
        role_id__in=NON_EXTERNAL_ROLES
    )
    if status == 'active':
        return base_query.filter(ended_at__isnull=True)
    elif status == 'inactive':
        return base_query.filter(ended_at__isnull=False)
    return base_query


def _apply_person_sort(queryset, request):
    """Apply sorting to person querysets based on GET parameters."""
    sort_field_map = {
        'name': ('person__last_name', 'person__first_name'),
        'email': ('person__email',),
        'skill': ('first_skill',),
        'voice_instrument': ('first_voice_or_instrument',),
    }
    sort_key = request.GET.get('sort', 'name')
    reverse = request.GET.get('reverse', 'false') == 'true'
    fields = sort_field_map.get(sort_key, sort_field_map['name'])
    if reverse:
        fields = tuple(f'-{f}' for f in fields)
    return queryset.order_by(*fields)


@method_decorator(login_required, name='dispatch')
class PersonUpdateView(UpdateView):
    template_name = "syncope/person_form.html"
    form_class = PersonForm
    context_object_name = "person_create"
    success_url = reverse_lazy("syncope:home")
    organization = None

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")

        if url_username:
            try:
                self.organization = Organization.objects.get(user__username=url_username)

                # Check permission
                if not AccessControl.has_permission(request.user, "update", url_username):
                    return HttpResponseForbidden()
            except Organization.DoesNotExist:
                # No organization, this is a personal user
                self.organization = None
                # Only allow user to edit their own personal profile
                if request.user.username != url_username:
                    return HttpResponseForbidden()
        else:
            self.organization = None

        return super().dispatch(request, *args, **kwargs)


    def get_object(self, queryset=None):
        person_id = self.kwargs.get("pk")

        if person_id:
            # Editing a specific organization person by ID
            url_username = self.kwargs["username"]
            try:
                target_user = CustomUser.objects.get(username=url_username)
            except CustomUser.DoesNotExist:
                raise Http404("User not found")

            return get_object_or_404(
                AccessControl.get_viewable_people_queryset(self.request.user)
                .filter(memberships__user=target_user),
                id=person_id
            )
        else:
            # Editing personal person (owner=None)
            # URL pattern: /<username>/person_form2/
            return get_object_or_404(
                Person,
                user=self.request.user,
                owner__isnull=True
            )

    def get_context_data(self, resource_formset=None, **kwargs):
        context = super().get_context_data(**kwargs)
        if resource_formset is not None:
            context['resource_formset'] = resource_formset
        elif self.request.POST:
            context['resource_formset'] = PersonResourceFormSet(
                self.request.POST, instance=self.object, prefix='resources', user=self.request.user
            )
        else:
            context['resource_formset'] = PersonResourceFormSet(
                instance=self.object, prefix='resources', user=self.request.user
            )
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.request.method == "GET":
            form.initial["skills"] = self.object.skills.exclude(
                id__in=[Skill.SINGER, Skill.INSTRUMENTALIST]
            ).values_list("id", flat=True)
            form.initial["voices"] = Voice.objects.filter(
                singer__person=self.object
            ).values_list("id", flat=True)
            form.initial["instruments"] = Instrument.objects.filter(
                instrumentalist__person=self.object
            ).values_list("id", flat=True)
        return form

    def _save_resources(self, person, resource_formset):
        person.person_resource.all().delete()
        valid_forms = [
            f for f in resource_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
        ]
        for idx, f in enumerate(valid_forms):
            url = f.cleaned_data['url']
            description = f.cleaned_data.get('description', '')
            resource, created = Resource.objects.get_or_create(
                url=url,
                defaults={'owner': self.request.user, 'description': description}
            )
            if not created:
                resource.description = description
                resource.save(update_fields=['description'])
            PersonResource.objects.create(person=person, resource=resource, order=idx + 1)

    def form_valid(self, form):
        self.object = form.save(commit=False)

        # if user is connected, update email
        if self.object.user:
            self.object.user.email = self.object.email
            self.object.user.save()

        self.object.save()

        rf = PersonResourceFormSet(
            self.request.POST, instance=self.object, prefix='resources', user=self.request.user
        )
        if rf.is_valid():
            self._save_resources(self.object, rf)

        return redirect(self.get_success_url())



@method_decorator(login_required, name='dispatch')
class PersonListView(ListView):
    """Shows members (active/inactive) or persons with song skills (composers/poets/arrangers/translators)."""
    template_name = "syncope/person_list.html"
    context_object_name = "persons"
    organization = None

    def dispatch(self, request, *args, **kwargs):
        list_type = kwargs.get('list_type')
        valid_types = {'active', 'inactive', 'others', 'all'} | set(SKILL_MAP.keys())
        if list_type not in valid_types:
            raise Http404
        if list_type in ('others', 'all'):
            url_username = kwargs.get('username')
            if not AccessControl.has_permission(request.user, 'delete', url_username):
                return HttpResponseForbidden()
        return super().dispatch(request, *args, **kwargs)

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        url_username = self.kwargs["username"]
        self.organization = get_object_or_404(CustomUser, username=url_username)

    def get_queryset(self):
        list_type = self.kwargs["list_type"]
        url_username = self.kwargs["username"]
        org_user = get_object_or_404(CustomUser, username=url_username)
        visible_memberships = AccessControl.get_visible_members(self.request.user, url_username)

        q = self.request.GET.get('q', '').strip()
        queryset = _build_person_queryset(visible_memberships, q)

        if list_type in ('active', 'inactive'):
            periods = _filter_membership_periods_by_status(org_user, list_type)
            queryset = queryset.filter(person__membership_period__in=periods).distinct()
        elif list_type == 'others':
            ever_member_ids = MembershipPeriod.objects.filter(
                user=org_user, role_id__in=NON_EXTERNAL_ROLES
            ).values_list('person_id', flat=True)
            queryset = queryset.exclude(person_id__in=ever_member_ids)
            queryset = queryset.exclude(person__skills__id__in=SKILL_MAP.values()).distinct()
        elif list_type == 'all':
            pass
        else:
            skill_id = SKILL_MAP[list_type]
            queryset = queryset.filter(person__skills__id=skill_id).distinct()

        return _apply_person_sort(_annotate_person_queryset(queryset), self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        list_type = self.kwargs["list_type"]
        context["list_type"] = list_type
        context["organization"] = self.organization
        context["url_username"] = self.kwargs["username"]
        context["q"] = self.request.GET.get('q', '')
        context["current_sort"] = self.request.GET.get('sort', 'name')
        context["reverse"] = self.request.GET.get('reverse', 'false') == 'true'

        for person in context['persons']:
            person.resource_icons = resource_icon_list(person.person.person_resource.all())

        return context

@method_decorator(login_required, name="dispatch")
class OrgMemberDetailView(DetailView):
    """Shows details of a Person owned by Organization."""
    model = Person
    template_name = "syncope/org_member_detail.html"
    context_object_name = "person"
    customuser = None
    has_edit_permission = False

    def get_queryset(self):
        return Person.objects.select_related("owner__user")

    def dispatch(self, request, *args, **kwargs):
        """Handle permission checking before processing the request."""
        url_username = self.kwargs.get("username")

        if url_username:
            self.customuser = get_object_or_404(CustomUser, username=url_username)

            if request.user != self.customuser:
                self.has_edit_permission = AccessControl.can_edit_event(
                    request.user, self.customuser
                ).exists()

                if not self.has_edit_permission:  # CHANGED: Use cached result
                    return HttpResponseForbidden("You don't have permission to edit this event.")
        else:
            self.customuser = request.user

        return super().dispatch(request, *args, **kwargs)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        url_username = self.kwargs["username"]

        context["url_username"] = url_username
        context["is_admin"] = AccessControl.has_permission(self.request.user, 'delete', url_username)
        context["person_data"] = AccessControl.filter_person_details(
            self.request.user,
            self.object,
            url_username,
        )

        context["is_linked"] = self.object.owner_id is not None
        context["can_unlink"] = context["is_admin"] or AccessControl.is_person_owner(
            self.request.user, self.object
        )

        person = self.object

        context['person_resources'] = resource_icon_list(
            person.person_resource.select_related('resource').order_by('order')
        )

        # Composed songs
        composed_songs = person.composed_songs.all()
        if composed_songs.exists():
            context["composed_songs"] = composed_songs

        # Written songs
        written_songs = person.written_songs.all()
        if written_songs.exists():
            context["written_songs"] = written_songs

        # Arranged songs
        arranged_songs = person.arranged_songs.all()
        if arranged_songs.exists():
            context["arranged_songs"] = arranged_songs

        # Translation pairs with song counts
        translations = LyricsTranslation.objects.filter(
            translator=person
        ).select_related('song__languagecode', 'languagecode')
        if translations.exists():
            # translation_pairs = []
            # Group by (original language, translation language) pair
            pair_dict = {}
            for trans in translations:
                original_lang = trans.song.languagecode.language_code if trans.song.languagecode else "Unknown"
                translation_lang = trans.languagecode.language_code if trans.languagecode else "Unknown"
                key = (original_lang, translation_lang)
                if key not in pair_dict:
                    pair_dict[key] = {"original_lang": original_lang, "translation_lang": translation_lang, "count": 0}
                pair_dict[key]["count"] += 1

            translation_pairs = list(pair_dict.values())
            if translation_pairs:
                context["translation_pairs"] = translation_pairs

        # Singer projects (reordered by latest event date)
        if person.skills.filter(id=Skill.SINGER).exists():
            projects = Project.objects.filter(
                events__attendance__person=person
            ).annotate(
                latest_event=Max('events__started_at')
            ).distinct().order_by('-latest_event')

            singer_projects = []
            for project in projects:
                perf_attended = Attendance.objects.filter(
                    person=person,
                    event__project=project,
                    event__event_type_id__in=[EventType.PERFORMANCE, EventType.CONCERT, EventType.RECORDING],
                    attendance_type_id=AttendanceType.PRESENT,
                ).count()
                rehearsals_present = Attendance.objects.filter(
                    person=person,
                    event__project=project,
                    event__event_type_id=EventType.REHEARSAL,
                    attendance_type_id=AttendanceType.PRESENT,
                ).count()
                rehearsals_total = Attendance.objects.filter(
                    person=person,
                    event__project=project,
                    event__event_type_id=EventType.REHEARSAL,
                ).counted().count()
                singer_projects.append({
                    "project": project,
                    "performances_attended": perf_attended,
                    "rehearsals_present": rehearsals_present,
                    "rehearsals_total": rehearsals_total,
                })

            context["singer_projects"] = singer_projects

            # Singer voices
            singer_voices = person.singer_set.all()
            if singer_voices.exists():
                context["singer_voices"] = singer_voices

        # Instrumentalist projects (similar to singer projects)
        if person.skills.filter(id=Skill.INSTRUMENTALIST).exists():
            projects = Project.objects.filter(
                events__attendance__person=person
            ).annotate(
                latest_event=Max('events__started_at')
            ).distinct().order_by('-latest_event')

            instrumentalist_projects = []
            for project in projects:
                perf_attended = Attendance.objects.filter(
                    person=person,
                    event__project=project,
                    event__event_type_id__in=[EventType.PERFORMANCE, EventType.CONCERT, EventType.RECORDING],
                    attendance_type_id=AttendanceType.PRESENT,
                ).count()
                rehearsals_present = Attendance.objects.filter(
                    person=person,
                    event__project=project,
                    event__event_type_id=EventType.REHEARSAL,
                    attendance_type_id=AttendanceType.PRESENT,
                ).count()
                rehearsals_total = Attendance.objects.filter(
                    person=person,
                    event__project=project,
                    event__event_type_id=EventType.REHEARSAL,
                ).counted().count()
                instrumentalist_projects.append({
                    "project": project,
                    "performances_attended": perf_attended,
                    "rehearsals_present": rehearsals_present,
                    "rehearsals_total": rehearsals_total,
                })

            context["instrumentalist_projects"] = instrumentalist_projects

            # Instrumentalist instruments
            instrumentalist_instruments = person.instrumentalist_set.all()
            if instrumentalist_instruments.exists():
                context["instrumentalist_instruments"] = instrumentalist_instruments

        return context


@method_decorator(login_required, name='dispatch')
class OrgMemberAddView( FormView):  # OrgMemberMixin,
    """Add new person."""
    template_name = "syncope/org_member_form.html"
    form_class = OrgMemberForm
    customuser = None

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get("username")

        if url_username:
            self.customuser = get_object_or_404(
                CustomUser,
                username=url_username
            )
            # Allow if viewing own account OR  has member access
            if request.user != self.customuser:
                member_queryset = AccessControl.can_view_member_list(
                    request.user,
                    self.customuser
                )
                if not member_queryset.exists():
                    return HttpResponseForbidden()


        else:
            self.customuser = None

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Pass preset to the form."""
        kwargs = super().get_form_kwargs()
        kwargs['preset'] = self.kwargs.get('preset')
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance = Person()
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['preset'] = self.kwargs.get('preset')
        context['is_admin'] = True
        return context

    def form_valid(self, form):
        with transaction.atomic():
            # 1. create new person
            person = self._create_person(form)

            # 2. add roles into membership
            self._add_roles(person, form.cleaned_data["roles"])

            # 3. add skills
            self._add_skills(person, form.cleaned_data["skills"])

            # 4. add voices
            self._add_voices(person, form.cleaned_data["voices"])

            # 5. add instruments
            self._add_instruments(person, form.cleaned_data["instruments"])

            # 6. add date fields
            self._add_dates(person, form)

        next_url = self.request.GET.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return redirect(next_url)
        return redirect("syncope:org_member_list", username=self.kwargs["username"])

    def _create_person(self, form):
        """
        Create a new Person.
        - If adding to a customuser: create org person with owner
        - If adding to personal account: create personal person with owner=None
        """
        is_organization = Organization.objects.filter(user=self.customuser).exists()

        if is_organization:
            # adding members to an organization:
            person = Person.objects.create(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=form.cleaned_data.get("email", ""),
                phone=form.cleaned_data.get("phone", ""),
                address=form.cleaned_data.get("address", ""),
                user=None,  # Belongs to organization
                owner=None  # Ownership not claimed yet
            )
        else:
            #  Adding to personal account (like adding a family member, poet, composer, etc.)
            # These are personal records that belong to the user but "user" is only for login
            person = Person.objects.create(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                email=form.cleaned_data.get("email", ""),
                phone=form.cleaned_data.get("phone", ""),
                address=form.cleaned_data.get("address", ""),
                user=None,  # The personal user account
                owner=None  # Personal record, no owner
            )

        return person



    def _add_roles(self, person, selected_roles):
        """Create memberships for selected roles."""
        if not selected_roles:
            selected_roles = [Role.objects.get(id=Role.EXTERNAL)]

        today = datetime.date.today()

        # Create the base membership (only once per person-org relationship)
        membership, created = Membership.objects.get_or_create(
            user=self.customuser,
            person=person
        )

        for role in selected_roles:
            # Create PersonRole to assign the role to the person
            PersonRole.objects.create(
                person=person,
                role=role
            )

            # Track when they started this role
            MembershipPeriod.objects.create(
                user=self.customuser,
                person=person,
                role=role,
                started_at=today
            )

    def _add_skills(self, person, selected_skills):
        """Create PersonSkill entry for selected skills."""
        for skill in selected_skills:
            PersonSkill.objects.create(
                person=person,
                skill=skill
            )

    def _add_voices(self, person, selected_voices):
        """Create Singer entries and ensure 'singer' skill is added."""
        if not selected_voices:
            return

        # Create Singer entries for each selected voice
        for voice in selected_voices:
            Singer.objects.create(
                person=person,
                voice=voice
            )

        # Automatically add 'singer' skill if voices were selected
        singer_skill = Skill.objects.filter(title__iexact='singer').first()
        if singer_skill:
            PersonSkill.objects.get_or_create(
                person=person,
                skill=singer_skill
            )

    def _add_instruments(self, person, selected_instruments):
        """Create Instrumentalist entries and ensure 'instrumentalist' skill is added."""
        if not selected_instruments:
            return

        # Create Instrumentalist entries for each selected instrument
        for instrument in selected_instruments:
            Instrumentalist.objects.create(
                person=person,
                instrument=instrument
            )

        # Automatically add 'instrumentalist' skill if instruments were selected
        instrumentalist_skill = Skill.objects.filter(title__iexact='instrumentalist').first()
        if instrumentalist_skill:
            PersonSkill.objects.get_or_create(
                person=person,
                skill=instrumentalist_skill
            )

    def _add_dates(self, person, form):
        """Update person with date fields."""
        if form.cleaned_data.get('birth_date'):
            person.birth_date = form.cleaned_data['birth_date']
        if form.cleaned_data.get('birth_approximate'):
            person.birth_approximate = form.cleaned_data['birth_approximate']
        if form.cleaned_data.get('death_date'):
            person.death_date = form.cleaned_data['death_date']
        if form.cleaned_data.get('death_approximate'):
            person.death_approximate = form.cleaned_data['death_approximate']
        person.save()





@method_decorator(login_required, name='dispatch')
class OrgMemberEditView( FormView):  # OrgMemberMixin,
    """Edit existing member. Admin can edit everybody, user can edit its own."""
    template_name = "syncope/org_member_form.html"
    form_class = OrgMemberForm
    customuser = None
    person = None


    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs["username"]


        self.customuser = get_object_or_404(
            CustomUser,
            username=url_username
        )


        self.person = get_object_or_404(Person, pk=self.kwargs["pk"])


        viewer_role = AccessControl.get_org_roles(
            request.user,
            url_username
        )


        is_admin = viewer_role.filter(id=Role.ADMIN).exists()
        is_owner = self.person.user == request.user



        if not (is_admin or is_owner):
            raise PermissionDenied("No permission to edit")

        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        # pre-fill form with existing data
        form = super().get_form(form_class)
        form.instance = self.person

        if self.request.method == "GET":
            # current roles in THIS organization
            current_role_ids = self.person.roles.values_list("id", flat=True)

            # current skills
            current_skill_ids = self.person.skills.values_list(
                "id", flat=True
            )

            # current voices
            current_voice_ids = Voice.objects.filter(
                singer__person=self.person
            ).values_list("id", flat=True)

            # current instruments
            current_instrument_ids = Instrument.objects.filter(
                instrumentalist__person=self.person
            ).values_list("id", flat=True)

            # dict of the checkboxes
            form.initial = {
                # person info
                "first_name": self.person.first_name,
                "last_name": self.person.last_name,
                "email": self.person.email,
                "phone": self.person.phone,
                "address": self.person.address,
                # date fields
                "birth_date": self.person.birth_date,
                "birth_approximate": self.person.birth_approximate_id,
                "death_date": self.person.death_date,
                "death_approximate": self.person.death_approximate_id,
                # m2m relationships
                "roles": current_role_ids,
                "skills": current_skill_ids,
                "voices": current_voice_ids,
                "instruments": current_instrument_ids,
            }

        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.customuser
        context['is_admin'] = True
        if self.request.POST:
            context['resource_formset'] = PersonResourceFormSet(
                self.request.POST, instance=self.person, prefix='resources', user=self.request.user
            )
        else:
            context['resource_formset'] = PersonResourceFormSet(
                instance=self.person, prefix='resources', user=self.request.user
            )
        return context

    def form_valid(self, form):
        with transaction.atomic():
            # 1. update person info
            self._update_person_info(form)

            # 2. update roles
            self._update_roles(form.cleaned_data["roles"])

            # 3. update skills
            self._update_skills(form.cleaned_data["skills"])

            # 4. update voices
            self._update_voices(form.cleaned_data["voices"])

            # 5. update instruments
            self._update_instruments(form.cleaned_data["instruments"])

            # 6. update date fields
            self._update_dates(form)

            # 7. save resources
            rf = PersonResourceFormSet(
                self.request.POST, instance=self.person, prefix='resources', user=self.request.user
            )
            if rf.is_valid():
                self._save_resources(rf)

        return redirect("syncope:org_member_list",username=self.kwargs["username"])

    def _save_resources(self, resource_formset):
        self.person.person_resource.all().delete()
        valid_forms = [
            f for f in resource_formset.forms
            if f.cleaned_data and not f.cleaned_data.get('DELETE') and f.cleaned_data.get('url')
        ]
        for idx, f in enumerate(valid_forms):
            url = f.cleaned_data['url']
            description = f.cleaned_data.get('description', '')
            resource, created = Resource.objects.get_or_create(
                url=url,
                defaults={'owner': self.request.user, 'description': description}
            )
            if not created:
                resource.description = description
                resource.save(update_fields=['description'])
            PersonResource.objects.create(person=self.person, resource=resource, order=idx + 1)

    def _update_person_info(self, form):
        """update personal info"""
        self.person.first_name = form.cleaned_data["first_name"]
        self.person.last_name = form.cleaned_data["last_name"]
        self.person.email = form.cleaned_data.get("email", "")
        self.person.phone = form.cleaned_data.get("phone", "")
        self.person.address = form.cleaned_data.get("address", "")
        self.person.save()

    def _update_roles(self, new_roles):
        """sync roles - add new ones, remove old ones"""
        today = datetime.date.today()

        # Get current roles for this person
        current_role_ids = set(self.person.roles.values_list("id", flat=True))

        # New roles from form
        new_role_ids = {role.id for role in new_roles}

        # Get or create the base membership (the relationship between org user and person)
        membership, _ = Membership.objects.get_or_create(
            user=self.customuser,
            person=self.person
        )

        # Add new roles
        for role_id in (new_role_ids - current_role_ids):
            PersonRole.objects.create(
                person=self.person,
                role_id=role_id
            )
            MembershipPeriod.objects.create(
                user=self.customuser,
                person=self.person,
                role_id=role_id,
                started_at=today
            )

        # Remove roles
        removed_role_ids = current_role_ids - new_role_ids
        if removed_role_ids:
            # Close open periods for removed roles
            MembershipPeriod.objects.filter(
                user=self.customuser,
                person=self.person,
                role_id__in=removed_role_ids,
                ended_at__isnull=True
            ).update(ended_at=today)

            # Delete the PersonRole entries
            PersonRole.objects.filter(
                person=self.person,
                role_id__in=removed_role_ids
            ).delete()

    def _update_skills(self, new_skills):
        """sync skills - add new, remove old"""
        # current skills
        current_skills = PersonSkill.objects.filter(person=self.person)
        current_skill_ids = set(current_skills.values_list("skill_id", flat=True))

        # new skills
        new_skill_ids = {skill.id for skill in new_skills}

        # do the magic
        for skill_id in (new_skill_ids - current_skill_ids):
            PersonSkill.objects.create(
                person=self.person,
                skill_id=skill_id
            )

        # remove old skills
        removed_skill_ids = current_skill_ids - new_skill_ids
        if removed_skill_ids:
            current_skills.filter(skill_id__in=removed_skill_ids).delete()

    def _update_voices(self, new_voices):
        """Sync voices - add new ones, remove old ones."""
        # Current voices
        current_singers = Singer.objects.filter(person=self.person)
        current_voice_ids = set(current_singers.values_list("voice_id", flat=True))

        # New voices from form
        new_voice_ids = {voice.id for voice in new_voices}

        # Add new voices
        for voice_id in (new_voice_ids - current_voice_ids):
            Singer.objects.create(
                person=self.person,
                voice_id=voice_id
            )

        # Remove old voices
        removed_voice_ids = current_voice_ids - new_voice_ids
        if removed_voice_ids:
            current_singers.filter(voice_id__in=removed_voice_ids).delete()

        # Handle 'singer' skill
        singer_skill = Skill.objects.filter(title__iexact='singer').first()
        if singer_skill:
            if new_voices:
                # If voices selected, ensure singer skill exists
                PersonSkill.objects.get_or_create(
                    person=self.person,
                    skill=singer_skill
                )
            else:
                # If no voices selected, remove singer skill
                PersonSkill.objects.filter(
                    person=self.person,
                    skill=singer_skill
                ).delete()

    def _update_instruments(self, new_instruments):
        """Sync instruments - add new ones, remove old ones."""
        # Current instruments
        current_instrumentalists = Instrumentalist.objects.filter(person=self.person)
        current_instrument_ids = set(current_instrumentalists.values_list("instrument_id", flat=True))

        # New instruments from form
        new_instrument_ids = {instrument.id for instrument in new_instruments}

        # Add new voices
        for instrument_id in (new_instrument_ids - current_instrument_ids):
            Instrumentalist.objects.create(
                person=self.person,
                instrument_id=instrument_id
            )

        # Remove old instruments
        removed_instrument_ids = current_instrument_ids - new_instrument_ids
        if removed_instrument_ids:
            current_instrumentalists.filter(instrument_id__in=removed_instrument_ids).delete()

        # Handle 'instrumentalist' skill
        instrumentalist_skill = Skill.objects.filter(title__iexact='instrumentalist').first()
        if instrumentalist_skill:
            if new_instruments:
                # If instruments selected, ensure instrumentalist skill exists
                PersonSkill.objects.get_or_create(
                    person=self.person,
                    skill=instrumentalist_skill
                )
            else:
                # If no voices selected, remove singer skill
                PersonSkill.objects.filter(
                    person=self.person,
                    skill=instrumentalist_skill
                ).delete()

    def _update_dates(self, form):
        """Update person with date fields."""
        if form.cleaned_data.get('birth_date'):
            self.person.birth_date = form.cleaned_data['birth_date']
        else:
            self.person.birth_date = None
        if form.cleaned_data.get('birth_approximate'):
            self.person.birth_approximate = form.cleaned_data['birth_approximate']
        else:
            self.person.birth_approximate = None
        if form.cleaned_data.get('death_date'):
            self.person.death_date = form.cleaned_data['death_date']
        else:
            self.person.death_date = None
        if form.cleaned_data.get('death_approximate'):
            self.person.death_approximate = form.cleaned_data['death_approximate']
        else:
            self.person.death_approximate = None
        self.person.save()


@method_decorator(login_required, name="dispatch")
class OrgMemberDeleteView(LoginRequiredMixin, DeleteView):
    model = Person
    template_name = 'syncope/org_member_confirm_delete.html'

    def get_queryset(self):
        url_username = self.kwargs.get('username')
        org_user = get_object_or_404(CustomUser, username=url_username)
        return Person.objects.filter(memberships__user=org_user)

    def dispatch(self, request, *args, **kwargs):
        url_username = self.kwargs.get('username')
        if not AccessControl.has_permission(request.user, 'delete', url_username):
            return HttpResponseForbidden("Only admins can delete members.")
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        person = self.get_object()
        name = f"{person.first_name} {person.last_name}".strip()
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f"Successfully deleted member '{name}'.")
        return response

    def get_success_url(self):
        return reverse('syncope:org_member_list', kwargs={'username': self.kwargs.get('username')})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_username'] = self.kwargs.get('username')
        context['is_admin'] = True
        return context


@require_POST
@login_required
def org_member_unlink(request, username, pk):
    org_user = get_object_or_404(CustomUser, username=username)
    person = get_object_or_404(
        Person.objects.select_related("owner"),
        pk=pk, memberships__user=org_user,
    )

    is_admin = AccessControl.has_permission(request.user, "delete", username)
    is_owner = AccessControl.is_person_owner(request.user, person)

    if not (is_admin or is_owner):
        return HttpResponseForbidden()

    if person.owner_id is None:
        return redirect("syncope:org_member_detail", username=username, pk=pk)

    person.owner = None
    person.save(update_fields=["owner"])

    name = f"{person.first_name} {person.last_name}".strip()
    if is_owner:
        messages.success(request, f"Unlinked your account from '{name}'.")
        return redirect("syncope:home")

    messages.success(request, f"Unlinked '{name}' from their account.")
    return redirect("syncope:org_member_detail", username=username, pk=pk)
