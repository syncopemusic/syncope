from django.urls import path

from .views.attendance import AttendanceDashboardView, AttendanceDeleteView, quick_add_rehearsal, self_attendance_update
from .views.event import EventCreateView, EventDetailView, EventUpdateView, EventListView
from .views.event import event_add_song, event_add_attendance
from .views.home import HomeView, IndexView, SkillListAndCreateView
from .views.importing import ImportHubView, ImportDashboardView, CombineProjectsView
from .views.organization import OrganizationCreateView, OrganizationDashboard
from .views.person import PersonUpdateView, OrgMemberAddView, OrgMemberEditView, OrgMemberListView, OrgMemberDetailView
from .views.project import ProjectDeleteView, ProjectCreateView, ProjectDetailView, ProjectUpdateView, ProjectListView
from .views.project import project_add_guest, project_add_event, project_remove_event, project_remove_song, project_add_song, project_remove_guest
from .views.song import SongListView, SongCreateView, SongDeleteView, SongDetailView, SongUpdateView, SongQuoteView
from .views.user_login_register import SignUp, UserLoginView, UserLogoutView
from .views.poll import PollListView, PollCreateUpdateView, PollDetailView, PollDeleteView, PollPersonView, PollEventView, PollEventUpdateView, PollEventAttendanceView, PollPersonAttendanceView, poll_person_remove, poll_event_remove
from .views.share import create_share_link, visit_share


app_name = 'syncope'

