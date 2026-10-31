from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Customer

User = get_user_model()


class SignupForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@company.com", "autocomplete": "email"}),
    )
    name = forms.CharField(
        label="Full Name",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane Doe"}),
    )
    company = forms.CharField(
        label="Company Name",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Acme Inc."}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "At least 9 characters with upper, lower, special"}),
        help_text="Must be more than 8 characters and contain at least one uppercase, one lowercase, and one special character.",
    )
    password_confirm = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Repeat password"}),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "Passwords do not match.")

        return cleaned_data

    def save(self):
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password"]
        name = self.cleaned_data["name"].strip()
        company = self.cleaned_data.get("company", "").strip()

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                role=User.Role.CUSTOMER,
            )
            Customer.objects.create(
                user=user,
                name=name,
                company=company,
            )
        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@company.com", "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Enter your password"}),
    )


class StyledPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Email address",
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@company.com"}),
    )


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})


class StaffCreateForm(forms.Form):
    """Admin-only form to create a staff or admin user."""
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "staff@brightloop.test"}),
    )
    full_name = forms.CharField(
        label="Full Name",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane Smith"}),
    )
    role = forms.ChoiceField(
        label="Role",
        choices=[("staff", "Staff"), ("admin", "Admin")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password1(self):
        pw = self.cleaned_data.get("password1", "")
        if pw:
            password_validation.validate_password(pw)
        return pw

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned

    def save(self):
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password1"]
        role = self.cleaned_data["role"]
        is_staff_flag = role in ("staff", "admin")
        is_superuser = role == "admin"
        user = User.objects.create_user(
            email=email,
            password=password,
            role=role,
        )
        user.is_staff = is_staff_flag
        user.is_superuser = is_superuser
        user.save()
        return user
