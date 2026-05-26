from django.db import models
from django.db.models import PROTECT, Q
from django.utils import timezone
from django.contrib.auth.models import  AbstractBaseUser, BaseUserManager, PermissionsMixin #AbstractUser,
from django.conf import settings


class Role(models.Model):
    ADMIN = 1
    MEMBER = 2
    SUPPORTER = 3
    EXTERNAL = 4

    title = models.CharField("name of role",max_length=50, unique=True)
    additional_notes = models.CharField("short explanation of role",max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class EventType(models.Model):
    REHEARSAL = 1
    PERFORMANCE = 2
    CONCERT = 3
    RECORDING = 4

    name = models.CharField("event designation", max_length=90, unique=True)
    additional_notes = models.CharField("short description of type", max_length=250, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Voice(models.Model):
    """
    All possible voice declarations, imported from fixtures.
    From Soprano 1 to Solo Bass 2.
    """
    name = models.CharField("voice", max_length=160, unique=True)
    additional_notes = models.CharField("additional notes", max_length=250, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Instrument(models.Model):
    """
    All possible instrument declarations, imported from fixtures.
    """
    name = models.CharField("instrument", max_length=160, unique=True)
    additional_notes = models.CharField("additional notes", max_length=250, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AttendanceType(models.Model):
    TBD = 0
    PRESENT = 1
    WORK_SCHOOL = 2
    ILLNESS = 3
    PRIVATE_VACATION = 4

    name = models.CharField("attendance designation", max_length=90, unique=True)
    additional_notes = models.CharField(
        "short description of presence",
        max_length=250,
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PollAttendanceType(models.Model):
    TBD = 0
    YES = 1
    MAYBE = 2
    NO = 3

    name = models.CharField("poll type", max_length=90, unique=True)

    def __str__(self):
        return self.name


class ApproximateDate(models.Model):
    """Flag of date approximations."""
    EXACT_DATE = 0
    MONTH_DAY_APPROX = 1
    YEAR_APPROX = 2

    approximation = models.CharField(max_length=2)
    additional_notes = models.CharField("short description of approx", max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.approximation


class LanguageCode(models.Model):
    """
    CHOICES = 'en', 'es', 'fr',...
    """
    language_code = models.CharField("language code", max_length=7, primary_key=True)

    def __str__(self):
        return self.language_code


class Resource(models.Model):
    """
    URL for external places.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="resources"
    )
    url = models.URLField("url", unique=True)
    description = models.TextField("description", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.description


class UserManager(BaseUserManager):
    """Custom user model manager for authentication."""
    def create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=250, unique=True)
    date_joined = models.DateTimeField("date joined", default=timezone.now)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    objects = UserManager()

    USERNAME_FIELD = "username"

    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return f"{self.username} - {self.email}"


class Organization(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    # auth account of the organization
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name="organizations",
        help_text="Organization auth hook"
    )

    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.name


class PersonQuerySet(models.QuerySet):
    """Intent for this queryset was to get filtering of composers and poets."""
    def with_skill(self, skill_id):
        """Filter persons who have a specific skill"""
        return self.filter(person_skill__skill_id=skill_id).distinct()

    def in_org_user(self, org_user):
        """Filter persons only from within organization."""
        return self.filter(
            memberships__user=org_user
        ).distinct()

    def for_user_with_skill(self, user, skill_id):
        """Generic method - any skill any organization"""
        return self.in_org_user(user).with_skill(skill_id)

    def active_performers(self, org_user, at_date):
        """Persons with an active MEMBER period at the given date.
        Used to determine who gets auto-populated into event attendance."""
        return self.filter(
            membership_period__user=org_user,
            membership_period__role_id=Role.MEMBER,
            membership_period__started_at__lte=at_date,
        ).filter(
            Q(membership_period__ended_at__gte=at_date) |
            Q(membership_period__ended_at__isnull=True)
        ).distinct()


class Skill(models.Model):
    """
    Title of the skill that each member has.
    Example: conductor, singer, musician, composer, poet, translator...
    """
    COMPOSER = 1
    POET = 2
    ARRANGER = 3
    SINGER = 4
    INSTRUMENTALIST = 5
    CONDUCTOR = 6
    TRANSLATOR = 7
    TECHNICIAN = 8

    title = models.CharField("name of skill",max_length=50, unique=True)
    additional_notes = models.CharField("short explanation of skill",max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title



class Person(models.Model):
    """
    One Person is under CustomUser, different Persons are owned by organizations.
    The CustomUser-Person has owner, the Org-Membership-Persons are many and fk to owner's Person.
    """
    first_name = models.CharField("name", max_length=100)
    last_name = models.CharField("surname", max_length=100)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone =  models.CharField(max_length=23, blank=True, null=True)
    birth_date = models.DateField("birthday", blank=True, null=True)
    birth_approximate = models.ForeignKey(ApproximateDate, on_delete=models.PROTECT, blank=True, null=True,
                                          related_name="birth_approximate")
    death_date = models.DateField("deathday", blank=True, null=True)
    death_approximate = models.ForeignKey(ApproximateDate, on_delete=models.PROTECT, blank=True, null=True,
                                          related_name="death_approximate")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="persons"
    ) # used to map login to actual user

    owner = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="owned_persons"
    )

    skills = models.ManyToManyField(
        Skill,
        through="PersonSkill",
        blank=True,
        related_name="persons"
    )

    roles = models.ManyToManyField(
        Role,
        through="PersonRole",
        blank=True,
        related_name="persons"
    )

    objects = PersonQuerySet.as_manager()

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                name="unique_user_per_person"
            )
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Membership(models.Model):
    """Base relationship between Person and AuthUser."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="memberships"
    )
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="memberships")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "person"],
                name="unique_membership_per_user_person"
            )
        ]


    def __str__(self):
        return f"{self.person} in {self.user}"


class MembershipPeriod(models.Model):
    """
    Tracks activity periods for each role assignment.
    Can have multiple periods of the same role, but only singular period at a given time.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="membership_period"
    )
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="membership_period")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="membership_period")
    started_at = models.DateField()
    ended_at = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'started_at', 'ended_at']),
            models.Index(fields=['person', 'started_at', 'ended_at']),
        ]



class PersonSkill(models.Model):
    """
    Relationship between Person(member) and Skill.
    Each Person(member) can have multiple skill entries.
    """
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="person_skill")
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="person_skill")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["person", "skill"],
                name="unique_skill_per_org_person"
            )
        ]


class PersonRole(models.Model):
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="person_role")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="person_role")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["person", "role"],
                name="unique_role_per_org_person"
            )
        ]


class PersonResource(models.Model):
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="person_resource")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="person_resource")
    order = models.PositiveIntegerField()



class Song(models.Model):
    title = models.CharField(max_length=250)
    number_of_pages = models.PositiveIntegerField(blank=True, null=True)
    number_of_copies = models.PositiveIntegerField(blank=True, null=True)

    composer = models.ForeignKey(
        Person,
        on_delete=PROTECT,
        related_name="composed_songs",
        limit_choices_to={'person_skill__skill_id': Skill.COMPOSER}
    )
    poet = models.ForeignKey(
        Person,
        on_delete=PROTECT,
        related_name="written_songs",
        limit_choices_to={'person_skill__skill_id': Skill.POET}
    )
    translator = models.ForeignKey(
        Person,
        on_delete=PROTECT,
        related_name="translated_songs",
        limit_choices_to={'person_skill__skill_id': Skill.TRANSLATOR},
        null=True,
        blank=True
    )

    year = models.IntegerField("year of creation", blank=True, null=True)
    group = models.CharField("type of song", max_length=250)
    number_of_voices = models.PositiveIntegerField(blank=True, null=True)
    keywords = models.CharField(max_length=255, blank=True, null=True)

    additional_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="songs"
    )

    internal_id = models.PositiveIntegerField("ID", blank=True, null=True)

    duration = models.PositiveIntegerField("duration in seconds", blank=True, null=True)

    lyrics = models.TextField("lyrics", blank=True, null=True)
    languagecode = models.ForeignKey(LanguageCode, on_delete=models.PROTECT, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "internal_id"],
                name="unique_id_per_org"
            )
        ]

    def __str__(self):
        return f"{self.title} - {self.composer.last_name}"


class Quote(models.Model):
    word = models.CharField(max_length=100)
    bar_number = models.CharField(max_length=20, blank=True, null=True)
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='quotes')

    class Meta:
        ordering = ['word']

    def __str__(self):
        if self.bar_number:
            return f"{self.word} ({self.bar_number})"
        return self.word


class SongResource(models.Model):
    song = models.ForeignKey(Song, on_delete=models.PROTECT, related_name="song_resource")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="song_resource")
    order = models.PositiveIntegerField()


class Project(models.Model):
    """Collection of Events under a common project."""
    title = models.CharField(max_length=250)
    details = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    guests = models.ManyToManyField(Person, blank=True, related_name="projects")
    songs = models.ManyToManyField(Song, blank=True, related_name="projects")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class ProjectResource(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_resource")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="project_resource")
    order = models.PositiveIntegerField()


class Event(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="events"
    )
    internal_id = models.PositiveIntegerField("ID", blank=True, null=True)
    name = models.CharField("name of the event", max_length=250)
    location = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField("start date hour")
    ended_at = models.DateTimeField("end date hour")
    event_type = models.ForeignKey(EventType, on_delete=models.PROTECT)
    details = models.TextField(blank=True, null=True)
    num_visitors = models.PositiveIntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    additional_notes = models.TextField(blank=True, null=True)
    producers = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    attendance_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(CustomUser, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='locked_events')
    locked_at = models.DateTimeField(null=True, blank=True)

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events'
    )


class EventSong(models.Model):
    """
    Through table for song objects that are in each event. Order matters.
    """
    event = models.ForeignKey(Event, on_delete=models.PROTECT)
    song = models.ForeignKey(Song, on_delete=models.PROTECT)
    order = models.IntegerField(null=True, blank=True)
    encore = models.BooleanField("additional songs after the end (encore)",blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "order"],
                name="unique_order_per_event"
            )
        ]


class EventResource(models.Model):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="event_resource")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="event_resource")
    order = models.PositiveIntegerField()


class EventSongResource(models.Model):
    event_song = models.ForeignKey(EventSong, on_delete=models.PROTECT, related_name="event_song_resource")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="event_song_resource")
    order = models.PositiveIntegerField()


class AttendanceQuerySet(models.QuerySet):
    def counted(self):
        """Exclude TBD (placeholder) attendance from counts"""
        return self.exclude(attendance_type_id=AttendanceType.TBD)


class Attendance(models.Model):
    """
    Designation of participation between event and person.
    Outputs: present, missing, absent, late, early departure.
    """
    event = models.ForeignKey(Event, on_delete=models.PROTECT)
    person = models.ForeignKey(Person, on_delete=models.PROTECT)
    attendance_type = models.ForeignKey(AttendanceType, on_delete=models.PROTECT)

    objects = models.Manager.from_queryset(AttendanceQuerySet)()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "person"],
                name="unique_person_per_event"
            )
        ]
        indexes = [
            models.Index(fields=['event', 'person']),
        ]


class Singer(models.Model):
    """Through table for person and voice."""
    person = models.ForeignKey(Person, on_delete=models.PROTECT)
    voice = models.ForeignKey(Voice, on_delete=models.PROTECT)



class Instrumentalist(models.Model):
    """Through table for person and instrument."""
    person = models.ForeignKey(Person, on_delete=models.PROTECT)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)


class LyricsTranslation(models.Model):
    """
    Place for the translation of lyrics.
    Translator is optional, language and song are mandatory.
    Each language has its own input.
    """
    translation = models.TextField()
    song = models.ForeignKey(Song, on_delete=models.PROTECT)
    languagecode = models.ForeignKey(LanguageCode, on_delete=models.PROTECT)
    translator = models.ForeignKey(Person, on_delete=models.PROTECT, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Poll(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="polls"
    )
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class PollPerson(models.Model):
    """Persons that are invited to the poll."""
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="poll_persons")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="poll_persons")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["poll", "person"],
                name="unique_person_per_poll"
            )
        ]


class PollEvent(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="poll_events")
    location = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField("start date hour")
    ended_at = models.DateTimeField("end date hour")
    event_type = models.ForeignKey(EventType, on_delete=models.CASCADE)
    details = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def same_date(self):
        if not self.ended_at:
            return True
        return self.started_at.date() == self.ended_at.date()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["poll", "location", "started_at", "ended_at"],
                name="unique_poll_location_date"
            )
        ]


class PollAttendance(models.Model):
    """Combines all poll models."""
    poll_event = models.ForeignKey(PollEvent, on_delete=models.CASCADE, related_name="poll_attendances")
    poll_attendance_type = models.ForeignKey(PollAttendanceType, on_delete=models.CASCADE, related_name="poll_attendances")
    poll_person = models.ForeignKey(PollPerson, on_delete=models.CASCADE, related_name="poll_attendances")
    comment = models.CharField(max_length=50, blank=True, null=True)



class Share(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    hash = models.CharField(max_length=32, unique=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, blank=True, null=True, related_name="share")
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, blank=True, null=True,  related_name="share")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, blank=True, null=True,  related_name="share")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, blank=True, null=True,  related_name="share")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(resource_id__isnull=False, poll_id__isnull=True, event_id__isnull=True, project_id__isnull=True) |
                    models.Q(resource_id__isnull=True, poll_id__isnull=False, event_id__isnull=True, project_id__isnull=True) |
                    models.Q(resource_id__isnull=True, poll_id__isnull=True, event_id__isnull=False, project_id__isnull=True) |
                    models.Q(resource_id__isnull=True, poll_id__isnull=True, event_id__isnull=True, project_id__isnull=False)
                ),
                name="share_only_one_fk"
            )
        ]

class ShareVisit(models.Model):
    id = models.AutoField(primary_key=True)
    share = models.ForeignKey(Share, on_delete=models.CASCADE, related_name="share_visits")
    visited_at = models.DateTimeField(auto_now_add=True)
    counter = models.PositiveIntegerField(default=0)