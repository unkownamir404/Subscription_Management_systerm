from django.contrib.auth import login
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from apps.accounts.forms import (
    SignupForm,
    EmailAuthenticationForm,
    StaffCreateForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)
from apps.accounts.permissions import RoleRequiredMixin


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("/portal/")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="apps.accounts.backends.CaseInsensitiveModelBackend")
            return redirect("/portal/")
    else:
        form = SignupForm()

    return render(request, "registration/signup.html", {"form": form})


class CustomLoginView(LoginView):
    form_class = EmailAuthenticationForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        user = self.request.user
        if hasattr(user, "role") and user.role in ("admin", "staff"):
            return "/reports/"
        return "/portal/"


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("login")


class StaffCreateView(RoleRequiredMixin, FormView):
    """
    Admin-only view to create a new staff user.
    Staff and customers receive 403; unauthenticated users are redirected to login.
    """
    allowed_roles = ["admin"]
    form_class = StaffCreateForm
    template_name = "registration/staff_new.html"
    success_url = reverse_lazy("staff_new")

    def form_valid(self, form):
        form.save()
        from django.contrib import messages
        messages.success(self.request, "Staff user created successfully.")
        return super().form_valid(form)


class CustomPasswordResetView(PasswordResetView):
    form_class = StyledPasswordResetForm
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = StyledSetPasswordForm
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"
