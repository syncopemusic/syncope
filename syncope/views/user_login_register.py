from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import CreateView
from syncope.forms import CustomUserCreationForm, LoginForm
from syncope.models import Person

@method_decorator(login_not_required, name='dispatch')
class SignUp(CreateView):
    form_class = CustomUserCreationForm
    success_url = reverse_lazy("login")
    template_name = "syncope/signup.html"

    def form_valid(self, form):
        response = super().form_valid(form) #save the new user first

        Person.objects.create(
        user=self.object,
        email=self.object.email,
        first_name="",
        last_name="",
        )

        return response


class UserLogoutView(LogoutView):
    next_page = reverse_lazy("syncope:login")

    def get(self, request, *args, **kwargs):
        # reached via back button / typed URL: logout is POST-only, so bounce to dashboard
        return redirect("syncope:home")


class UserLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True