urlpatterns = [

    path("signup/", SignUp.as_view(), name="signup"),

    path("<str:username>/person_form2/", PersonUpdateView.as_view(), name="person_update"),
    path("logout/", UserLogoutView.as_view(), name="logout"),
    path("login/", UserLoginView.as_view(), name="login"),

    path("home/", HomeView.as_view(), name="home"),

    path("", IndexView.as_view(), name="index2"),
    path("organization_form/", OrganizationCreateView.as_view(), name="org_create"),

    path("<str:username>/dashboard/", OrganizationDashboard.as_view(), name="org_dashboard"),
    path("<str:username>/import/", ImportHubView.as_view(), name="import_hub"),
    path("<str:username>/import/combine/", CombineProjectsView.as_view(), name="import_combine"),
    path("<str:username>/<str:method>/import/", ImportDashboardView.as_view(), name="import_dashboard"),
    path("<str:username>/events/", EventListView.as_view(), name="event_list"),
    path("<str:username>/events/add/", EventCreateView.as_view(), name="event_create"),
    path("<str:username>/events/<int:pk>/", EventDetailView.as_view(), name="event_detail"),
    path("<str:username>/events/<int:pk>/edit/", EventUpdateView.as_view(), name="event_update"),
    path("<str:username>/events/<int:event_pk>/attendance/update/", self_attendance_update, name="self_attendance_update"),
    path("<str:username>/events/<int:pk>/attendance/add/", event_add_attendance, name="event_add_attendance"),
    path("<str:username>/events/<int:event_pk>/attendance/<int:pk>/delete/", AttendanceDeleteView.as_view(), name="attendance_delete"),
    path("<str:username>/events/<int:pk>/songs/add/", event_add_song, name="event_add_song"),

    path("<str:username>/members/", OrgMemberListView.as_view(), name="org_member_list"),
    path("<str:username>/members/add/", OrgMemberAddView.as_view(),name="org_member_add"),
    path("<str:username>/members/add-composer/",
         OrgMemberAddView.as_view(),{'preset': 'composer'},name="org_member_add_composer"),
    path("<str:username>/members/add-poet/",
         OrgMemberAddView.as_view(),{'preset': 'poet'},name="org_member_add_poet"),
    path("<str:username>/members/add-translator/",
         OrgMemberAddView.as_view(),{'preset': 'translator'},name="org_member_add_translator"),
    path("<str:username>/members/<int:pk>/", OrgMemberDetailView.as_view(), name="org_member_detail"),
    path("<str:username>/members/<int:pk>/edit/", OrgMemberEditView.as_view(), name="org_member_edit"),

    path("<str:username>/songs/", SongListView.as_view(), name="song_dashboard"),
    path("<str:username>/songs/create/", SongCreateView.as_view(), name="song_form2"),
    path("<str:username>/songs/<int:pk>/", SongDetailView.as_view(), name="song_page"),
    path("<str:username>/songs/<int:pk>/update/", SongUpdateView.as_view(), name="song_update"),
    path("<str:username>/songs/<int:pk>/delete/", SongDeleteView.as_view(), name="song_delete"),
    path("<str:username>/songs/<int:pk>/quotes/", SongQuoteView.as_view(), name="song_quotes"),
    path('<str:username>/attendance/', AttendanceDashboardView.as_view(), name='attendance'),
    path('<str:username>/attendance/quick-add/', quick_add_rehearsal, name='quick_add_rehearsal'),
    path("skill/", SkillListAndCreateView.as_view(), name="skill"),

    path('<str:username>/projects/', ProjectListView.as_view(), name='project_list'),
    path('<str:username>/projects/new/', ProjectCreateView.as_view(), name='project_create'),
    path('<str:username>/projects/<int:pk>/', ProjectDetailView.as_view(), name='project_detail'),
    path('<str:username>/projects/<int:pk>/edit/', ProjectUpdateView.as_view(), name='project_update'),
    path('<str:username>/projects/<int:pk>/delete/', ProjectDeleteView.as_view(), name='project_delete'),
    path('<str:username>/projects/<int:pk>/events/add/', project_add_event, name='project_add_event'),
    path('<str:username>/projects/<int:pk>/events/<int:event_pk>/remove/', project_remove_event, name='project_remove_event'),
    path('<str:username>/projects/<int:pk>/songs/add/', project_add_song, name='project_add_song'),
    path('<str:username>/projects/<int:pk>/songs/<int:song_pk>/remove/', project_remove_song, name='project_remove_song'),
    path('<str:username>/projects/<int:pk>/guests/add/', project_add_guest, name='project_add_guest'),
    path('<str:username>/projects/<int:pk>/guests/<int:guest_pk>/remove/', project_remove_guest, name='project_remove_guest'),

    path("<str:username>/polls/<int:pk>/<int:person_pk>/", PollPersonAttendanceView.as_view(), name="poll_person_attendance"),

    path("<str:username>/polls/", PollListView.as_view(), name="poll_list"),
    path("<str:username>/polls/create/", PollCreateUpdateView.as_view(), name="poll_create"),
    path("<str:username>/polls/<int:pk>/", PollDetailView.as_view(), name="poll_detail"),
    path("<str:username>/polls/<int:pk>/update/", PollCreateUpdateView.as_view(), name="poll_update"),
    path("<str:username>/polls/<int:pk>/delete/", PollDeleteView.as_view(), name="poll_delete"),
    path("<str:username>/polls/<int:pk>/persons/", PollPersonView.as_view(), name="poll_persons"),
    path("<str:username>/polls/<int:pk>/persons/<int:person_pk>/remove/", poll_person_remove, name="poll_person_remove"),
    path("<str:username>/polls/<int:pk>/events/", PollEventView.as_view(), name="poll_events"),
    path("<str:username>/polls/<int:pk>/events/<int:event_pk>/edit/", PollEventUpdateView.as_view(), name="poll_event_update"),
    path("<str:username>/polls/<int:pk>/events/<int:event_pk>/remove/", poll_event_remove, name="poll_event_remove"),
    path("<str:username>/polls/<int:pk>/attendance/", PollEventAttendanceView.as_view(), name="poll_attendance"),

    path("share/create/", create_share_link, name="share-create"),
    path("<str:share_id>/", visit_share, name="share-visit"),

]