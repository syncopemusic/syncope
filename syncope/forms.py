from django import forms
import datetime
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils import timezone
from .models import CustomUser, Organization, Person, Song, Skill, Role, Quote, Project, Poll, PollPerson, PollEvent, \
    PollAttendance, Invitation
from .models import Event, EventSong, Attendance, AttendanceType,  Voice, Instrument, EventType, EventResource, EventSongResource
from .models import LyricsTranslation, LanguageCode, ApproximateDate, Resource, SongResource, PersonResource, ProjectResource
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.db.models import Q


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ("email", "username",)


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
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            # editing current user
            self.fields["email"].initial = self.instance.email
        elif user and user.is_authenticated:
            # new user - grab email from user
            self.fields["email"].initial = user.email

class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "email", "address"]


class OrgMemberForm(forms.Form):  # Person + Membership + MembershipPeriod
    VALID_PRESETS = {'composer', 'poet', 'translator'}
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
            external_role = Role.objects.filter(title__iexact='external').first()
            composer_skill = Skill.objects.filter(title__iexact="composer").first()
            if external_role and composer_skill:
                self.initial['roles'] = [external_role.id]
                self.initial["skills"] = [composer_skill.id]

        elif preset == 'poet':
            poet_skill = Skill.objects.filter(title__iexact="poet").first()
            external_role = Role.objects.filter(title__iexact="external").first()
            if poet_skill and external_role:
                self.initial['roles'] = [external_role.id]
                self.initial["skills"] = [poet_skill.id]

        elif preset == 'translator':
            translator_skill = Skill.objects.filter(title__iexact="translator").first()
            external_role = Role.objects.filter(title__iexact="external").first()
            if translator_skill and external_role:
                self.initial['roles'] = [external_role.id]
                self.initial["skills"] = [translator_skill.id]



class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ['word', 'bar_number']
        labels = {
            'word': 'Quote',
            'bar_number': 'Bar Number',
        }
        widgets = {
            'word': forms.TextInput(attrs={'placeholder': 'Quote text'}),
            'bar_number': forms.TextInput(attrs={'placeholder': '43'}),
        }


class SongForm(forms.ModelForm):
    class Meta:
        model = Song
        fields = [
            "internal_id",
            "title",
            "composer",
            "poet",
            "translator",
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user:
            self.fields['composer'].queryset = Person.objects.for_user_with_skill(user=user, skill_id=Skill.COMPOSER)
            self.fields['poet'].queryset = Person.objects.for_user_with_skill(user=user, skill_id=Skill.POET)
            self.fields['translator'].queryset = Person.objects.for_user_with_skill(user=user, skill_id=Skill.TRANSLATOR)


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
                  'details',
                  'project',
                  'producers',
                  'additional_notes',
                  'num_visitors',
                  ]
        widgets = {
            'started_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'ended_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'location': forms.Textarea(attrs={'rows': 3}),
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


class EventSongForm(forms.ModelForm):
    class Meta:
        model = EventSong
        fields = ['id', 'song', 'encore']
        widgets = {
            'id': forms.HiddenInput(),
            'song': forms.HiddenInput(),
            'encore': forms.CheckboxInput(),
        }


class EventSongFormSet(BaseInlineFormSet):
    def clean(self):
        if any(self.errors):
            for form in self.forms:
                form.errors.pop('__all__', None)


class SongChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, already_added_ids=None, **kwargs):
        self.already_added_ids = already_added_ids or set()
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        label = str(obj)
        if obj.pk in self.already_added_ids:
            return f"* {label}"
        return label


class AddSongToEventForm(forms.Form):
    encore = forms.BooleanField(required=False, label='Encore')

    def __init__(self, *args, org_user=None, event=None, search_q='', **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and event is not None:
            already_added_ids = set(event.eventsong_set.values_list('song_id', flat=True))
            qs = Song.objects.filter(user=org_user).order_by('title')
            if search_q:
                if search_q.isdigit():
                    qs = qs.filter(internal_id=int(search_q))
                else:
                    qs = qs.filter(
                        Q(title__icontains=search_q) |
                        Q(composer__last_name__icontains=search_q) |
                        Q(keywords__icontains=search_q)
                    ).distinct()
            self.fields['song'] = SongChoiceField(
                queryset=qs,
                already_added_ids=already_added_ids,
                widget=forms.Select(attrs={'size': '8'}),
                empty_label=None,
                label='Song',
            )


class EventChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, already_added_ids=None, other_project_ids=None, **kwargs):
        self.already_added_ids = already_added_ids or set()
        self.other_project_ids = other_project_ids or {}
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        # Format: "Event Name (2024-12-25 19:00 - 21:00)"
        if obj.started_at:
            time_str = obj.started_at.strftime('%Y-%m-%d %H:%M')
            if obj.ended_at:
                time_str += f" - {obj.ended_at.strftime('%H:%M')}"
        else:
            time_str = "No date"
        label = f"{obj.name} ({time_str})"
        if obj.pk in self.already_added_ids:
            return f"* {label}"
        if obj.pk in self.other_project_ids:
            other_project = self.other_project_ids[obj.pk]
            return f"⚠ {label} (in: {other_project})"
        return label


