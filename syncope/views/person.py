from django.http import Http404, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from syncope.forms import PersonForm, PersonResourceFormSet, MembershipPeriodFormSet
from syncope.utils import merge_consecutive_membership_periods
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
from syncope.models import Attendance, AttendanceType, Event, EventType, Voice, Instrument,  Project, LyricsTranslation, PersonResource, Resource
from syncope.permissions import AccessControl
from syncope.utils import resource_icon_list, add_query_param
from syncope.views.drafts import DraftMixin


@method_decorator(login_required, name='dispatch')
class PersonUpdateView(DraftMixin, UpdateView):
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
        kwargs["own_profile"] = not bool(self.kwargs.get("pk"))
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

        self._update_skills(form.cleaned_data["skills"])
        self._update_voices(form.cleaned_data["voices"])
        self._update_instruments(form.cleaned_data["instruments"])

        return redirect(self.get_success_url())

    def _sync_m2m(self, model_class, new_items, id_field, related_skill_title=None):
        """Generic M2M sync: add/remove relations and optionally update derived skill."""
        queryset = model_class.objects.filter(person=self.object)
        current_ids = set(queryset.values_list(f'{id_field}', flat=True))
        new_ids = {item.id for item in new_items}

        for new_id in (new_ids - current_ids):
            model_class.objects.create(person=self.object, **{id_field: new_id})
        queryset.filter(**{f'{id_field}__in': current_ids - new_ids}).delete()

        if related_skill_title:
            skill = Skill.objects.filter(title__iexact=related_skill_title).first()
            if skill:
                if new_ids:
                    PersonSkill.objects.get_or_create(person=self.object, skill=skill)
                else:
                    PersonSkill.objects.filter(person=self.object, skill=skill).delete()

    def _update_skills(self, new_skills):
        self._sync_m2m(PersonSkill, new_skills, 'skill_id')

    def _update_voices(self, new_voices):
        self._sync_m2m(Singer, new_voices, 'voice_id', related_skill_title='singer')

    def _update_instruments(self, new_instruments):
        self._sync_m2m(Instrumentalist, new_instruments, 'instrument_id', related_skill_title='instrumentalist')


