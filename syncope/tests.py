from django.test import TestCase
from django.urls import reverse

from syncope.models import CustomUser, Person, Project


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
        url = reverse("syncope:project_new_song", kwargs={"username": "org", "pk": self.project.pk})
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 403)
