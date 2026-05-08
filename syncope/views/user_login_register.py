from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import CreateView
from syncope.forms import CustomUserCreationForm
from syncope.models import Person

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
    next_page = reverse_lazy("syncope:home")


class UserLoginView(LoginView):
    template_name = "registration/login.html"
