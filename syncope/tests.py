from datetime import date

from django.test import TestCase
from django.urls import reverse

from syncope.models import (
    CustomUser, Event, EventSong, EventSongResource, EventType, Membership, MembershipPeriod,
    Person, PersonSkill, Project, Role, Skill, Song,
)


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
            response, reverse("syncope:song_detail", kwargs={"username": "org", "pk": self.song.pk})
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
