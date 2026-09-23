from datetime import date

from django.test import TestCase
from django.urls import reverse

from syncope.models import CustomUser, Event, EventType, MembershipPeriod, Person, Project, Role, Song


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