class AddEventToProjectForm(forms.Form):
    def __init__(self, *args, org_user=None, project=None, search_q='', **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and project is not None:
            already_added_ids = set(project.events.values_list('id', flat=True))
            qs = Event.objects.filter(user=org_user).order_by('-started_at')
            if search_q:
                qs = qs.filter(name__icontains=search_q)

            # Build a mapping of events in other projects
            other_project_ids = {}
            for event in qs.exclude(project__isnull=True):
                other_project_ids[event.pk] = event.project.title

            self.fields['event'] = EventChoiceField(
                queryset=qs,
                already_added_ids=already_added_ids,
                other_project_ids=other_project_ids,
                widget=forms.Select(attrs={'size': '8'}),
                empty_label=None,
                label='Event',
            )


class AddSongToProjectForm(forms.Form):
    def __init__(self, *args, org_user=None, project=None, search_q='', **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and project is not None:
            already_added_ids = set(project.songs.values_list('id', flat=True))
            qs = Song.objects.filter(user=org_user).order_by('title')
            if search_q:
                if search_q.isdigit():
                    qs = qs.filter(internal_id=int(search_q))
                else:
                    qs = qs.filter(
                        Q(title__icontains=search_q) |
                        Q(composer__last_name__icontains=search_q) |
                        Q(keywords__icontains=search_q)
                    ).distinct()
            self.fields['song'] = SongChoiceField(
                queryset=qs,
                already_added_ids=already_added_ids,
                widget=forms.Select(attrs={'size': '8'}),
                empty_label=None,
                label='Song',
            )


class AddGuestToProjectForm(forms.Form):
    def __init__(self, *args, org_user=None, project=None, search_q='', **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and project is not None:
            already_added_ids = set(project.guests.values_list('id', flat=True))
            qs = Person.objects.filter(
                membership_period__user=org_user,
            ).distinct()
            if search_q:
                qs = qs.filter(
                    Q(first_name__icontains=search_q) |
                    Q(last_name__icontains=search_q)
                ).distinct()
            qs = qs.order_by('last_name', 'first_name')
            self.fields['guest'] = forms.ModelChoiceField(
                queryset=qs,
                widget=forms.Select(attrs={'size': '8'}),
                empty_label=None,
                label='Guest',
            )


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['id', 'person', 'attendance_type']
        widgets = {
            'id': forms.HiddenInput(),
            'person': forms.HiddenInput(),
            'attendance_type': forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        person_queryset = kwargs.pop('person_queryset', None)
        kwargs.pop('user', None)
        kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        if person_queryset is not None:
            if self.instance and self.instance.person_id:
                self.fields['person'].queryset = Person.objects.filter(
                    Q(pk__in=person_queryset) | Q(pk=self.instance.person_id)
                )
            else:
                self.fields['person'].queryset = person_queryset



class AddAttendanceForm(forms.Form):
    """Admin-only form to add any org person to an event's attendance."""
    person = forms.ModelChoiceField(
        queryset=Person.objects.none(),
        widget=forms.Select(attrs={'size': '8'}),
        empty_label=None,
        label='Person',
    )
    attendance_type = forms.ModelChoiceField(
        queryset=AttendanceType.objects.all(),
        widget=forms.RadioSelect(),
        label='Attendance Type',
    )

    def __init__(self, *args, org_user=None, event=None, search_q='', **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and event:
            from django.db.models import Exists, OuterRef, ExpressionWrapper, BooleanField
            from .models import Singer, Instrumentalist
            already_attending = event.attendance_set.values_list('person_id', flat=True)
            qs = Person.objects.filter(
                membership_period__user=org_user,
            ).exclude(
                id__in=already_attending
            ).distinct()
            if search_q:
                qs = qs.filter(
                    Q(first_name__icontains=search_q) |
                    Q(last_name__icontains=search_q) |
                    Q(singer__voice__name__icontains=search_q) |
                    Q(instrumentalist__instrument__name__icontains=search_q)
                ).distinct()
            qs = qs.annotate(
                is_performer=ExpressionWrapper(
                    Exists(Singer.objects.filter(person=OuterRef('pk'))) |
                    Exists(Instrumentalist.objects.filter(person=OuterRef('pk'))),
                    output_field=BooleanField()
                )
            ).order_by('-is_performer', 'last_name', 'first_name')
            self.fields['person'].queryset = qs


EventSongFormSet = inlineformset_factory(
    Event,
    EventSong,
    form=EventSongForm,
    formset=EventSongFormSet,
    extra=0,
    can_delete=True,
)

AttendanceFormSet = inlineformset_factory(
    Event,
    Attendance,
    form=AttendanceForm,
    extra=0,
    can_delete=True,
)

QuoteFormSet = inlineformset_factory(
    Song,
    Quote,
    form=QuoteForm,
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

    def __init__(self, *args, org_user=None, poll=None, search_q=None, **kwargs):
        super().__init__(*args, **kwargs)
        if org_user and poll:
            already_added = poll.poll_persons.values_list('person_id', flat=True)
            qs = Person.objects.in_org_user(org_user).exclude(pk__in=already_added)
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


class PollBulkImportForm(forms.Form):
    role_criteria = forms.ChoiceField(required=False, label='Role')
    skill_criteria = forms.ChoiceField(required=False, label='Skill')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role_criteria'].choices = [('all', 'All roles')] + list(
            Role.objects.values_list('title', 'title')
        )
        self.fields['skill_criteria'].choices = [('all', 'All skills')] + list(
            Skill.objects.values_list('title', 'title')
        )


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