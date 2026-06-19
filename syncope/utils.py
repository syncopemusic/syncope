from .models import (Song, Membership, CustomUser, Attendance, AttendanceType,
                     Person, PersonRole, PersonSkill,
                     MembershipPeriod, Role, Skill, ApproximateDate,
                     Singer, Voice, Event, Project, EventType, EventSong,
                     LanguageCode, Instrument, Instrumentalist)
import csv, datetime
from datetime import datetime, date
from django.contrib import messages
from .permissions import AccessControl
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Min, Max
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


def add_query_param(url, params):
    """Add or update query parameters in a URL, preserving existing ones."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key, value in params.items():
        qs[key] = [str(value)]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))


INTERNAL_ID_KEY = "internal_id"
TITLE_KEY = "title"
COMPOSER_LAST_NAME_KEY = "composer_last_name"
COMPOSER_FIRST_NAME_KEY = "composer_first_name"
POET_LAST_NAME_KEY = "poet_last_name"
POET_FIRST_NAME_KEY = "poet_first_name"
TRANSLATOR_LAST_NAME_KEY = "translator_last_name"
TRANSLATOR_FIRST_NAME_KEY = "translator_first_name"
ARRANGER_LAST_NAME_KEY = "arranger_last_name"
ARRANGER_FIRST_NAME_KEY = "arranger_first_name"
YEAR_KEY = "year"
ENSEMBLE_KEY = "ensemble"
NUMBER_OF_PAGES_KEY = "number_of_pages"
NUMBER_OF_COPIES_KEY = "number_of_copies"
NUMBER_OF_VOICES_KEY = "number_of_voices"
KEYWORDS_KEY = "keywords"
LANGUAGE_CODE_KEY = "languagecode"
ADDITIONAL_NOTES_KEY = "additional_notes"
LYRICS_KEY = "lyrics"

ALLOWED_SONG_KEYS = [
    INTERNAL_ID_KEY,
    TITLE_KEY,
    COMPOSER_LAST_NAME_KEY,
    COMPOSER_FIRST_NAME_KEY,
    POET_LAST_NAME_KEY,
    POET_FIRST_NAME_KEY,
    TRANSLATOR_LAST_NAME_KEY,
    TRANSLATOR_FIRST_NAME_KEY,
    ARRANGER_LAST_NAME_KEY,
    ARRANGER_FIRST_NAME_KEY,
    YEAR_KEY,
    ENSEMBLE_KEY,
    NUMBER_OF_PAGES_KEY,
    NUMBER_OF_COPIES_KEY,
    NUMBER_OF_VOICES_KEY,
    KEYWORDS_KEY,
    LANGUAGE_CODE_KEY,
    ADDITIONAL_NOTES_KEY,
    LYRICS_KEY,
]

def _get_or_create_person_with_skill(org_user, last_name, first_name, skill_id, today):
    if not (last_name or first_name):
        return None
    existing = Person.objects.filter(
        last_name=last_name,
        first_name=first_name,
        memberships__user=org_user,
        person_skill__skill_id=skill_id
    ).first()
    if existing:
        return existing
    person = Person.objects.create(
        last_name=last_name,
        first_name=first_name,
        user=None,
        owner=None
    )
    Membership.objects.create(user=org_user, person=person)
    PersonRole.objects.create(person=person, role_id=Role.EXTERNAL)
    MembershipPeriod.objects.create(user=org_user, person=person, role_id=Role.EXTERNAL,
                                    started_at=today)
    PersonSkill.objects.create(person=person, skill_id=skill_id)
    return person

def import_songs(org_user, request, file_path, delimiter=";"):
    """Import songs from a CSV file into the database for a given organization user."""
    viewer_user = request.user
    imported_count = 0

    # Check if viewer can manage this org_user
    if request.user != org_user:
        has_permission = AccessControl.can_edit_event(
            request.user, org_user
        ).exists()

        if not has_permission:
            messages.error(request, "You don't have permission to import.")

    with open(file_path, 'r') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = reader.fieldnames
        messages.info(request, f"headers: {headers}")

        for h in headers:
            if h not in ALLOWED_SONG_KEYS:
                return None
        today = date.today()

        for row in reader:
            # Split the row data according to headers
            internal_id_value = (row.get(INTERNAL_ID_KEY) or '').strip()
            title_value = (row.get(TITLE_KEY) or '').strip()
            composer_last_name = (row.get(COMPOSER_LAST_NAME_KEY) or '').strip()
            composer_first_name = (row.get(COMPOSER_FIRST_NAME_KEY) or '').strip()
            poet_last_name = (row.get(POET_LAST_NAME_KEY) or '').strip()
            poet_first_name = (row.get(POET_FIRST_NAME_KEY) or '').strip()
            translator_last_name = (row.get(TRANSLATOR_LAST_NAME_KEY) or '').strip()
            translator_first_name = (row.get(TRANSLATOR_FIRST_NAME_KEY) or '').strip()
            arranger_last_name = (row.get(ARRANGER_LAST_NAME_KEY) or '').strip()
            arranger_first_name = (row.get(ARRANGER_FIRST_NAME_KEY) or '').strip()
            year_value = (row.get(YEAR_KEY) or '').strip()
            ensemble_value = (row.get(ENSEMBLE_KEY) or '').strip()
            number_of_pages_value = (row.get(NUMBER_OF_PAGES_KEY) or '').strip()
            number_of_copies_value = (row.get(NUMBER_OF_COPIES_KEY) or '').strip()
            number_of_voices_value = (row.get(NUMBER_OF_VOICES_KEY) or '').strip()
            keywords_value = (row.get(KEYWORDS_KEY) or '').strip()
            language_code_value = (row.get(LANGUAGE_CODE_KEY) or '').strip()
            additional_notes_value = (row.get(ADDITIONAL_NOTES_KEY) or '').strip()
            lyrics_value = (row.get(LYRICS_KEY) or '').strip()
            try:
                composer = _get_or_create_person_with_skill(
                    org_user, composer_last_name, composer_first_name, Skill.COMPOSER, today
                )
                poet = _get_or_create_person_with_skill(
                    org_user, poet_last_name, poet_first_name, Skill.POET, today
                )
                translator = _get_or_create_person_with_skill(
                    org_user, translator_last_name, translator_first_name, Skill.TRANSLATOR, today
                )
                arranger = _get_or_create_person_with_skill(
                    org_user, arranger_last_name, arranger_first_name, Skill.ARRANGER, today
                )

                languagecode = None
                if language_code_value:
                    languagecode = LanguageCode.objects.filter(language_code=language_code_value).first()

                Song.objects.create(   # Create new song with validated data
                    user=org_user,
                    internal_id=internal_id_value or None,  # Explicitly set None if empty
                    title=title_value,
                    composer=composer,
                    poet=poet,
                    translator=translator,
                    arranger=arranger,
                    number_of_pages=number_of_pages_value or None,
                    number_of_copies=number_of_copies_value or None,
                    number_of_voices=number_of_voices_value or None,
                    keywords=keywords_value or None,
                    languagecode=languagecode,
                    additional_notes=additional_notes_value or None,
                    lyrics=lyrics_value or None,
                    created_at=today,
                    updated_at=today,
                )
                imported_count += 1
            except Exception as e:
                message_text = f"Error importing row {reader.line_num}: {str(e)}"
                messages.error(request, message_text)
                continue  # Continue to next row on error

        return {
            'success': True,
            'count': imported_count
        }


FIRST_NAME_KEY = "first_name"
LAST_NAME_KEY = "last_name"
EMAIL_KEY = "email"
ADDRESS_KEY = "address"
BIRTH_DATE_KEY = "birth_date"
BIRTH_APPROX_KEY = "birth_date_approximation"
DEATH_DATE_KEY = "death_date"
DEATH_APPROX_KEY = "death_date_approximation"
LANDLINE_PHONE_KEY = "landline_phone"
MOBILE_PHONE_KEY = "mobile_phone"
VOICE_KEY = "voice"
INSTRUMENT_KEY = "instrument"
ACTIVITY_KEY = "activity"

ALLOWED_PERSON_KEYS = [
    FIRST_NAME_KEY,
    LAST_NAME_KEY,
    EMAIL_KEY,
    ADDRESS_KEY,
    BIRTH_DATE_KEY,
    BIRTH_APPROX_KEY,
    DEATH_DATE_KEY,
    DEATH_APPROX_KEY,
    LANDLINE_PHONE_KEY,
    MOBILE_PHONE_KEY,
    VOICE_KEY,
    INSTRUMENT_KEY,
    ACTIVITY_KEY,
]

REQUIRED_PERSON_KEYS = {FIRST_NAME_KEY, LAST_NAME_KEY}

OPTIONAL_PERSON_KEYS = {
    EMAIL_KEY, ADDRESS_KEY, BIRTH_DATE_KEY, BIRTH_APPROX_KEY,
    DEATH_DATE_KEY, DEATH_APPROX_KEY, LANDLINE_PHONE_KEY,
    MOBILE_PHONE_KEY, VOICE_KEY, INSTRUMENT_KEY, ACTIVITY_KEY,
}

VOICE_TYPES = {
    'Soprano': {"Soprano", "SOPRANO", "soprano", "Sopran", "SOPRAN", "sopran", "Sop", "SOP", "sop", "S", "s"},
    'Alto': {"Alto", "ALTO", "alto", "Alt", "ALT", "alt", "A", "a", "Contralto", "CONTRALTO", "contralto"},
    'Tenor': {"Tenor", "TENOR", "tenor", "Ten", "TEN", "ten", "T", "t"},
    'Bass': {"Bass", "BASS", "bass", "Basso", "BASSO", "basso", "Bas", "BAS", "bas", "B", "b"}
}



# Reverse mapping for O(1) lookup
VOICE_LOOKUP = {variant: voice for voice, variants in VOICE_TYPES.items() for variant in variants}


def import_persons(org_user, person_mode, request, file_path, delimiter=";"):
    """Import persons from CSV file."""
    imported_count = 0
    skipped_count = 0
    error_details = []

    # Check permissions
    if request.user != org_user:
        has_permission = AccessControl.can_edit_event(request.user, org_user).exists()
        if not has_permission:
            messages.error(request, "You don't have permission to import.")
            return {'success': False, 'count': 0, 'error': 'Permission denied'}

    # Helper: parse date from multiple formats
    def parse_bday(date_str):
        if not date_str:
            return None
        for fmt in ['%Y-%m-%d']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    # Helper: parse activity date ranges
    def parse_activity(activity_str):
        def parse_date(d):
            try:
                return datetime.strptime(d, '%Y-%m-%d').date()
            except ValueError:
                return None
        intervals = []
        for item in activity_str.split(','):
            item = item.strip()
            if not item:
                continue
            if item.endswith('-'):
                start = parse_date(item[:-1])
                if start:
                    intervals.append({'start': start, 'end': None})
            else:
                start = parse_date(item[0:10])
                end = parse_date(item[11:21])
                if start and end:
                    intervals.append({'start': start, 'end': end})
                else:
                    messages.error(request, f"wrong date format: {item}")

        return intervals

    # Helper: resolve approximation string to ApproximateDate FK instance
    def parse_approx(approx_str):
        if not approx_str or not approx_str.strip():
            return None
        return ApproximateDate.objects.filter(approximation=approx_str.strip()).first()

    # Process CSV
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = reader.fieldnames
        messages.info(request, f"{headers}")

        present_headers = set(headers or [])
        missing_required = REQUIRED_PERSON_KEYS - present_headers
        if missing_required:
            msg = f"CSV is missing required columns: {', '.join(sorted(missing_required))}"
            messages.error(request, msg)
            return {'success': False, 'count': 0, 'error': msg}
        present_optional = OPTIONAL_PERSON_KEYS & present_headers

        for row in reader:
            try:
                # Extract and clean data
                first_name = (row.get(FIRST_NAME_KEY) or '').strip()
                last_name = (row.get(LAST_NAME_KEY) or '').strip()
                email = (row.get(EMAIL_KEY) or '').strip() or None if EMAIL_KEY in present_optional else None
                address = (row.get(ADDRESS_KEY) or '').strip() or None if ADDRESS_KEY in present_optional else None
                birth_date = parse_bday(row.get(BIRTH_DATE_KEY) or '') if BIRTH_DATE_KEY in present_optional else None
                birth_approx = parse_approx(row.get(BIRTH_APPROX_KEY) or '') if BIRTH_APPROX_KEY in present_optional else None
                death_date = parse_bday(row.get(DEATH_DATE_KEY) or '') if DEATH_DATE_KEY in present_optional else None
                death_approx = parse_approx(row.get(DEATH_APPROX_KEY) or '') if DEATH_APPROX_KEY in present_optional else None
                phone = (row.get(MOBILE_PHONE_KEY) or row.get(LANDLINE_PHONE_KEY) or '').strip() or None \
                        if (MOBILE_PHONE_KEY in present_optional or LANDLINE_PHONE_KEY in present_optional) else None
                voice = (row.get(VOICE_KEY) or '').strip() if VOICE_KEY in present_optional else ''
                instrument = (row.get(INSTRUMENT_KEY) or '').strip() if INSTRUMENT_KEY in present_optional else ''
                activity_ranges = parse_activity(row.get(ACTIVITY_KEY) or '') if ACTIVITY_KEY in present_optional else []
                has_active = bool(activity_ranges and any(p['end'] is None for p in activity_ranges))

                if not first_name or not last_name:
                    raise ValueError(f"first_name and last_name are required (got: '{first_name}', '{last_name}')")

                existing = Person.objects.filter(
                    memberships__user=org_user,
                    first_name=first_name,
                    last_name=last_name
                ).first()

                if existing:
                    updates = {k: v for k, v in {
                        'email': email, 'address': address, 'phone': phone,
                        'birth_date': birth_date, 'birth_approximate': birth_approx,
                        'death_date': death_date, 'death_approximate': death_approx,
                    }.items() if v is not None}
                    if updates:
                        Person.objects.filter(pk=existing.pk).update(**updates)

                    PersonSkill.objects.get_or_create(person=existing, skill_id=person_mode)
                    Membership.objects.get_or_create(user=org_user, person=existing)

                    voice_type = VOICE_LOOKUP.get(voice)
                    if voice and voice_type:
                        voice_instance = Voice.objects.filter(name=voice_type).first()
                        if voice_instance:
                            Singer.objects.get_or_create(person=existing, defaults={'voice': voice_instance})

                    if instrument:
                        instrument_instance = Instrument.objects.filter(name=instrument).first()
                        if instrument_instance:
                            Instrumentalist.objects.get_or_create(person=existing, defaults={'instrument': instrument_instance})

                    for period in activity_ranges:
                        MembershipPeriod.objects.get_or_create(
                            user=org_user, person=existing, started_at=period['start'],
                            defaults={'role_id': Role.MEMBER, 'ended_at': period['end']}
                        )

                    if has_active:
                        PersonRole.objects.get_or_create(person=existing, role_id=Role.MEMBER)

                    imported_count += 1
                    continue

                with transaction.atomic():
                    person = Person.objects.create(
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        address=address,
                        birth_date=birth_date,
                        birth_approximate=birth_approx,
                        death_date=death_date,
                        death_approximate=death_approx,
                        phone=phone,
                        user=None,
                        owner=None
                    )
                    PersonSkill.objects.create(person=person, skill_id=person_mode)

                try:    # PersonSkill and Voice
                    voice_type = VOICE_LOOKUP.get(voice)
                    if voice_type:
                        voice_instance = Voice.objects.get(name=voice_type)
                        Singer.objects.create(person=person, voice=voice_instance)
                except Exception as e:
                    error_details.append(f"Row {reader.line_num} - Voice assignment failed for {first_name}: {str(e)}")

                try:    # Instrument
                    if instrument:
                        instrument_instance = Instrument.objects.get(name=instrument)
                        Instrumentalist.objects.create(person=person, instrument=instrument_instance)
                except Exception as e:
                    error_details.append(f"Row {reader.line_num} - Instrument assignment failed for {first_name}: {str(e)}")

                try: # Check if membership already exists to prevent duplicates
                    membership, created = Membership.objects.get_or_create(
                        user=org_user,
                        person=person
                    )
                    if created:
                        pass
                    else:
                        messages.info(request, f"Membership already exists for {org_user} and {first_name}")
                except Exception as e:
                    error_details.append(f"Row {reader.line_num} - Membership failed for {first_name}: {str(e)}")

                # MembershipPeriod
                for period in activity_ranges:    # Process membership periods
                    try:
                        MembershipPeriod.objects.create(
                            user=org_user,
                            person=person,
                            role_id=Role.MEMBER,
                            started_at=period['start'],
                            ended_at=period['end']
                        )
                    except Exception as e:
                        messages.info(request, f"Warning: Failed to create membership period for {first_name}: {str(e)}")
                        error_details.append(
                            f"Row {reader.line_num} - Membership period failed for {first_name}: {str(e)}")

                # Role
                try:
                    PersonRole.objects.create(
                        person=person,
                        role_id=Role.MEMBER if has_active else Role.EXTERNAL
                    )

                except Exception as e:
                    messages.info(request, f"Warning: Failed to assign role to {first_name}: {str(e)}")
                    error_details.append(f"Row {reader.line_num} - Role assignment failed for {first_name}: {str(e)}")

                imported_count += 1

            except Exception as e:
                skipped_count += 1
                error_details.append(f"Row {reader.line_num}: {str(e)}")
                continue

    messages.success(request, f"Import complete: {imported_count} imported, {skipped_count} skipped")

    return {
        'success': True,
        'count': imported_count,
        'skipped': skipped_count,
        'errors': len(error_details),
        'error_details': error_details
    }



EVENT_INTERNAL_ID_KEY = "internal_id"
EVENT_NAME_KEY = "title"
EVENT_LOCATION_CITY_KEY = "location_city"
# EVENT_LOCATION_RID_KEY = "location_rid"
EVENT_LOCATION_CUSTOM_KEY = "location_custom"
EVENT_START_DATE_KEY = "start_date"
EVENT_START_HOUR_KEY = "start_hour"
EVENT_ENDED_AT_KEY = "end_date"
EVENT_TYPE_KEY = "duration_rid"
EVENT_DETAILS_KEY = "description"
EVENT_NUM_VISITORS_KEY = "num_visitors"
EVENT_PROJECT_KEY = "project"
EVENT_INCOME_KEY = "income"
EVENT_OUTCOME_KEY = "outcome"
EVENT_ADDITIONAL_TEXTFIELD_KEY = "notes"
EVENT_PRODUCERS_GROUP_KEY = "producers_group"

ALLOWED_EVENT_KEYS = [
    EVENT_INTERNAL_ID_KEY,
    EVENT_NAME_KEY,
    EVENT_LOCATION_CITY_KEY,
    EVENT_LOCATION_CUSTOM_KEY,
    # EVENT_LOCATION_RID_KEY,
    EVENT_START_DATE_KEY,
    EVENT_START_HOUR_KEY,
    EVENT_ENDED_AT_KEY,
    EVENT_TYPE_KEY,
    EVENT_DETAILS_KEY,
    EVENT_NUM_VISITORS_KEY,
    EVENT_PROJECT_KEY,
    EVENT_ADDITIONAL_TEXTFIELD_KEY,
    EVENT_PRODUCERS_GROUP_KEY,
]


def import_events(org_user, request, file_path, delimiter=";"):
    """
    Import events from CSV file.
    duration_rid:  "KCME5Y5W"="Performance"
                   "GYTTXWT0"="Rehearsal"
                    else="Concert"
    """
    imported_count = 0
    skipped_count = 0
    error_details = []
    default_attendance_type = AttendanceType.objects.get(name="Present")

    def get_active_members(user, date):
        return Person.objects.filter(
            membership_period__user=user,
            membership_period__role_id=Role.MEMBER,
            membership_period__started_at__lte=date,
        ).filter(
            Q(membership_period__ended_at__gte=date) |
            Q(membership_period__ended_at__isnull=True)
        ).distinct()

    def populate_event_attendance(event, active_persons, attendance_type):
        existing = Attendance.objects.filter(event=event)
        existing_map = {a.person_id: a for a in existing}

        to_create = []
        to_update = []

        for person in active_persons:
            if person.id in existing_map:
                att = existing_map[person.id]
                if att.attendance_type_id != attendance_type.id:
                    att.attendance_type = attendance_type
                    to_update.append(att)
            else:
                to_create.append(
                    Attendance(
                        event=event,
                        person=person,
                        attendance_type=attendance_type
                    )
                )
        if to_create:
            Attendance.objects.bulk_create(to_create)

        if to_update:
            Attendance.objects.bulk_update(to_update, ["attendance_type"])

    # Check permissions
    if request.user != org_user:
        has_permission = AccessControl.can_edit_event(request.user, org_user).exists()
        if not has_permission:
            messages.error(request, "You don't have permission to import.")
            return {'success': False, 'count': 0, 'error': 'Permission denied'}

    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = reader.fieldnames
        messages.info(request, f"{headers}")

        for h in headers:
            valid_headers = [h for h in reader.fieldnames if h in ALLOWED_EVENT_KEYS]
            if not valid_headers:
                messages.error(request, "Your headers are wrong")
                return None

        touched_projects = {}
        for row in reader:
            f_row = {k: v for k, v in row.items() if k in valid_headers}
            try:
                with transaction.atomic():

                    internal_id = (f_row.get(EVENT_INTERNAL_ID_KEY) or '').strip() or None
                    name = (f_row.get(EVENT_NAME_KEY) or '').strip() or None
                    location_city = (f_row.get(EVENT_LOCATION_CITY_KEY) or '').strip() or None
                    # location_rid = (f_row.get(EVENT_LOCATION_RID_KEY) or '').strip() or None
                    location_custom = (f_row.get(EVENT_LOCATION_CUSTOM_KEY) or '').strip() or None
                    start_date = (f_row.get(EVENT_START_DATE_KEY) or '').strip()  # or None
                    start_hour = (f_row.get(EVENT_START_HOUR_KEY) or '').strip()  # or None
                    ended_at = (f_row.get(EVENT_ENDED_AT_KEY) or '').strip() or None
                    event_typo = (f_row.get(EVENT_TYPE_KEY) or '').strip() or None
                    details = (f_row.get(EVENT_DETAILS_KEY) or '').strip() or None
                    num_visitors = (f_row.get(EVENT_NUM_VISITORS_KEY) or '').strip() or None
                    project_title = (f_row.get(EVENT_PROJECT_KEY) or '').strip() or None
                    notes = (f_row.get(EVENT_ADDITIONAL_TEXTFIELD_KEY) or '').strip() or None
                    income = (f_row.get(EVENT_INCOME_KEY) or '').strip() or None
                    outcome = (f_row.get(EVENT_OUTCOME_KEY) or '').strip() or None
                    producers = (f_row.get(EVENT_PRODUCERS_GROUP_KEY) or '').strip() or None

                    location = f"{location_city}, {location_custom}"

                    started_at = datetime.combine(
                        datetime.fromisoformat(start_date).date(),
                        datetime.strptime(start_hour, "%H:%M").time()
                    )
                    started_at = timezone.make_aware(started_at)
                    event_date = started_at.date()
                    if ended_at:
                        try:
                            ended_at = timezone.make_aware(datetime.fromisoformat(ended_at))
                            ended_at = ended_at.replace(hour=23, minute=59, second=0, microsecond=0)
                        except (ValueError, TypeError):
                            ended_at = None
                    else:
                        ended_at = None

                    if event_typo == "KCME5Y5W":
                        event_type = EventType.objects.get(name="Performance")
                    elif event_typo == "GYTTXWT0":
                        event_type = EventType.objects.get(name="Rehearsal")
                    else:
                        event_type = EventType.objects.get(name="Concert")

                    additional_notes = "\n".join([
                        str(x) for x in [income, outcome, notes]
                        if x not in (None, "", "0")
                    ])

                    active_persons = get_active_members(org_user, event_date)

                    # Get or create project first (if applicable) before connecting to event
                    project = None
                    if project_title:
                        project, _ = Project.objects.get_or_create(
                            title=project_title,
                            user=org_user,
                            defaults={
                                'description': details,
                                'start_date': started_at,
                                'end_date': ended_at,
                            }
                        )
                        touched_projects[project.pk] = project

                    event = Event.objects.create(
                        user=org_user,
                        internal_id=internal_id,
                        name=name,
                        location=location,
                        started_at=started_at,
                        ended_at=ended_at,
                        event_type=event_type,
                        details=details,
                        num_visitors=num_visitors,
                        additional_notes=additional_notes,
                        producers=producers,
                        project=project,
                    )

                    populate_event_attendance(event, active_persons, default_attendance_type)


                    imported_count += 1

            except Exception as e:
                skipped_count += 1
                error_details.append(f"Row {reader.line_num}: {str(e)}")
                messages.info(request, f"Error processing row {reader.line_num}: {str(e)}")
                continue

    # Recalculate project timeframes to span all imported events
    for proj in touched_projects.values():
        agg = proj.events.aggregate(min_start=Min('started_at'), max_end=Max('ended_at'))
        if agg['min_start']:
            proj.start_date = agg['min_start'].date()
            proj.end_date = agg['max_end'].date()
            proj.save(update_fields=['start_date', 'end_date'])

    messages.success(request, f"Import complete: {imported_count} imported, {skipped_count} skipped")

    return {
        'success': True,
        'count': imported_count,
        'skipped': skipped_count,
        'errors': len(error_details),
        'error_details': error_details
    }



ATTENDANCE_MAP = {
    "+":1,
    "-":2,
    "o":4,
}

def import_attendance(org_user, request, file_path, delimiter=";"):
    """
    Import attendance from CSV file.
    Expected: headers as date (ISO format), first column as names; names as "first_name last_name(s)";
    Legend: "+" = present, "-" = absent, "o" = missing;
    """
    imported_count = 0
    skipped_count = 0
    error_details = []

    start_hour = "18:30"
    end_hour = "22:00"
    event_name = "rehearsal"
    event_type = EventType.objects.get(name="Rehearsal")

    # Check permissions
    if request.user != org_user:
        has_permission = AccessControl.can_edit_event(request.user, org_user).exists()
        if not has_permission:
            messages.error(request, "You don't have permission to import.")
            return {'success': False, 'count': 0, 'error': 'Permission denied'}

    with open(file_path, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file, delimiter=delimiter)
        headers = reader.fieldnames

        # First column is names, rest are dates
        name_column = headers[0]
        raw_dates = headers[1:]

        # Parse and validate dates
        parsed_dates = {}
        for d in raw_dates:
            try:
                parsed_dates[d] = datetime.fromisoformat(d).date()
            except ValueError:
                error_details.append(f"Invalid date format: {d}")
                continue

        # Direct attendance type mapping
        try:
            ATTENDANCE_MAP_DIRECT = {
                "+": AttendanceType.objects.get(id=AttendanceType.PRESENT),
                "-": AttendanceType.objects.get(id=AttendanceType.WORK_SCHOOL),
                "o": AttendanceType.objects.get(id=AttendanceType.PRIVATE_VACATION),
                "!": AttendanceType.objects.get(id=AttendanceType.ILLNESS),
            }
        except AttendanceType.DoesNotExist as e:
            messages.error(request, f"Missing AttendanceType configuration: {str(e)}")
            return {'success': False, 'count': 0, 'error': str(e)}

        # Create or fetch events for each date
        events = {}
        for raw_date, dt in parsed_dates.items():
            try:
                # Try to fetch existing event on this date
                event = Event.objects.filter(
                    user=org_user,
                    started_at__date=dt,
                ).first()

                if not event:
                    # Create new event if none exists
                    started_at = datetime.combine(
                        dt,
                        datetime.strptime(start_hour, "%H:%M").time()
                    )
                    started_at = timezone.make_aware(started_at)
                    ended_at = datetime.combine(
                        dt,
                        datetime.strptime(end_hour, "%H:%M").time()
                    )
                    ended_at = timezone.make_aware(ended_at)

                    event = Event.objects.create(
                        user=org_user,
                        started_at=started_at,
                        ended_at=ended_at,
                        name=event_name,
                        event_type=event_type,
                    )
                events[raw_date] = event
            except Exception as e:
                error_details.append(f"Error creating/fetching event for {raw_date}: {str(e)}")
                continue

        # Collect attendance records to process
        attendances_by_event = {}  # {event_id: {person_id: attendance_type}}

        # Process rows and collect attendance data
        for row in reader:
            try:
                with transaction.atomic():
                    # Parse name from first column
                    name_str = (row.get(name_column, "") or "").strip()
                    if not name_str:
                        error_details.append(f"Row {reader.line_num}: Empty name field")
                        skipped_count += 1
                        continue

                    name_parts = name_str.split()
                    first_name = name_parts[0]
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

                    # Find person in organization
                    person = Person.objects.filter(
                        first_name=first_name,
                        last_name=last_name,
                        memberships__user=org_user
                    ).first()

                    if not person:
                        error_details.append(
                            f"Row {reader.line_num}: Person '{first_name} {last_name}' not found in organization"
                        )
                        skipped_count += 1
                        continue

                    # Collect attendance entries for this person
                    for raw_date in parsed_dates.keys():
                        if raw_date not in events:
                            # Skip dates that failed to create/fetch events
                            continue

                        value = (row.get(raw_date, "") or "").strip()
                        if not value:
                            continue

                        # Map attendance code to type
                        attendance_type = ATTENDANCE_MAP_DIRECT.get(value)
                        if not attendance_type:
                            continue

                        event = events[raw_date]
                        if event.id not in attendances_by_event:
                            attendances_by_event[event.id] = {}

                        # Store person_id -> attendance_type mapping
                        attendances_by_event[event.id][person.id] = attendance_type

                    imported_count += 1

            except Exception as e:
                skipped_count += 1
                error_details.append(f"Row {reader.line_num}: {str(e)}")
                continue

        # Bulk process attendance records (create/update)
        for event_id, person_attendance_map in attendances_by_event.items():
            try:
                event = Event.objects.get(id=event_id)
                existing = Attendance.objects.filter(event=event)
                existing_map = {a.person_id: a for a in existing}

                to_create = []
                to_update = []

                for person_id, attendance_type in person_attendance_map.items():
                    if person_id in existing_map:
                        # Update if attendance type changed
                        att = existing_map[person_id]
                        if att.attendance_type_id != attendance_type.id:
                            att.attendance_type = attendance_type
                            to_update.append(att)
                    else:
                        # Create new attendance record
                        to_create.append(
                            Attendance(
                                event_id=event_id,
                                person_id=person_id,
                                attendance_type=attendance_type
                            )
                        )

                if to_create:
                    Attendance.objects.bulk_create(to_create)

                if to_update:
                    Attendance.objects.bulk_update(to_update, ["attendance_type"])

            except Exception as e:
                error_details.append(f"Error processing attendance for event {event_id}: {str(e)}")

        messages.success(
            request,
            f"Import complete: {imported_count} imported, {skipped_count} skipped"
        )

        return {
            'success': True,
            'count': imported_count,
            'skipped': skipped_count,
            'errors': len(error_details),
            'error_details': error_details
        }


def import_event_songs(org_user, request, file_path, delimiter=";"):
    """
    For importing songs into already existing events.
    Expected: first row contains dates (ISO format), no song column header.
    Each subsequent row contains song values (internal_id or title).
    Each column represents an event/date.
    Song order is determined by row position (top to bottom).
    On any error, entire operation is rolled back to keep database clean.
    """
    imported_count = 0
    error_details = []

    # Check permissions
    if request.user != org_user:
        has_permission = AccessControl.can_edit_event(request.user, org_user).exists()
        if not has_permission:
            messages.error(request, "You don't have permission to import.")
            return {'success': False, 'count': 0, 'error': 'Permission denied'}

    try:
        with transaction.atomic():
            with open(file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                headers = reader.fieldnames

                # All headers are dates
                date_columns = headers

                # Parse and validate dates
                parsed_dates = {}
                for d in date_columns:
                    try:
                        parsed_dates[d] = datetime.fromisoformat(d).date()
                    except ValueError:
                        error_details.append(f"Invalid date format in headers: {d}")

                if error_details:
                    raise ValueError(f"Header validation failed: {'; '.join(error_details)}")

                # Fetch events for each date (only fetch, don't create)
                events = {}
                for raw_date, dt in parsed_dates.items():
                    event = Event.objects.filter(
                        user=org_user,
                        started_at__date=dt,
                    ).first()

                    if not event:
                        raise ValueError(f"No event found for date: {raw_date}")

                    events[raw_date] = event

                # Collect and validate all song-event pairs before creating
                songs_to_create = []  # List of (event_id, song_id, order)

                # Track order counter per event
                order_per_event = {}

                # Process rows
                for row_num, row in enumerate(reader, start=1):
                    # Process each date column
                    for raw_date in date_columns:
                        song_value = (row.get(raw_date, "") or "").strip()
                        if not song_value:
                            continue

                        # Resolve song_value to a Song object
                        song = None
                        if song_value.isdigit():
                            song = Song.objects.filter(
                                user=org_user,
                                internal_id=song_value
                            ).first()
                        else:
                            song = Song.objects.filter(
                                user=org_user,
                                title=song_value
                            ).first()

                        if not song:
                            raise ValueError(
                                f"Row {row_num}: Song value '{song_value}' "
                                f"does not match any internal_id or title"
                            )

                        event = events[raw_date]

                        # Track order per event
                        if event.id not in order_per_event:
                            order_per_event[event.id] = 0

                        songs_to_create.append((event.id, song.id, order_per_event[event.id]))
                        order_per_event[event.id] += 1

                # If we got here, all validation passed - create the records
                if songs_to_create:
                    event_songs = [
                        EventSong(event_id=event_id, song_id=song_id, order=order)
                        for event_id, song_id, order in songs_to_create
                    ]
                    EventSong.objects.bulk_create(event_songs, ignore_conflicts=True)
                    imported_count = len(event_songs)

    except ValueError as e:
        error_details.append(str(e))
        messages.error(request, f"Import failed: {str(e)}")
        return {
            'success': False,
            'count': 0,
            'errors': len(error_details),
            'error_details': error_details
        }
    except Exception as e:
        error_details.append(f"Unexpected error: {str(e)}")
        messages.error(request, f"Import failed with error: {str(e)}")
        return {
            'success': False,
            'count': 0,
            'errors': len(error_details),
            'error_details': error_details
        }

    if error_details:
        messages.warning(request, f"Import complete: {imported_count} imported with {len(error_details)} warnings")
    else:
        messages.success(request, f"Import complete: {imported_count} songs imported")

    return {
        'success': True,
        'count': imported_count,
        'errors': len(error_details),
        'error_details': error_details
    }


def combine_event_projects(org_user, request):
    """
    Assign rehearsals to projects based on event timeline.

    For each project: find its last concert/performance/recording.
    Then: assign all rehearsals before that date to that project.
    """
    error_details = []

    # Check permissions
    if request.user != org_user:
        has_permission = AccessControl.can_edit_event(request.user, org_user).exists()
        if not has_permission:
            messages.error(request, "You don't have permission to combine events.")
            return {'success': False, 'count': 0, 'error': 'Permission denied'}

    try:
        with transaction.atomic():
            # Get all events, sorted by date
            all_events = Event.objects.filter(user=org_user).order_by('started_at')

            # Find each project's last ending event (concert/performance/recording)
            project_ends_at = {}  # project_id -> datetime of last ending event
            for event in all_events:
                if event.project_id and event.event_type_id in {EventType.CONCERT,  EventType.RECORDING}: # EventType.PERFORMANCE,
                    project_ends_at[event.project_id] = event.started_at

            # Build a sorted list of project end dates
            projects_by_end_date = sorted(project_ends_at.items(), key=lambda x: x[1])

            # For each unassigned rehearsal, find which project it belongs to
            updates = []
            for event in all_events:
                if event.event_type_id != EventType.REHEARSAL:
                    continue
                if event.project_id is not None:
                    continue  # already assigned

                # Find the project whose end date is >= this rehearsal
                for project_id, end_date in projects_by_end_date:
                    if event.started_at <= end_date:
                        event.project_id = project_id
                        updates.append(event)
                        break


            # Save all updated rehearsals
            if updates:
                Event.objects.bulk_update(updates, ['project'])

            messages.success(request, f"Combining complete: {len(updates)} rehearsals assigned to projects")

            return {
                'success': True,
                'count': len(updates),
                'errors': len(error_details),
                'error_details': error_details
            }

    except Exception as e:
        error_details.append(str(e))
        messages.error(request, f"Combining failed: {str(e)}")
        return {
            'success': False,
            'count': 0,
            'errors': len(error_details),
            'error_details': error_details
        }


RESOURCE_ICONS = {
    'video':      '▶',
    'audio':      '🎧',
    'sheet':      '𝄞',
    'wikipedia':  'Ⓦ',
    'doc':        '📄',
    'photo':      '📷',
    'other':      '🔗',
}


def get_url_info(url):
    url = url.lower()
    path = urlparse(url).path
    video_domains = ('youtube.com', 'youtu.be', 'vimeo.com', 'tiktok.com',)
    audio_domains = ('spotify.com', 'soundcloud.com', 'bandcamp.com', 'deezer.com', 'tidal.com', 'mixcloud.com',)
    sheet_music_domains = ('musescore.com', 'songsterr.com', 'flat.io', 'noteflight.com', 'imslp.org',)

    if any(domain in url for domain in video_domains):
        return 'video'
    if any(domain in url for domain in audio_domains):
        return 'audio'
    if any(domain in url for domain in sheet_music_domains):
        return 'sheet'

    if 'wikipedia.org' in url:
        return 'wikipedia'
    if path.endswith(('.pdf', '.doc', '.docx',)):
        return 'doc'
    if path.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg')):
        return 'photo'
    if path.endswith(('.mp3', '.m4a', '.flac', '.wav', '.aac', '.ogg', '.opus', '.wma', '.aiff', '.alac')):
        return 'audio'
    if path.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.wmv')):
        return 'video'
    if path.endswith(('.mid', '.midi', '.mscz', '.mscx', '.musicxml', '.mxl',)):
        return 'sheet'

    return 'other'


def resource_icon_list(resource_qs):
    from django.urls import reverse
    from syncope.models import Share

    resource_ids = [r.resource_id for r in resource_qs]
    share_map = {
        s.resource_id: s.pk
        for s in Share.objects.filter(resource_id__in=resource_ids)
    }

    return [
        {'url': r.resource.url,
         'share_url': reverse('syncope:share_visit', args=[share_map.get(r.resource_id)]) if r.resource_id in share_map else None,
         'icon': RESOURCE_ICONS[get_url_info(r.resource.url)],
         'desc': r.resource.description or r.resource.url}
        for r in resource_qs
    ]


