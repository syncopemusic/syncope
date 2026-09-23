from django import forms
import datetime
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils import timezone
from .models import CustomUser, Organization, Person, Song, Skill, Role, Quote, Project, Poll, PollPerson, PollEvent, \
    PollAttendance, Invitation
from .models import Event, EventSong, AttendanceType,  Voice, Instrument, EventType, EventResource, EventSongResource
from .models import LyricsTranslation, LanguageCode, ApproximateDate, Resource, SongResource, PersonResource, ProjectResource, \
    MembershipPeriod, PersonRole
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.db.models import Q, Count


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ("email", "username",)

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ("email",)


class RegisterForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = "__all__"


class PersonForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.exclude(id__in=[Skill.SINGER, Skill.INSTRUMENTALIST]),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )
    voices = forms.ModelMultipleChoiceField(
        queryset=Voice.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': '6'}),
        label='Voice Types'
    )
    instruments = forms.ModelMultipleChoiceField(
        queryset=Instrument.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': '6'}),
        label='Instrument Types'
    )

    class Meta:
        model = Person
        fields = [
            "first_name",
            "last_name",
            "email",
            "address",
            "phone",
            "birth_date",
            "birth_approximate",
            "death_date",
            "death_approximate",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={'type': 'date'}),
            "death_date": forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        own_profile = kwargs.pop("own_profile", False)
        super().__init__(*args, **kwargs)

        if own_profile:
            for field in ("death_date", "birth_approximate", "death_approximate"):
                self.fields.pop(field, None)

        if self.instance.pk:
            # editing current user
            self.fields["email"].initial = self.instance.email
        elif user and user.is_authenticated:
            # new user - grab email from user
            self.fields["email"].initial = user.email

