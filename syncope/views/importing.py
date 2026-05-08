from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.contrib import messages
import os
import tempfile
from django.views.generic import  View
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from syncope.models import CustomUser, Skill
from syncope.permissions import AccessControl
from syncope.utils import import_songs, import_persons, import_events, import_attendance, import_event_songs, combine_event_projects


@method_decorator(login_required, name="dispatch")
class ImportHubView(View):
    template_name = 'syncope/import_hub.html'

    def dispatch(self, request, *args, **kwargs):
        """Handle permission checking before processing the request."""
        username = self.kwargs.get("username")
        self.org_user = get_object_or_404(CustomUser, username=username)

        if request.user != self.org_user:
            has_permission = AccessControl.can_edit_event(
                request.user, self.org_user
            ).exists()

            if not has_permission:
                return HttpResponseForbidden("You don't have permission to view this page.")

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, username):
        context = {
            'org_user': self.org_user,
            'url_username': username,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ImportDashboardView(View):
    template_name = 'syncope/import_dashboard.html'

    VALID_METHODS = ["songs", "members", "events", "attendance", "event_songs"]


    def dispatch(self, request, *args, **kwargs):
        """Handle permission checking before processing the request."""
        url_username = self.kwargs.get("username")
        self.org_user = get_object_or_404(CustomUser, username=url_username)

        if request.user != self.org_user:
            has_permission = AccessControl.can_edit_event(
                request.user, self.org_user
            ).exists()

            if not has_permission:
                return HttpResponseForbidden("You don't have permission to view this dashboard.")

        # Validate the import method from URL
        self.import_method = self.kwargs.get('method')
        if self.import_method not in self.VALID_METHODS:
            return HttpResponseForbidden(f"Invalid import method: {self.import_method}")

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, username, method):
        """Render the import dashboard with the appropriate method."""
        context = {
            'import_method': self.import_method,
            'org_user': self.org_user,
            'url_username': username,
        }
        if self.import_method == 'members':
            context['skills'] = Skill.objects.all()
        return render(request, self.template_name, context)

    def post(self, request, username, method):
        """Handle file upload and import."""
        if 'file' not in request.FILES:
            messages.error(request, "No file uploaded")
            return redirect('syncope:import_dashboard', username=username, method=method)

        uploaded_file = request.FILES['file']
        delimiter = request.POST.get('delimiter', ';')
        if delimiter == '\\t':  # Convert literal '\t' string to actual tab character
            delimiter = '\t'
        person_mode = request.POST.get('person_mode')

        try:
            # Save uploaded file temporarily
            # Create a temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8') as tmp_file:
                # Write the uploaded content to temp file
                file_content = uploaded_file.read().decode('utf-8')
                tmp_file.write(file_content)
                tmp_file_path = tmp_file.name

            try:
                # Call the appropriate import function based on method
                if self.import_method == 'songs':
                    result = import_songs(self.org_user, request, tmp_file_path, delimiter)
                elif self.import_method == 'members':
                    result = import_persons(self.org_user, person_mode, request, tmp_file_path, delimiter)
                elif self.import_method == 'events':
                    result = import_events(self.org_user, request, tmp_file_path, delimiter)
                elif self.import_method == 'attendance':
                    result = import_attendance(self.org_user, request, tmp_file_path, delimiter)
                elif self.import_method == 'event_songs':
                    result = import_event_songs(self.org_user, request, tmp_file_path, delimiter)
                else:
                    messages.error(request, f"Invalid import method: {self.import_method}")
                    return redirect('syncope:import_dashboard', username=username, method=method)

                # Check result if your import functions return a dict
                if isinstance(result, dict) and result.get('success'):
                    messages.success(
                        request,
                        f"Successfully imported {result.get('count', 0)} {self.import_method}"
                    )
                elif result:  # If function returns True or similar
                    messages.success(request, f"Successfully imported {self.import_method}")
                else:
                    messages.warning(request, "Import completed with some issues")

            finally:
                # Clean up: delete the temporary file
                if os.path.exists(tmp_file_path):
                    os.unlink(tmp_file_path)

        except Exception as e:
            messages.error(request, f"Error during import: {str(e)}")

        return redirect('syncope:import_dashboard', username=username, method=method)



@method_decorator(login_required, name="dispatch")
class CombineProjectsView(View):

    def dispatch(self, request, *args, **kwargs):
        """Handle permission checking before processing the request."""
        username = self.kwargs.get("username")
        self.org_user = get_object_or_404(CustomUser, username=username)

        if request.user != self.org_user:
            has_permission = AccessControl.can_edit_event(
                request.user, self.org_user
            ).exists()

            if not has_permission:
                return HttpResponseForbidden("You don't have permission to perform this action.")

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, username):
        combine_event_projects(self.org_user, request)
        return redirect('syncope:import_hub', username=username)

    def get(self, request, username):
        return redirect('syncope:import_hub', username=username)



