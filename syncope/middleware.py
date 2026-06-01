from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages


class ProfileCompletionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile_url = reverse(
                'syncope:person_update',
                kwargs={'username': request.user.username}
            )
            exempt_prefixes = [
                profile_url,
                reverse('syncope:login'),
                reverse('syncope:logout'),
            ]
            if not any(request.path.startswith(p) for p in exempt_prefixes):
                from syncope.models import Person
                person = Person.objects.filter(
                    user=request.user, owner=None
                ).first()
                if person and (not person.first_name or not person.last_name):
                    messages.info(
                        request,
                        "Please complete your profile."
                    )
                    return redirect(profile_url)

        return self.get_response(request)
