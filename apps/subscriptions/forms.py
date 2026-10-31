from django import forms
from apps.subscriptions.models import Subscription, SubscriptionLine, QuotationTemplate, TemplateLine
from apps.catalog.models import Plan, Product, ProductVariant
from apps.accounts.models import Customer


class SubscriptionForm(forms.ModelForm):
    template = forms.ModelChoiceField(
        queryset=QuotationTemplate.objects.filter(is_active=True),
        required=False,
        empty_label="-- Select Template (Optional) --",
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Pre-populate lines and settings from a quotation template.",
    )

    class Meta:
        model = Subscription
        fields = [
            "customer",
            "plan",
            "start_date",
            "expiry_date",
            "payment_terms_days",
        ]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "plan": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expiry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "payment_terms_days": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }


class SubscriptionLineForm(forms.ModelForm):
    class Meta:
        model = SubscriptionLine
        fields = ["product", "variant", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "variant": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }


class QuotationTemplateForm(forms.ModelForm):
    class Meta:
        model = QuotationTemplate
        fields = ["name", "plan", "validity_days", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "plan": forms.Select(attrs={"class": "form-select"}),
            "validity_days": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class TemplateLineForm(forms.ModelForm):
    class Meta:
        model = TemplateLine
        fields = ["product", "variant", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "variant": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }


TemplateLineFormSet = forms.inlineformset_factory(
    QuotationTemplate,
    TemplateLine,
    form=TemplateLineForm,
    extra=2,
    can_delete=True,
)
