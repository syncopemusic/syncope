from datetime import date, datetime, timedelta

from django.http import QueryDict
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from syncope.models import (
    Attendance, AttendanceType, CustomUser, Event, EventResource, EventSong, EventSongResource, EventType,
    Invitation, InvitationStatus, InvitationType, LyricsTranslation, Membership, MembershipPeriod, Organization,
    Person, PersonRole, PersonSkill, Poll, PollPerson, Project, Resource, Role, Singer, Skill, Song, Voice,
)
from syncope.utils import filter_period, parse_date_query, parse_filters


class ProjectEditPermissionTests(TestCase):
    """Only the org account (or an ADMIN member) may reach the Project edit subpages."""

    fixtures = ["syncope/fixture_role.json"]

    def setUp(self):
        self.org_user = CustomUser.objects.create_user(
            username="org", email="org@example.com", password="pw12345"
        )
        Person.objects.create(user=self.org_user, email=self.org_user.email, first_name="Org", last_name="Owner")
        self.outsider = CustomUser.objects.create_user(
            username="outsider", email="outsider@example.com", password="pw12345"
        )
        Person.objects.create(user=self.outsider, email=self.outsider.email, first_name="Out", last_name="Sider")
        self.project = Project.objects.create(user=self.org_user, title="Test Project")

    def test_org_owner_can_reach_meta_edit(self):
        self.client.login(username="org", password="pw12345")
        url = reverse("syncope:project_meta_edit", kwargs={"username": "org", "pk": self.project.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_outsider_is_forbidden_from_meta_edit(self):
        self.client.login(username="outsider", password="pw12345")
        url = reverse("syncope:project_meta_edit", kwargs={"username": "org", "pk": self.project.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_outsider_cannot_add_song(self):
        self.client.login(username="outsider", password="pw12345")
        url = reverse("syncope:project_songs_edit", kwargs={"username": "org", "pk": self.project.pk})
        response = self.client.post(url, {"add_song": ["1"]})
        self.assertEqual(response.status_code, 403)


class ProjectStagedEditTests(TestCase):
    """The Events/Songs/Participants subpages commit staged adds/removes in one batched POST
    (mirrors the event Attendance/Songs subpages' save-bar pattern)."""

    fixtures = ["syncope/fixture_role.json"]

    def setUp(self):
        self.org_user = CustomUser.objects.create_user(
            username="org", email="org@example.com", password="pw12345"
        )
        Person.objects.create(user=self.org_user, email=self.org_user.email, first_name="Org", last_name="Owner")
        self.project = Project.objects.create(user=self.org_user, title="Test Project")
        self.client.login(username="org", password="pw12345")

    def test_add_and_remove_song(self):
        song = Song.objects.create(user=self.org_user, title="Test Song")
        url = reverse("syncope:project_songs_edit", kwargs={"username": "org", "pk": self.project.pk})

        self.client.post(url, {"add_song": [str(song.pk)]})
        self.assertIn(song, self.project.songs.all())

        self.client.post(url, {f"remove_{song.pk}": "1"})
        self.assertNotIn(song, self.project.songs.all())

    def test_add_and_remove_event(self):
        event_type = EventType.objects.create(name="Rehearsal")
        event = Event.objects.create(user=self.org_user, name="Test Event", event_type=event_type)
        url = reverse("syncope:project_events_edit", kwargs={"username": "org", "pk": self.project.pk})

        self.client.post(url, {"add_event": [str(event.pk)]})
        event.refresh_from_db()
        self.assertEqual(event.project_id, self.project.pk)

        self.client.post(url, {f"remove_{event.pk}": "1"})
        event.refresh_from_db()
        self.assertIsNone(event.project_id)

    def test_song_events_edit_add_remove_and_search(self):
        song = Song.objects.create(user=self.org_user, title="Test Song")
        other = Song.objects.create(user=self.org_user, title="Other Song")
        event_type = EventType.objects.create(name="Rehearsal")
        event = Event.objects.create(user=self.org_user, name="Test Event", event_type=event_type)
        EventSong.objects.create(event=event, song=other, order=1)
        kwargs = {"username": "org", "pk": song.pk}
        url = reverse("syncope:song_events_edit", kwargs=kwargs)
        search = reverse("syncope:song_events_search", kwargs=kwargs)

        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(search, {"q": "Test"}), f'data-id="{event.pk}"')

        self.client.post(url, {"add_event": [str(event.pk)]})
        self.assertEqual(EventSong.objects.get(event=event, song=song).order, 2)
        self.assertNotContains(self.client.get(search, {"q": "Test"}), f'data-id="{event.pk}"')
        self.assertContains(self.client.get(reverse("syncope:song_detail", kwargs=kwargs)), "Test Event")

        self.client.post(url, {f"remove_{event.pk}": "1"})
        self.assertFalse(EventSong.objects.filter(event=event, song=song).exists())
        self.assertTrue(EventSong.objects.filter(event=event, song=other).exists())

    def test_add_guest_and_remove_auto_member(self):
        guest = Person.objects.create(first_name="Gia", last_name="Guest")
        MembershipPeriod.objects.create(
            user=self.org_user, person=guest, role_id=Role.EXTERNAL, started_at=date(2020, 1, 1)
        )
        member = Person.objects.create(first_name="Mia", last_name="Member")
        MembershipPeriod.objects.create(
            user=self.org_user, person=member, role_id=Role.MEMBER, started_at=date(2020, 1, 1)
        )
        url = reverse("syncope:project_participants_edit", kwargs={"username": "org", "pk": self.project.pk})

        self.client.post(url, {"add_guest": [str(guest.pk)]})
        self.assertIn(guest, self.project.guests.all())

        self.client.post(url, {f"remove_{member.pk}": "1"})
        self.assertIn(member, self.project.excluded_members.all())


class OrgMemberEditInvalidPeriodTests(TestCase):
    """A membership period that fails validation must block the whole save, not be dropped silently."""

    fixtures = ["syncope/fixture_role.json"]

    def test_invalid_period_re_renders_and_saves_nothing(self):
        org = CustomUser.objects.create_user(username="org", email="org@example.com", password="pw12345")
        Person.objects.create(user=org, email=org.email, first_name="Org", last_name="Owner")
        person = Person.objects.create(first_name="Mia", last_name="Member")
        Membership.objects.create(user=org, person=person)
        self.client.login(username="org", password="pw12345")
        url = reverse("syncope:org_member_edit", kwargs={"username": "org", "pk": person.pk})

        response = self.client.post(url, {
            "first_name": "Changed", "last_name": "Member",
            "periods-TOTAL_FORMS": "1", "periods-INITIAL_FORMS": "0",
            "periods-0-role": str(Role.MEMBER), "periods-0-started_at": "2021-01-01", "periods-0-ended_at": "2020-01-01",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "End date must be after start date.")
        person.refresh_from_db()
        self.assertEqual(person.first_name, "Mia")


class SongSubpageTests(TestCase):
    """Song editing is split across Meta/Lyrics subpages (mirrors Project/Event)."""

    fixtures = ["syncope/fixture_role.json", "syncope/fixture_skill.json"]

    def setUp(self):
        self.org_user = CustomUser.objects.create_user(
            username="org", email="org@example.com", password="pw12345"
        )
        Person.objects.create(user=self.org_user, email=self.org_user.email, first_name="Org", last_name="Owner")
        self.song = Song.objects.create(user=self.org_user, title="Test Song", internal_id=1)
        self.client.login(username="org", password="pw12345")

    def test_subpages_render(self):
        for url_name in ("song_meta_edit", "song_lyrics_edit", "song_resources_edit"):
            url = reverse(f"syncope:{url_name}", kwargs={"username": "org", "pk": self.song.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url_name)

        new_url = reverse("syncope:song_new", kwargs={"username": "org"})
        self.assertEqual(self.client.get(new_url).status_code, 200)

    def test_create_assigns_next_internal_id_and_lands_on_detail(self):
        url = reverse("syncope:song_new", kwargs={"username": "org"})
        response = self.client.post(url, {"title": "New Song"})
        new_song = Song.objects.get(title="New Song")
        self.assertEqual(new_song.internal_id, 2)
        self.assertRedirects(
            response, reverse("syncope:song_detail", kwargs={"username": "org", "pk": new_song.pk})
        )

    def test_meta_edit_saves_composer_via_picker_field(self):
        composer = Person.objects.create(first_name="Woody", last_name="Composer")
        Membership.objects.create(user=self.org_user, person=composer)
        PersonSkill.objects.create(person=composer, skill_id=Skill.COMPOSER)

        url = reverse("syncope:song_meta_edit", kwargs={"username": "org", "pk": self.song.pk})
        self.client.post(url, {"title": "Test Song", "composer": str(composer.pk)})

        self.song.refresh_from_db()
        self.assertEqual(self.song.composer_id, composer.pk)

    def test_song_person_search_scopes_by_skill(self):
        composer = Person.objects.create(first_name="Woody", last_name="Composer")
        Membership.objects.create(user=self.org_user, person=composer)
        PersonSkill.objects.create(person=composer, skill_id=Skill.COMPOSER)

        url = reverse("syncope:song_person_search", kwargs={"username": "org", "field": "composer"})
        response = self.client.get(url, {"q": "Woody"})
        self.assertContains(response, "Woody Composer")

        response = self.client.get(url, {"q": "Nobody"})
        self.assertNotContains(response, "Woody Composer")

    def test_song_person_search_matches_full_name_and_leading_space(self):
        composer = Person.objects.create(first_name="Woody", last_name="Composer")
        Membership.objects.create(user=self.org_user, person=composer)
        PersonSkill.objects.create(person=composer, skill_id=Skill.COMPOSER)

        url = reverse("syncope:song_person_search", kwargs={"username": "org", "field": "composer"})
        response = self.client.get(url, {"q": "Woody Composer"})
        self.assertContains(response, "Woody Composer")

        response = self.client.get(url, {"q": " Woody"})
        self.assertContains(response, "Woody Composer")

    def test_lyrics_edit_saves_lyrics_and_language(self):
        from syncope.models import LanguageCode
        language = LanguageCode.objects.create(language_code="en")
        url = reverse("syncope:song_lyrics_edit", kwargs={"username": "org", "pk": self.song.pk})
        response = self.client.post(url, {
            "lyrics": "La la la",
            "languagecode": str(language.pk),
            "translations-TOTAL_FORMS": "0", "translations-INITIAL_FORMS": "0",
            "translations-MIN_NUM_FORMS": "0", "translations-MAX_NUM_FORMS": "1000",
        })
        self.song.refresh_from_db()
        self.assertEqual(self.song.lyrics, "La la la")
        self.assertEqual(self.song.languagecode_id, language.pk)
        self.assertRedirects(
            response, reverse("syncope:song_lyrics_edit", kwargs={"username": "org", "pk": self.song.pk})
        )


class ResourcesEditViewTests(TestCase):
    """One view/template covers Song/Event/Project/Person resources - exercised here via Song."""

    fixtures = ["syncope/fixture_role.json"]

    def setUp(self):
        self.org_user = CustomUser.objects.create_user(
            username="org", email="org@example.com", password="pw12345"
        )
        Person.objects.create(user=self.org_user, email=self.org_user.email, first_name="Org", last_name="Owner")
        self.outsider = CustomUser.objects.create_user(
            username="outsider", email="outsider@example.com", password="pw12345"
        )
        self.song = Song.objects.create(user=self.org_user, title="Test Song")
        self.url = reverse("syncope:song_resources_edit", kwargs={"username": "org", "pk": self.song.pk})

    def test_outsider_forbidden(self):
        self.client.login(username="outsider", password="pw12345")
        response = self.client.post(self.url, {"order": ""})
        self.assertEqual(response.status_code, 403)

    def test_add_resource_scoped_to_an_event_creates_event_song_resource(self):
        event_type = EventType.objects.create(name="Rehearsal")
        event = Event.objects.create(user=self.org_user, name="Test Event", event_type=event_type)
        event_song = EventSong.objects.create(event=event, song=self.song, order=1)

        self.client.login(username="org", password="pw12345")
        get_response = self.client.get(self.url)
        self.assertContains(get_response, str(event))

        self.client.post(self.url, {
            "order": "n0",
            "new_url": ["https://a.example/"],
            "new_description": ["A"],
            "new_setlist_id": [str(event_song.pk)],
        })

        self.assertEqual(self.song.song_resource.count(), 0)
        esr = EventSongResource.objects.get(event_song__event=event, event_song__song=self.song)
        self.assertEqual(esr.resource.url, "https://a.example/")

    def test_add_reorder_and_remove(self):
        self.client.login(username="org", password="pw12345")

        self.client.post(self.url, {
            "order": "n0,n1",
            "new_url": ["https://a.example/", "https://b.example/"],
            "new_description": ["A", "B"],
        })
        self.assertEqual(self.song.song_resource.count(), 2)
        first, second = self.song.song_resource.select_related("resource").order_by("order")
        self.assertEqual(first.resource.url, "https://a.example/")
        self.assertEqual(second.resource.url, "https://b.example/")

        # reorder: second becomes first
        self.client.post(self.url, {"order": f"r{second.pk},r{first.pk}"})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.order, 1)
        self.assertEqual(first.order, 2)

        # remove the (now second) row
        self.client.post(self.url, {"order": f"r{second.pk}", f"remove_{first.pk}": "1"})
        self.assertEqual(self.song.song_resource.count(), 1)
        self.assertEqual(self.song.song_resource.first().pk, second.pk)


class ResourcesEditOtherKindsRenderTests(TestCase):
    """Detail pages and the Resources edit page render for the other three owner kinds too."""

    fixtures = ["syncope/fixture_role.json", "syncope/fixture_eventtype.json"]

    def setUp(self):
        self.org_user = CustomUser.objects.create_user(
            username="org", email="org@example.com", password="pw12345"
        )
        Person.objects.create(user=self.org_user, email=self.org_user.email, first_name="Org", last_name="Owner")
        self.project = Project.objects.create(user=self.org_user, title="Test Project")
        self.event = Event.objects.create(user=self.org_user, name="Test Event", event_type_id=EventType.REHEARSAL)
        self.person = Person.objects.create(first_name="Mia", last_name="Member")
        Membership.objects.create(user=self.org_user, person=self.person)
        self.client.login(username="org", password="pw12345")

    def test_detail_pages_render(self):
        self.assertEqual(
            self.client.get(reverse("syncope:project_detail", kwargs={"username": "org", "pk": self.project.pk})).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("syncope:event_detail", kwargs={"username": "org", "pk": self.event.pk})).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("syncope:org_member_detail", kwargs={"username": "org", "pk": self.person.pk})).status_code, 200
        )

    def test_resources_edit_pages_render_for_each_kind(self):
        for url_name, pk in (
            ("project_resources_edit", self.project.pk),
            ("event_resources_edit", self.event.pk),
            ("person_resources_edit", self.person.pk),
        ):
            url = reverse(f"syncope:{url_name}", kwargs={"username": "org", "pk": pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url_name)

    def test_return_button_preserves_event_origin(self):
        """Reached from the Attendance dashboard (?origin=attendance), Return/Save-redirect
        must go back to event_detail?origin=attendance, not the Events-root default."""
        event_detail_url = reverse("syncope:event_detail", kwargs={"username": "org", "pk": self.event.pk})
        edit_url = reverse("syncope:event_resources_edit", kwargs={"username": "org", "pk": self.event.pk})

        get_response = self.client.get(edit_url, {"origin": "attendance"})
        self.assertContains(get_response, f'href="{event_detail_url}?origin=attendance"')

        post_response = self.client.post(f"{edit_url}?origin=attendance", {"order": ""})
        self.assertEqual(post_response.status_code, 302)
        self.assertIn("origin=attendance", post_response.url)

    def test_return_button_defaults_for_project_and_person(self):
        for url_name, detail_name, pk in (
            ("project_resources_edit", "project_detail", self.project.pk),
            ("person_resources_edit", "org_member_detail", self.person.pk),
        ):
            edit_url = reverse(f"syncope:{url_name}", kwargs={"username": "org", "pk": pk})
            detail_url = reverse(f"syncope:{detail_name}", kwargs={"username": "org", "pk": pk})
            response = self.client.get(edit_url)
            self.assertContains(response, f'href="{detail_url}"', msg_prefix=url_name)


class LoginByDefaultTests(TestCase):
    fixtures = ["syncope/fixture_role.json"]

    def setUp(self):
        self.user = CustomUser.objects.create_user(username="me", email="me@example.com", password="pw12345")
        Person.objects.create(user=self.user, email=self.user.email, first_name="Me", last_name="Self")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("syncope:song_list", kwargs={"username": "me"}))
        self.assertRedirects(response, "/login/?next=/me/songs/")

    def test_auth_pages_public(self):
        for name in ("syncope:login", "syncope:signup"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_home_forwards_to_user_dashboard(self):
        self.client.login(username="me", password="pw12345")
        dashboard = reverse("syncope:org_dashboard", kwargs={"username": "me"})
        self.assertRedirects(self.client.get(reverse("syncope:home")), dashboard)
        self.assertContains(self.client.get(dashboard), "Make your own organization")

    def test_reserved_username_rejected(self):
        from syncope.forms import CustomUserCreationForm
        form = CustomUserCreationForm({"email": "x@example.com", "username": "home",
                                       "password1": "pw-12345-xyz", "password2": "pw-12345-xyz"})
        self.assertIn("username", form.errors)


class AttendanceFilterTests(TestCase):
    fixtures = ["syncope/fixture_role.json", "syncope/fixture_attendancetype.json"]

    def setUp(self):
        self.org = CustomUser.objects.create_user(username="org", email="org@example.com", password="pw12345")
        self.client.login(username="org", password="pw12345")
        self.rehearsal = EventType.objects.create(name="Rehearsal")
        self.concert = EventType.objects.create(name="Concert")
        now = timezone.now()
        self.old = Event.objects.create(user=self.org, name="old", event_type=self.rehearsal,
                                        started_at=now - timedelta(days=60), ended_at=now - timedelta(days=60))
        self.recent = [Event.objects.create(user=self.org, name=f"r{i}", event_type=self.rehearsal,
                                            started_at=now - timedelta(days=i + 1), ended_at=now - timedelta(days=i + 1))
                       for i in range(4)]
        self.gig = Event.objects.create(user=self.org, name="gig", event_type=self.concert,
                                        started_at=now - timedelta(days=2), ended_at=now - timedelta(days=2))
        self.url = reverse("syncope:attendance", kwargs={"username": "org"})

    def shown(self, **params):
        return {e.name for e in self.client.get(self.url, params).context["events"]}

    def test_defaults_last_30_days_all_types(self):
        self.assertEqual(self.shown(), {"r0", "r1", "r2", "r3", "gig"})

    def test_submitted_form_without_dates_is_unbounded(self):
        self.assertIn("old", self.shown(f=1))

    def test_type_and_limit(self):
        self.assertEqual(self.shown(f=1, event_type=self.concert.pk), {"gig"})
        self.assertEqual(len(self.shown(f=1, event_limit=2)), 2)
        self.assertGreater(len(self.shown(f=1, event_limit="abc")), 2)  # bad limit is ignored, not a 500

    def test_single_date_and_post_keeps_filters(self):
        self.assertEqual(self.shown(f=1, end_date=timezone.localdate().isoformat(), start_date="2999-01-01"), set())
        self.assertEqual(self.client.post(self.url + "?f=1&event_type=%d" % self.concert.pk, {}).status_code, 302)


class ParseDateQueryTests(SimpleTestCase):
    def test_ranges_are_whole_periods(self):
        self.assertEqual(parse_date_query("5.3.2025"), (date(2025, 3, 5), date(2025, 3, 6)))
        self.assertEqual(parse_date_query("2025-03-05"), (date(2025, 3, 5), date(2025, 3, 6)))
        self.assertEqual(parse_date_query("2.2025"), (date(2025, 2, 1), date(2025, 3, 1)))
        self.assertEqual(parse_date_query("2025-12"), (date(2025, 12, 1), date(2026, 1, 1)))
        self.assertEqual(parse_date_query(" 2025 "), (date(2025, 1, 1), date(2026, 1, 1)))
        self.assertEqual(parse_date_query("29.2.2024"), (date(2024, 2, 29), date(2024, 3, 1)))
        self.assertEqual(parse_date_query("31.12.2025"), (date(2025, 12, 31), date(2026, 1, 1)))

    def test_invalid_dates_never_slip(self):
        for q in ("31.2.2025", "29.2.2023", "31.4.2025", "13.2025", "0.2025", "0.3.2025", "5.0.2025",
                  "5.3.25", "99", "abc", "", "1.2.3.2025", "2025.3.5.1"):
            self.assertIsNone(parse_date_query(q), q)


class ListSearchTests(TestCase):
    fixtures = ["syncope/fixture_role.json", "syncope/fixture_eventtype.json",
                "syncope/fixture_invitationstatus.json", "syncope/fixture_invitationtype.json"]

    def setUp(self):
        self.org = CustomUser.objects.create_user(username="org", email="org@example.com", password="pw12345")
        self.client.login(username="org", password="pw12345")
        self.kw = {"username": "org"}

    def search(self, name, q):
        return self.client.get(reverse(f"syncope:{name}_list_search", kwargs=self.kw), {"q": q})

    def local(self, *args):
        return timezone.make_aware(datetime(*args))

    def test_anonymous_redirected(self):
        self.client.logout()
        for name in ("event", "project", "poll", "invitation"):
            self.assertEqual(self.search(name, "x").status_code, 302, name)

    def test_event_text_and_dates(self):
        rehearsal = EventType.objects.get(pk=EventType.REHEARSAL)
        night = Event.objects.create(user=self.org, name="Night", event_type=rehearsal,
                                     started_at=self.local(2025, 3, 5, 23, 30), ended_at=self.local(2025, 3, 5, 23, 45))
        trip = Event.objects.create(user=self.org, name="Trip", event_type=rehearsal,
                                    started_at=self.local(2025, 3, 10, 9), ended_at=self.local(2025, 3, 12, 18))
        shown = lambda q: {e.name for e in self.search("event", q).context["events"]}
        self.assertEqual(shown("night"), {"Night"})
        self.assertEqual(shown("5.3.2025"), {"Night"})
        self.assertEqual(shown("6.3.2025"), set())
        self.assertEqual(shown("11.3.2025"), {"Trip"})
        self.assertEqual(shown("3.2025"), {"Night", "Trip"})
        self.assertEqual(shown("4.2025"), set())
        self.assertEqual(shown("2025"), {"Night", "Trip"})
        self.assertEqual(shown(""), {"Night", "Trip"})
        self.assertContains(self.client.get(reverse("syncope:event_list", kwargs=self.kw), {"q": "night"}), 'value="night"')

    def test_project_year_overlap_event_dates_and_counts(self):
        rehearsal = EventType.objects.get(pk=EventType.REHEARSAL)
        long = Project.objects.create(user=self.org, title="Long", start_date=date(2023, 5, 1), end_date=date(2025, 6, 1))
        gig = Project.objects.create(user=self.org, title="Gig", start_date=date(2020, 1, 1), end_date=date(2020, 1, 2))
        for day in (1, 2):
            Event.objects.create(user=self.org, name=f"e{day}", event_type=rehearsal, project=gig,
                                 started_at=self.local(2026, 2, day, 19), ended_at=self.local(2026, 2, day, 21))
        shown = lambda q: {p.title: p.num_rehearsals for p in self.search("project", q).context["projects"]}
        self.assertEqual(shown("2024"), {"Long": 0})
        self.assertEqual(shown("2026"), {"Gig": 2})
        self.assertEqual(shown("2.2026"), {"Gig": 2})
        self.assertEqual(shown("e1"), {"Gig": 2})  # filtering through events must not shrink the counts
        self.assertEqual(shown("2019"), {})

    def test_poll_persons_and_created_date(self):
        empty = Poll.objects.create(user=self.org, title="Empty")
        full = Poll.objects.create(user=self.org, title="Full")
        for i in range(3):
            PollPerson.objects.create(poll=full, person=Person.objects.create(first_name="P", last_name=str(i)))
        shown = lambda q: {p.title for p in self.search("poll", q).context["polls"]}
        self.assertEqual(shown("3"), {"Full"})
        self.assertEqual(shown("0"), {"Empty"})
        self.assertEqual(shown("full"), {"Full"})
        today = timezone.localdate()
        self.assertEqual(shown(f"{today.day}.{today.month}.{today.year}"), {"Empty", "Full"})
        self.assertEqual(shown(str(today.year + 1)), set())

    def test_invitation_search_narrows_both_tables(self):
        other = CustomUser.objects.create_user(username="zed", email="zed@example.com", password="pw12345")
        Person.objects.create(user=other, email=other.email, first_name="Zed", last_name="Zee")
        kwargs = dict(sender=self.org, recipient=other, invitation_type_id=InvitationType.INVITE,
                      expires_at=self.local(2030, 6, 15, 12))
        Invitation.objects.create(status_id=InvitationStatus.PENDING, **kwargs)
        Invitation.objects.create(status_id=InvitationStatus.APPROVED, **kwargs)
        ctx = lambda q: self.search("invitation", q).context
        self.assertEqual((len(ctx("zed")["pending_list"]), len(ctx("zed")["history_invitations"])), (1, 1))
        self.assertEqual((len(ctx("nobody")["pending_list"]), len(ctx("nobody")["history_invitations"])), (0, 0))
        self.assertEqual(len(ctx("15.6.2030")["pending_list"]), 1)  # expires_at
        self.assertEqual(len(ctx("2031")["pending_list"]), 0)
        self.client.login(username="zed", password="pw12345")  # recipient, but not the page owner nor an admin
        self.assertEqual(self.search("invitation", "").status_code, 403)


class AttendanceSearchTests(TestCase):
    fixtures = ["syncope/fixture_role.json", "syncope/fixture_attendancetype.json", "syncope/fixture_voice.json"]

    def setUp(self):
        self.org = CustomUser.objects.create_user(username="org", email="org@example.com", password="pw12345")
        self.client.login(username="org", password="pw12345")
        self.url = reverse("syncope:attendance", kwargs={"username": "org"})
        rehearsal = EventType.objects.create(name="Rehearsal")
        now = timezone.now()
        self.event = Event.objects.create(user=self.org, name="r", event_type=rehearsal,
                                          started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=2))
        self.ana, self.bob = (Person.objects.create(first_name=f, last_name=l) for f, l in (("Ana", "Novak"), ("Bob", "Kralj")))
        for person in (self.ana, self.bob):
            MembershipPeriod.objects.create(user=self.org, person=person, role_id=Role.MEMBER, started_at=date(2000, 1, 1))
            Attendance.objects.create(event=self.event, person=person, attendance_type_id=AttendanceType.PRESENT)
        Singer.objects.create(person=self.bob, voice=Voice.objects.first())

    def rows(self, **params):
        return {r["member"].last_name for r in self.client.get(self.url, params).context["dashboard_data"]}

    def test_text_search_filters_rows_by_name_and_voice(self):
        self.assertEqual(self.rows(q="ana nov"), {"Novak"})
        self.assertEqual(self.rows(q=Voice.objects.first().name), {"Kralj"})
        self.assertEqual(self.rows(q="nobody"), set())
        self.assertEqual(self.rows(), {"Novak", "Kralj"})

    def test_date_search_filters_event_columns(self):
        today = timezone.localtime(self.event.started_at).date()
        shown = lambda q: len(self.client.get(self.url, {"f": 1, "q": q}).context["events"])
        self.assertEqual(shown(f"{today.day}.{today.month}.{today.year}"), 1)
        self.assertEqual(shown(str(today.year - 1)), 0)

    def test_saving_with_hidden_rows_keeps_their_attendance(self):
        cell = f"attendance_{self.event.pk}_{self.ana.pk}"
        self.client.post(self.url + "?q=ana", {cell: str(AttendanceType.ILLNESS)})
        att = lambda p: Attendance.objects.get(event=self.event, person=p).attendance_type_id
        self.assertEqual(att(self.ana), AttendanceType.ILLNESS)
        self.assertEqual(att(self.bob), AttendanceType.PRESENT)  # hidden by the search, not reset to TBD


class ParseFiltersTests(SimpleTestCase):
    def test_garbage_is_dropped(self):
        spec = {"start": "date", "type": "multi", "lang": "codes", "has": ("yes", "no")}
        get = QueryDict("start=2025-02-30&type=1&type=x&type=2&lang=en&lang=&has=maybe")
        self.assertEqual(parse_filters(get, spec), {"type": [1, 2], "lang": ["en"]})
        self.assertEqual(parse_filters(QueryDict("start=2025-02-28&has=no"), spec), {"start": date(2025, 2, 28), "has": "no"})
        self.assertEqual(parse_filters(QueryDict(""), spec), {})

    def test_period_is_half_open_and_optional(self):
        self.assertIsNone(filter_period({}))
        self.assertEqual(filter_period({"end": date(2025, 2, 28)})[1], date(2025, 3, 1))
        self.assertEqual(filter_period({"start": date(2025, 2, 1)})[0], date(2025, 2, 1))


class ListFilterTests(TestCase):
    fixtures = ["syncope/fixture_role.json", "syncope/fixture_eventtype.json", "syncope/fixture_attendancetype.json",
                "syncope/fixture_invitationstatus.json", "syncope/fixture_invitationtype.json",
                "syncope/fixture_languagecode.json", "syncope/fixture_voice.json"]

    def setUp(self):
        self.org = CustomUser.objects.create_user(username="org", email="org@example.com", password="pw12345")
        self.client.login(username="org", password="pw12345")
        self.kw = {"username": "org"}

    def get(self, name, **params):
        return self.client.get(reverse(f"syncope:{name}", kwargs=self.kw), {"f": 1, **params})

    def local(self, *args):
        return timezone.make_aware(datetime(*args))

    def event(self, name, start, hours=1, type_id=EventType.REHEARSAL, **extra):
        return Event.objects.create(user=self.org, name=name, event_type_id=type_id, started_at=start,
                                    ended_at=start + timedelta(hours=hours), **extra)

    def test_panels_start_closed_and_unfiltered(self):
        for name in ("event_list", "project_list", "poll_list", "invitation_list", "song_list"):
            response = self.client.get(reverse(f"syncope:{name}", kwargs=self.kw))
            self.assertEqual(response.context["filters"], {}, name)
            self.assertContains(response, '<details class="filter-panel">', msg_prefix=name)

    def test_poll_created_range(self):
        Poll.objects.create(user=self.org, title="Empty")
        Poll.objects.create(user=self.org, title="Full")
        titles = lambda **p: {x.title for x in self.get("poll_list_search", **p).context["polls"]}
        today = timezone.localdate().isoformat()
        self.assertEqual(titles(start=today, end=today), {"Empty", "Full"})
        self.assertEqual(titles(start="2999-01-01"), set())
        self.assertEqual(titles(start="2999-01-01", q="empty"), set())  # filter and search AND together

    # Read access by role: members see the org, supporters non-rehearsal events + projects, externals the project list.
    def viewer(self, role_id):
        user = CustomUser.objects.create_user(username=f"v{role_id}", email=f"v{role_id}@example.com", password="pw12345")
        personal = Person.objects.create(first_name="V", last_name=str(role_id), user=user)
        in_org = Person.objects.create(first_name="V", last_name=str(role_id), owner=personal)
        Membership.objects.create(user=self.org, person=in_org)
        PersonRole.objects.create(person=in_org, role_id=role_id)
        self.client.login(username=user.username, password="pw12345")

    def status(self, name, **kw):
        return self.client.get(reverse(f"syncope:{name}", kwargs={**self.kw, **kw})).status_code

    def test_roles_get_only_their_pages(self):
        project = Project.objects.create(user=self.org, title="P")
        rehearsal = self.event("Rehearsal", self.local(2025, 3, 1, 19))
        concert = self.event("Concert", self.local(2025, 3, 2, 19), type_id=EventType.CONCERT)
        self.viewer(Role.EXTERNAL)
        self.assertEqual(self.status("project_list"), 200)
        for name, kw in (("project_detail", {"pk": project.pk}), ("song_list", {}), ("attendance", {}), ("org_member_list", {}),
                         ("event_list", {}), ("event_detail", {"pk": concert.pk})):
            self.assertEqual(self.status(name, **kw), 403, name)
        self.viewer(Role.SUPPORTER)
        self.assertEqual(self.status("event_detail", pk=concert.pk), 200)
        self.assertEqual(self.status("event_detail", pk=rehearsal.pk), 404)
        self.assertEqual({e.name for e in self.get("event_list").context["object_list"]}, {"Concert"})
        for name, kw in (("project_detail", {"pk": project.pk}), ("attendance", {}), ("org_member_list", {})):
            self.assertEqual(self.status(name, **kw), 403, name)
        self.viewer(Role.MEMBER)
        Organization.objects.create(user=self.org, name="Org", email="org@example.com")  # songs of an org, not a person
        song = Song.objects.create(user=self.org, title="Tune", internal_id=1)
        self.assertEqual(self.status("song_list"), 200)
        self.assertEqual(self.status("song_detail", pk=song.pk), 200)
        self.assertEqual(self.status("song_new"), 403)
        self.assertEqual(self.status("song_meta_edit", pk=song.pk), 403)
        self.assertEqual(self.status("attendance"), 200)
        self.assertEqual(self.status("event_detail", pk=rehearsal.pk), 200)

    def test_invitation_type_status_direction_range(self):
        other = CustomUser.objects.create_user(username="zed", email="zed@example.com", password="pw12345")
        Invitation.objects.create(sender=self.org, recipient=other, invitation_type_id=InvitationType.INVITE,
                                  status_id=InvitationStatus.PENDING)
        Invitation.objects.create(sender=other, recipient=self.org, invitation_type_id=InvitationType.REQUEST,
                                  status_id=InvitationStatus.APPROVED)
        n = lambda **p: tuple(len(self.get("invitation_list_search", **p).context[k]) for k in ("pending_list", "history_invitations"))
        self.assertEqual(n(), (1, 1))
        self.assertEqual(n(type=InvitationType.REQUEST), (0, 1))
        self.assertEqual(n(status=InvitationStatus.PENDING), (1, 0))
        self.assertEqual(n(direction="sent"), (1, 0))
        self.assertEqual(n(direction="received"), (0, 1))
        self.assertEqual(n(start="2999-01-01"), (0, 0))

    def test_project_status_and_date_overlap(self):
        today = timezone.localdate()
        day = lambda n: today + timedelta(days=n)
        mk = lambda title, a, b: Project.objects.create(user=self.org, title=title, start_date=a, end_date=b)
        mk("Up", day(10), day(20)); mk("On", day(-5), day(5)); mk("Open", day(-5), None); mk("Past", day(-20), day(-10)); mk("Undated", None, None)
        titles = lambda **p: {x.title for x in self.get("project_list_search", **p).context["projects"]}
        # Missing dates are open-ended: the undated project matches every status and date range.
        self.assertEqual(titles(status="upcoming"), {"Up", "Undated"})
        self.assertEqual(titles(status="ongoing"), {"On", "Open", "Undated"})
        self.assertEqual(titles(status="past"), {"Past", "Undated"})
        self.assertEqual(titles(start=day(-15).isoformat(), end=day(-12).isoformat()), {"Past", "Undated"})
        self.assertEqual(titles(), {"Up", "On", "Open", "Past", "Undated"})

    def test_event_filters_guests_resources_and_attendee_search(self):
        project = Project.objects.create(user=self.org, title="Proj")
        member = Person.objects.create(first_name="Mia", last_name="Member")
        guest = Person.objects.create(first_name="Gus", last_name="Guest")
        MembershipPeriod.objects.create(user=self.org, person=member, role_id=Role.MEMBER, started_at=date(2000, 1, 1))
        song = Song.objects.create(user=self.org, title="Tune", internal_id=1)
        plain = self.event("Plain", self.local(2025, 3, 1, 19))
        rich = self.event("Rich", self.local(2025, 3, 10, 19), type_id=EventType.CONCERT, project=project)
        Attendance.objects.create(event=plain, person=member, attendance_type_id=AttendanceType.PRESENT)
        Attendance.objects.create(event=rich, person=guest, attendance_type_id=AttendanceType.PRESENT)
        Attendance.objects.create(event=plain, person=guest, attendance_type_id=AttendanceType.ILLNESS)
        event_song = EventSong.objects.create(event=rich, song=song, order=1)
        res = lambda n: Resource.objects.create(owner=self.org, url=f"https://example.com/{n}")
        EventResource.objects.create(event=rich, resource=res(1), order=1)
        EventSongResource.objects.create(event_song=event_song, resource=res(2), order=1)
        names = lambda **p: [e.name for e in self.get("event_list_search", **p).context["events"]]
        self.assertEqual(names(type=EventType.CONCERT), ["Rich"])
        self.assertEqual(names(project=project.pk), ["Rich"])
        self.assertEqual(names(has_songs="yes"), ["Rich"])
        self.assertEqual(names(has_songs="no"), ["Plain"])
        self.assertEqual(names(has_resources="yes"), ["Rich"])
        self.assertEqual(names(guests="yes"), ["Rich"])  # Gus was ill at Plain, only present counts
        self.assertEqual(names(guests="no"), ["Plain"])
        self.assertEqual(names(start="2025-03-05"), ["Rich"])
        self.assertEqual(names(q="gus"), ["Rich"])  # present attendee names are searchable
        self.assertEqual(names(q="mia"), ["Plain"])
        rich_row = self.get("event_list_search", sort="resources", reverse="true").context["events"][0]
        self.assertEqual((rich_row.name, rich_row.event_res_n, rich_row.song_res_n), ("Rich", 1, 1))
        self.assertEqual(names(sort="song_resources")[-1], "Rich")

    def test_song_filters(self):
        mk = lambda title, i, **kw: Song.objects.create(user=self.org, title=title, internal_id=i, **kw)
        composer = Person.objects.create(first_name="Ann", last_name="Comp")
        a, b, c = mk("A", 1, languagecode_id="aa", composer=composer), mk("B", 2), mk("C", 3)
        LyricsTranslation.objects.create(song=b, languagecode_id="ab", translation="x")
        gig = self.event("Gig", self.local(2025, 3, 5, 19), type_id=EventType.CONCERT)
        es = EventSong.objects.create(event=gig, song=c, order=1)
        EventSongResource.objects.create(event_song=es, resource=Resource.objects.create(owner=self.org, url="https://example.com/s"), order=1)
        titles = lambda **p: {s.title for s in self.get("song_list_search", **p).context["songs"]}
        self.assertEqual(titles(language="aa"), {"A"})
        self.assertEqual(titles(language="ab"), {"B"})  # translation counts
        self.assertEqual(titles(language=["aa", "ab"]), {"A", "B"})
        self.assertEqual(titles(composer=composer.pk), {"A"})
        self.assertEqual(titles(start="2025-03-05", end="2025-03-05"), {"C"})
        self.assertEqual(titles(start="2025-03-06"), set())
        self.assertEqual(titles(performed="yes"), {"C"})
        self.assertEqual(titles(performed="no"), {"A", "B"})
        self.assertEqual(titles(has_resources="yes"), {"C"})
        self.assertEqual(titles(language="aa", performed="yes"), set())  # filters AND together

    def test_dashboard_voice_filter_narrows_rows_and_keeps_hidden_attendance(self):
        gig = self.event("r", timezone.now() - timedelta(hours=3))
        ana, bob = (Person.objects.create(first_name=f, last_name=l) for f, l in (("Ana", "Novak"), ("Bob", "Kralj")))
        for person in (ana, bob):
            MembershipPeriod.objects.create(user=self.org, person=person, role_id=Role.MEMBER, started_at=date(2000, 1, 1))
            Attendance.objects.create(event=gig, person=person, attendance_type_id=AttendanceType.PRESENT)
        voice = Voice.objects.first()
        Singer.objects.create(person=bob, voice=voice)
        url = reverse("syncope:attendance", kwargs=self.kw)
        rows = lambda **p: {r["member"].last_name for r in self.client.get(url, {"f": 1, **p}).context["dashboard_data"]}
        self.assertEqual(rows(voice=voice.pk), {"Kralj"})
        self.assertEqual(rows(), {"Novak", "Kralj"})
        self.client.post(f"{url}?f=1&voice={voice.pk}", {f"attendance_{gig.pk}_{bob.pk}": str(AttendanceType.ILLNESS)})
        att = lambda p: Attendance.objects.get(event=gig, person=p).attendance_type_id
        self.assertEqual((att(bob), att(ana)), (AttendanceType.ILLNESS, AttendanceType.PRESENT))