class OrganizationForm(forms.ModelForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = Organization
        fields = ["name", "email", "address"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class OrgMemberForm(forms.Form):  # Person + Membership + MembershipPeriod
    VALID_PRESETS = {'composer', 'poet', 'translator', 'arranger', 'member'}
    # Person
    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=23, required=False)
    address = forms.CharField(required=False, widget=forms.Textarea)
    # Date fields
    birth_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    birth_approximate = forms.ModelChoiceField(
        queryset=ApproximateDate.objects.all(),
        required=False,
        empty_label="Exact date",
        label="Birth date approximation"
    )
    death_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    death_approximate = forms.ModelChoiceField(
        queryset=ApproximateDate.objects.all(),
        required=False,
        empty_label="Exact date",
        label="Death date approximation"
    )
    # Role checkboxes
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )
    # Skill checkbox
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.exclude(id__in=[Skill.SINGER, Skill.INSTRUMENTALIST]),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )
    # Voice select multiple
    voices = forms.ModelMultipleChoiceField(
        queryset=Voice.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            'size': '6',  # Shows 6 options at once
            # 'class': 'form-select'  # Optional: for styling
        }),
        label='Voice Types'
    )
    # Instrument select multiple
    instruments = forms.ModelMultipleChoiceField(
        queryset=Instrument.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            'size': '6',  # Shows 6 options at once
            # 'class': 'form-select'  # Optional: for styling
        }),
        label='Instrument Types'
    )

    def __init__(self, *args, preset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preset not in self.VALID_PRESETS:
            preset = None

        # Apply presets
        if preset == 'composer':
            self.initial['roles'] = [Role.EXTERNAL]
            self.initial["skills"] = [Skill.COMPOSER]

        elif preset == 'poet':
            self.initial['roles'] = [Role.EXTERNAL]
            self.initial["skills"] = [Skill.POET]

        elif preset == 'translator':
            self.initial['roles'] = [Role.EXTERNAL]
            self.initial["skills"] = [Skill.TRANSLATOR]

        elif preset == 'arranger':
            self.initial['roles'] = [Role.EXTERNAL]
            self.initial["skills"] = [Skill.ARRANGER]

        elif preset == 'member':
            self.initial['roles'] = [Role.MEMBER]



class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ['word', 'bar_number', 'date', 'person']
        labels = {
            'word': 'Quote',
            'bar_number': 'Bar Number',
            'date': 'Date',
            'person': 'Person',
        }
        widgets = {
            'word': forms.TextInput(attrs={'placeholder': 'Quote text'}),
            'bar_number': forms.TextInput(attrs={'placeholder': '43'}),
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['person'].queryset = Person.objects.in_org_user(user)


class SongForm(forms.ModelForm):
    class Meta:
        model = Song
        fields = [
            "internal_id",
            "title",
            "composer",
            "arranger",
            "poet",
            "translator",
            "origin",
            "number_of_pages",
            "number_of_copies",
            "year",
            "ensemble",
            "number_of_voices",
            "additional_notes",
            "lyrics",
            "languagecode",
            "keywords",
        ]
        widgets = {
            "lyrics": forms.Textarea(attrs={'rows': 12}),
        }
        labels = {
            "languagecode": "Language",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if user:
            person_field_skills = {
                'composer': Skill.COMPOSER,
                'arranger': Skill.ARRANGER,
                'poet': Skill.POET,
                'translator': Skill.TRANSLATOR,
            }
            for field_name, skill_id in person_field_skills.items():
                self.fields[field_name].queryset = Person.objects.for_user_with_skill(
                    user=user, skill_id=skill_id
                )

    def clean_internal_id(self):
        value = self.cleaned_data.get("internal_id")
        if value is not None and self.user:
            qs = Song.objects.filter(user=self.user, internal_id=value)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("ID already in use.")
        return value


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'title',
            'description',
            'details',
            'start_date',
            'end_date',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'details': forms.Textarea(attrs={'rows': 6}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)


class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ["title", "additional_notes"]


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['name',
                  'location',
                  'description',
                  'started_at',
                  'ended_at',
                  'event_type',
                  'project',
                  'producers',
                  'additional_notes',
                  'num_visitors',
                  ]
        labels = {
            'producers': 'Organizers',
            'additional_notes': 'Personal notes',
        }
        widgets = {
            'started_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'ended_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'location': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Venue / address'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Description'}),
            'producers': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Organizers'}),
            'additional_notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Personal notes'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Order projects by start date (most recent first)
        qs = Project.objects.all() if user is None else Project.objects.filter(user=user)
        self.fields['project'].queryset = qs.order_by('-start_date').distinct()

        # Pre-select "rehearsal" event type and remove empty option
        rehearsal_event_type = EventType.objects.get(pk=EventType.REHEARSAL)
        self.fields['event_type'].initial = rehearsal_event_type
        self.fields['event_type'].empty_label = None

        # Name is optional - events can exist as just a date and type
        self.fields['name'].required = False
        self.fields['name'].widget.attrs['placeholder'] = 'Optional'




class AddSongToEventForm(forms.Form):
    """Admin-only form to add archive songs to an event's setlist (staged client-side; see event_songs_edit.html)."""
    song = forms.ModelMultipleChoiceField(
        queryset=Song.objects.none(),
        widget=forms.CheckboxSelectMultiple(),
        label='Song',
    )

    def __init__(self, *args, org_user=None, event=None, search_q='', limit_results=True, exclude_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.song_search_truncated = False
        if org_user and event is not None:
            if search_q:
                already_added_ids = set(event.eventsong_set.values_list('song_id', flat=True))
                exclude_pks = already_added_ids | set(exclude_ids or [])
                qs = Song.objects.filter(user=org_user).exclude(id__in=exclude_pks).annotate(
                    resource_count=Count('song_resource', distinct=True)
                ).order_by('title')
                if search_q.isdigit():
                    qs = qs.filter(internal_id=int(search_q))
                else:
                    qs = qs.filter(
                        Q(title__icontains=search_q) |
                        Q(composer__last_name__icontains=search_q) |
                        Q(keywords__icontains=search_q)
                    ).distinct()
                if limit_results:
                    total_matches = qs.count()
                    limited_ids = list(qs.values_list('pk', flat=True)[:25])
                    qs = qs.filter(pk__in=limited_ids)
                    self.song_search_truncated = total_matches > 25
            else:
                qs = Song.objects.none()
            self.fields['song'].queryset = qs


class AddEventToProjectForm(forms.Form):
    """Admin-only form powering the Events subpage's live search (see project_events_edit.html).

    Adds/removes are staged client-side and committed in one batched POST
    (ProjectEventsEditView.post), so `exclude_ids` lets the search hide events
    already staged-but-not-yet-saved, not just ones already committed to the project.
    """
    def __init__(self, *args, org_user=None, project=None, search_q='', exclude_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.other_project_ids = {}
        self.search_results = []
        if org_user and project is not None and search_q:
            eligible = Event.objects.filter(user=org_user).exclude(
                project=project
            ).exclude(pk__in=exclude_ids or []).select_related('project').order_by('-started_at')
            self.search_results = list(eligible.filter(name__icontains=search_q))
            for event in self.search_results:
                if event.project_id:
                    self.other_project_ids[event.pk] = event.project.title


class AddSongToProjectForm(forms.Form):
    """Admin-only form powering the Songs subpage's live search (see project_songs_edit.html).

    See AddEventToProjectForm's docstring for why `exclude_ids` exists.
    """
    def __init__(self, *args, org_user=None, project=None, search_q='', exclude_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_results = []
        if org_user and project is not None and search_q:
            eligible = Song.objects.filter(user=org_user).exclude(
                projects=project
            ).exclude(pk__in=exclude_ids or []).order_by('title')
            if search_q.isdigit():
                self.search_results = list(eligible.filter(internal_id=int(search_q)))
            else:
                self.search_results = list(eligible.filter(
                    Q(title__icontains=search_q) |
                    Q(composer__last_name__icontains=search_q) |
                    Q(keywords__icontains=search_q)
                ).distinct())


class AddGuestToProjectForm(forms.Form):
    """Admin-only form powering the Participants subpage's live search (see project_participants_edit.html).

    See AddEventToProjectForm's docstring for why `exclude_ids` exists.
    """
    def __init__(self, *args, org_user=None, project=None, search_q='', exclude_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_results = []
        if org_user and project is not None and search_q:
            eligible = Person.objects.filter(membership_period__user=org_user).exclude(
                projects=project
            ).exclude(pk__in=exclude_ids or []).distinct().order_by('last_name', 'first_name')
            self.search_results = list(eligible.filter(
                Q(first_name__icontains=search_q) |
                Q(last_name__icontains=search_q)
            ).distinct())


class AddAttendanceForm(forms.Form):
    """Admin-only form to add any org person to an event's attendance."""
    person = forms.ModelMultipleChoiceField(
        queryset=Person.objects.none(),
        widget=forms.CheckboxSelectMultiple(),
        label='Person',
    )
    attendance_type = forms.ModelChoiceField(
        queryset=AttendanceType.objects.all(),
        widget=forms.RadioSelect(),
        label='Attendance Type',
        initial=AttendanceType.PRESENT,
    )

    def __init__(self, *args, org_user=None, event=None, search_q='', limit_results=True, exclude_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.person_search_truncated = False
        if org_user and event:
            if search_q:
                from django.db.models import Exists, OuterRef, ExpressionWrapper, BooleanField
                from .models import Singer, Instrumentalist
                already_attending = event.attendance_set.values_list('person_id', flat=True)
                exclude_pks = set(already_attending) | set(exclude_ids or [])
                qs = Person.objects.filter(
                    membership_period__user=org_user,
                ).exclude(
                    id__in=exclude_pks
                ).filter(
                    Q(first_name__icontains=search_q) |
                    Q(last_name__icontains=search_q) |
                    Q(singer__voice__name__icontains=search_q) |
                    Q(instrumentalist__instrument__name__icontains=search_q)
                ).distinct().annotate(
                    is_performer=ExpressionWrapper(
                        Exists(Singer.objects.filter(person=OuterRef('pk'))) |
                        Exists(Instrumentalist.objects.filter(person=OuterRef('pk'))),
                        output_field=BooleanField()
                    )
                ).order_by('-is_performer', 'last_name', 'first_name')
                if limit_results:
                    total_matches = qs.count()
                    limited_ids = list(qs.values_list('pk', flat=True)[:25])
                    qs = qs.filter(pk__in=limited_ids)
                    self.person_search_truncated = total_matches > 25
            else:
                qs = Person.objects.none()
            self.fields['person'].queryset = qs


class BaseQuoteFormSet(BaseInlineFormSet):
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['user'] = self.user
        return kwargs


QuoteFormSet = inlineformset_factory(
    Song,
    Quote,
    form=QuoteForm,
    formset=BaseQuoteFormSet,
    extra=1,
    can_delete=True,
)


class LyricsTranslationForm(forms.ModelForm):
    class Meta:
        model = LyricsTranslation
        fields = ['languagecode', 'translation', 'translator']
        widgets = {'translation': forms.Textarea(attrs={'rows': 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['languagecode'].queryset = LanguageCode.objects.all()
        if user:
            self.fields['translator'].queryset = Person.objects.for_user_with_skill(
                user=user, skill_id=Skill.TRANSLATOR
            )
        else:
            self.fields['translator'].queryset = Person.objects.none()


class BaseLyricsTranslationFormSet(BaseInlineFormSet):
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['user'] = self.user
        return kwargs


LyricsTranslationFormSet = inlineformset_factory(
    Song,
    LyricsTranslation,
    form=LyricsTranslationForm,
    formset=BaseLyricsTranslationFormSet,
    extra=1,
    can_delete=True,
)


class BaseResourceFormSet(BaseInlineFormSet):
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['user'] = self.user
        return kwargs

    def clean(self):
        if any(self.errors):
            for form in self.forms:
                form.errors.pop('__all__', None)


def make_resource_form(resource_model):
    class ResourceForm(forms.ModelForm):
        url = forms.URLField(
            label="Resource URL",
            required=False,
            widget=forms.URLInput(attrs={'placeholder': Resource._meta.get_field('url').verbose_name}),
        )
        description = forms.CharField(
            label="Description",
            required=False,
            widget=forms.Textarea(attrs={'placeholder': Resource._meta.get_field('description').verbose_name, "rows":1}),
        )

        class Meta:
            model = resource_model
            fields = []

        def __init__(self, *args, user=None, **kwargs):
            self.user = user
            super().__init__(*args, **kwargs)
            if self.instance.pk and self.instance.resource_id:
                self.fields['url'].initial = self.instance.resource.url
                self.fields['description'].initial = self.instance.resource.description

        def save(self, commit=True):
            url = self.cleaned_data.get('url')
            description = self.cleaned_data.get('description')
            if url:
                resource, created = Resource.objects.get_or_create(
                    url=url,
                    defaults={'owner': self.user, 'description': description}
                )
                if not created:
                    resource.description = description
                    resource.save(update_fields=['description'])
                self.instance.resource = resource
            return super().save(commit=commit)

    return ResourceForm


SongResourceForm = make_resource_form(SongResource)
PersonResourceForm = make_resource_form(PersonResource)
EventResourceForm = make_resource_form(EventResource)
EventSongResourceForm = make_resource_form(EventSongResource)

SongResourceFormSet = inlineformset_factory(
    Song, SongResource, form=SongResourceForm,
    formset=BaseResourceFormSet, extra=1, can_delete=True,
)
PersonResourceFormSet = inlineformset_factory(
    Person, PersonResource, form=PersonResourceForm,
    formset=BaseResourceFormSet, extra=1, can_delete=True,
)
EventResourceFormSet = inlineformset_factory(
    Event, EventResource, form=EventResourceForm,
    formset=BaseResourceFormSet, extra=1, can_delete=True,
)
EventSongResourceFormSet = inlineformset_factory(
    EventSong, EventSongResource, form=EventSongResourceForm,
    formset=BaseResourceFormSet, extra=1, can_delete=True,
)

ProjectResourceForm = make_resource_form(ProjectResource)

ProjectResourceFormSet = inlineformset_factory(
    Project, ProjectResource, form=ProjectResourceForm,
    formset=BaseResourceFormSet, extra=1, can_delete=True,
)


class MembershipPeriodForm(forms.ModelForm):
    class Meta:
        model = MembershipPeriod
        fields = ['role', 'started_at', 'ended_at']
        widgets = {
            'started_at': forms.DateInput(attrs={'type': 'date'}),
            'ended_at': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, person=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ended_at'].help_text = "Leave blank if still active"

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('started_at')
        end = cleaned.get('ended_at')
        if start and end and end < start:
            raise forms.ValidationError("End date must be after start date.")
        return cleaned


class BaseMembershipPeriodFormSet(BaseInlineFormSet):
    def __init__(self, *args, user=None, person=None, **kwargs):
        self.user = user
        self.person = person
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['user'] = self.user
        kwargs['person'] = self.person
        return kwargs

    def save_new(self, form, commit=True):
        obj = super().save_new(form, commit=False)
        obj.user = self.user
        if commit:
            obj.save()
        return obj

    def clean(self):
        if any(self.errors):
            return
        from collections import defaultdict
        by_role = defaultdict(list)
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            role = form.cleaned_data.get('role')
            start = form.cleaned_data.get('started_at')
            end = form.cleaned_data.get('ended_at')
            if role and start:
                by_role[role.id].append((start, end))
        for role_id, periods in by_role.items():
            periods.sort(key=lambda p: p[0])
            for i in range(len(periods) - 1):
                _, end_a = periods[i]
                start_b, _ = periods[i + 1]
                if end_a is None or start_b <= end_a:
                    raise forms.ValidationError("Periods for the same role must not overlap.")


MembershipPeriodFormSet = inlineformset_factory(
    Person, MembershipPeriod, fk_name='person',
    form=MembershipPeriodForm, formset=BaseMembershipPeriodFormSet,
    extra=1, can_delete=True,
)


class PollCreateForm(forms.ModelForm):
    import_active_members = forms.BooleanField(
        required=False,
        initial=True,
        label='Import active members'
    )

    class Meta:
        model = Poll
        fields = ['title', 'description']
        widgets = {
            "description": forms.Textarea(attrs={'rows': 3}),
        }


class PollPersonForm(forms.ModelForm):
    class Meta:
        model = PollPerson
        fields =  [
            'poll',
            'person'
        ]
        widgets = {
            'poll': forms.HiddenInput(),
        }

    def __init__(self, *args, org_user=None, poll=None, search_q=None, exclude_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and poll:
            already_added = poll.poll_persons.values_list('person_id', flat=True)
            exclude_pks = set(already_added) | set(exclude_ids or [])
            qs = Person.objects.in_org_user(org_user).exclude(pk__in=exclude_pks)
            if search_q:
                qs = qs.filter(
                    Q(first_name__icontains=search_q) |
                    Q(last_name__icontains=search_q) |
                    Q(roles__title__icontains=search_q) |
                    Q(skills__title__icontains=search_q) |
                    Q(singer__voice__name__icontains=search_q) |
                    Q(instrumentalist__instrument__name__icontains=search_q)
                ).distinct()
            self.fields['person'].queryset = qs


class PollEventForm(forms.ModelForm):
    event_type = forms.ModelChoiceField(
        queryset=EventType.objects.all(),
        empty_label=None,
        initial=EventType.REHEARSAL,
    )

    class Meta:
        model = PollEvent
        fields = [
            'poll',
            'event_type',
            'started_at',
            'ended_at',
            'location',
            'details'
        ]
        widgets = {
            'poll': forms.HiddenInput(),
            'started_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'ended_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'location': forms.Textarea(attrs={'rows': 2}),
            'details': forms.Textarea(attrs={'rows': 2}),
        }


class PollAttendanceForm(forms.ModelForm):
    class Meta:
        model = PollAttendance
        fields = [
            'poll_event',
            'poll_attendance_type',
            'poll_person',
            'comment'
        ]
        widgets = {
            'comment': forms.Textarea(attrs={'rows': 1}),
        }


class InvitationForm(forms.ModelForm):
    recipient_username = forms.CharField(
        max_length=250,
        widget=forms.TextInput(attrs={"autocomplete": "off"})
    )

    class Meta:
        model = Invitation
        fields = ['existing_person', 'copy_details', 'expires_at']
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, customuser, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['expires_at'].initial = timezone.now() + datetime.timedelta(days=7)
        is_org = Organization.objects.filter(user=customuser).exists()
        if is_org:
            self.fields['recipient_username'].label = "Username to invite"
            self.fields['existing_person'].queryset = Person.objects.unlinked_in_org(customuser)
            self.fields['existing_person'].label = "Link to existing member record (optional)"
            self.fields['existing_person'].empty_label = "-- Create new person on accept --"
            del self.fields['copy_details']
        else:
            self.fields['recipient_username'].label = "Organization username to request"
            self.fields['existing_person'].queryset = Person.objects.none()
            self.fields['existing_person'].widget = forms.HiddenInput()
            self.fields['existing_person'].required = False
            self.fields['copy_details'].label = (
                "Allow my profile details (name, email, address, phone, birth date) "
                "to be copied to the new member record"
            )

        self.order_fields(['recipient_username', 'existing_person', 'copy_details', 'expires_at'])


class InvitationAcceptForm(forms.Form):
    """Used by an organization admin when accepting a REQUEST, to optionally
    link the requester to an existing (unlinked) member record."""
    existing_person = forms.ModelChoiceField(
        queryset=Person.objects.none(),
        required=False,
        label="Link to existing member record (optional)",
    )

    def __init__(self, *args, organization_user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['existing_person'].queryset = Person.objects.unlinked_in_org(organization_user)
        self.fields['existing_person'].empty_label = "-- Create new member record --"