@method_decorator(login_required, name='dispatch')
class OrgMemberListView(ListView):
    """Shows all members of a CustomUser."""
    template_name = "syncope/org_member_list.html"
    context_object_name = "members"
    organization = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        url_username = self.kwargs["username"]
        self.organization = get_object_or_404(
            CustomUser,
            username=url_username
        )

    def get_queryset(self):
        url_username = self.kwargs["username"]

        # Get all memberships for this organization
        visible_memberships = AccessControl.get_visible_members(
            self.request.user,
            url_username
        )

        queryset = visible_memberships.select_related('person').prefetch_related(
            'person__skills', 'person__roles',
            'person__singer_set__voice', 'person__instrumentalist_set__instrument',
            'person__person_resource__resource',
        )

        q = self.request.GET.get('q', '').strip()
        if q:
            # When searching, include all matching results regardless of visibility filtering
            # but still respect the base membership access
            queryset = queryset.filter(
                Q(person__first_name__icontains=q) |
                Q(person__last_name__icontains=q) |
                Q(person__skills__title__icontains=q) |
                Q(person__singer__voice__name__icontains=q) |
                Q(person__instrumentalist__instrument__name__icontains=q)
            ).distinct()

        session_key = f'member_list_role_{self.kwargs["username"]}'
        if 'role' in self.request.GET:
            role_id = self.request.GET.get('role', '').strip()
            self.request.session[session_key] = role_id
        else:
            role_id = self.request.session.get(session_key)
            if role_id is None:
                role_id = str(Role.MEMBER)
                self.request.session[session_key] = role_id

        if role_id:
            queryset = queryset.filter(person__roles__id=int(role_id))

        queryset = queryset.annotate(
            first_skill=Min('person__skills__title'),
            first_voice=Min('person__singer__voice__name'),
            first_instrument=Min('person__instrumentalist__instrument__name'),
        ).annotate(
            first_voice_or_instrument=Coalesce('first_voice', 'first_instrument', Value('')),
        )

        sort_field_map = {
            'name': ('person__last_name', 'person__first_name'),
            'email': ('person__email',),
            'skill': ('first_skill',),
            'voice_instrument': ('first_voice_or_instrument',),
        }
        sort_key = self.request.GET.get('sort', 'name')
        reverse = self.request.GET.get('reverse', 'false') == 'true'
        fields = sort_field_map.get(sort_key, sort_field_map['name'])
        if reverse:
            fields = tuple(f'-{f}' for f in fields)
        return queryset.order_by(*fields)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.organization
        context["url_username"] = self.kwargs["username"]
        context["q"] = self.request.GET.get('q', '')
        context["current_sort"] = self.request.GET.get('sort', 'name')
        context["reverse"] = self.request.GET.get('reverse', 'false') == 'true'
        session_key = f'member_list_role_{self.kwargs["username"]}'
        if 'role' in self.request.GET:
            context["selected_role"] = self.request.GET.get('role', '')
        else:
            context["selected_role"] = self.request.session.get(session_key, str(Role.MEMBER))

        url_username = self.kwargs["username"]
        visible_members = AccessControl.get_visible_members(
            self.request.user,
            url_username
        )
        available_roles = Role.objects.filter(
            persons__in=visible_members.values_list('person', flat=True)
        ).distinct().order_by('title')
        context["available_roles"] = available_roles

        for member in context['members']:
            member.resource_icons = resource_icon_list(member.person.person_resource.all())

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
class OrgMemberAddView(DraftMixin, FormView):  # OrgMemberMixin,
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
        host = self.request.get_host()
        safe_next = next_url if (next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={host})) else None
        draft_key = self.request.GET.get('draft_key')

        auto_add_event = self.request.GET.get('auto_add_event')
        auto_add_project = self.request.GET.get('auto_add_project')

        if safe_next and auto_add_event:
            event = Event.objects.filter(pk=auto_add_event, user=self.customuser).first()
            if event:
                Attendance.objects.get_or_create(
                    event=event, person=person,
                    defaults={'attendance_type_id': AttendanceType.PRESENT},
                )
            if draft_key:
                safe_next = add_query_param(safe_next, {'draft_key': draft_key})
            return redirect(safe_next)

        if safe_next and auto_add_project:
            project = Project.objects.filter(pk=auto_add_project, user=self.customuser).first()
            if project:
                project.guests.add(person)
            if draft_key:
                safe_next = add_query_param(safe_next, {'draft_key': draft_key})
            return redirect(safe_next)

        if safe_next:
            preset = self.kwargs.get('preset', '')
            next_url = add_query_param(safe_next, {f'select_{preset or "person"}': person.pk})
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
class OrgMemberEditView(DraftMixin, FormView):  # OrgMemberMixin,
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

        period_qs = MembershipPeriod.objects.filter(
            person=self.person, user=self.customuser
        ).order_by('role_id', 'started_at')

        period_kwargs = dict(instance=self.person, prefix='periods', user=self.customuser, person=self.person, queryset=period_qs)

        if self.request.POST:
            context['resource_formset'] = PersonResourceFormSet(
                self.request.POST, instance=self.person, prefix='resources', user=self.request.user
            )
            context['period_formset'] = MembershipPeriodFormSet(self.request.POST, **period_kwargs)
        else:
            context['resource_formset'] = PersonResourceFormSet(
                instance=self.person, prefix='resources', user=self.request.user
            )
            context['period_formset'] = MembershipPeriodFormSet(**period_kwargs)
        return context

    def form_valid(self, form):
        with transaction.atomic():
            # 1. save period formset
            pf = MembershipPeriodFormSet(
                self.request.POST, instance=self.person, prefix='periods',
                user=self.customuser, person=self.person,
                queryset=MembershipPeriod.objects.filter(person=self.person, user=self.customuser),
            )
            if pf.is_valid():
                pf.save()

            # 2. update person info
            self._update_person_info(form)

            # 3. update roles (auto-creates/closes periods for checkbox changes)
            self._update_roles(form.cleaned_data["roles"])

            # 4. merge any same-boundary periods created by step 1+3 interaction
            merge_consecutive_membership_periods(self.person, self.customuser)

            # 5. reconcile PersonRole with final open-period state
            self._reconcile_roles_with_periods()

            # 6. update skills
            self._update_skills(form.cleaned_data["skills"])

            # 7. update voices
            self._update_voices(form.cleaned_data["voices"])

            # 8. update instruments
            self._update_instruments(form.cleaned_data["instruments"])

            # 9. update date fields
            self._update_dates(form)

            # 10. save resources
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

    def _sync_m2m(self, model_class, new_items, id_field, related_skill_title=None):
        """Generic M2M sync: add/remove relations and optionally update derived skill."""
        queryset = model_class.objects.filter(person=self.person)
        current_ids = set(queryset.values_list(f'{id_field}', flat=True))
        new_ids = {item.id for item in new_items}

        for new_id in (new_ids - current_ids):
            model_class.objects.create(person=self.person, **{id_field: new_id})
        queryset.filter(**{f'{id_field}__in': current_ids - new_ids}).delete()

        if related_skill_title:
            skill = Skill.objects.filter(title__iexact=related_skill_title).first()
            if skill:
                if new_ids:
                    PersonSkill.objects.get_or_create(person=self.person, skill=skill)
                else:
                    PersonSkill.objects.filter(person=self.person, skill=skill).delete()

    def _update_skills(self, new_skills):
        self._sync_m2m(PersonSkill, new_skills, 'skill_id')

    def _update_voices(self, new_voices):
        self._sync_m2m(Singer, new_voices, 'voice_id', related_skill_title='singer')

    def _update_instruments(self, new_instruments):
        self._sync_m2m(Instrumentalist, new_instruments, 'instrument_id', related_skill_title='instrumentalist')

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

    def _reconcile_roles_with_periods(self):
        """Sync PersonRole with final open-period state. Open periods are authoritative."""
        open_role_ids = set(
            MembershipPeriod.objects.filter(
                person=self.person, user=self.customuser, ended_at__isnull=True
            ).values_list('role_id', flat=True)
        )
        current_role_ids = set(self.person.roles.values_list('id', flat=True))
        roles_to_add = open_role_ids - current_role_ids
        if roles_to_add:
            PersonRole.objects.bulk_create([
                PersonRole(person=self.person, role_id=role_id)
                for role_id in roles_to_add
            ], ignore_conflicts=True)
        PersonRole.objects.filter(
            person=self.person, role_id__in=(current_role_ids - open_role_ids)
        ).delete()


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
