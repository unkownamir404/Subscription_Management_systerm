from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from apps.accounts.models import Customer
from apps.billing.services.pricing import line_unit_price
from apps.catalog.models import Plan, Product, ProductVariant, Tax
from apps.subscriptions.models import (
    QuotationTemplate,
    TemplateLine,
    Subscription,
    SubscriptionLine,
)


class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = [
            "customer",
            "plan",
            "start_date",
            "expiry_date",
            "payment_terms_days",
            "quote_valid_until",
        ]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "plan": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expiry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "payment_terms_days": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "quote_valid_until": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        expiry = cleaned_data.get("expiry_date")
        if start and expiry and expiry < start:
            self.add_error("expiry_date", "Expiry date cannot be earlier than start date.")
        return cleaned_data


class SubscriptionLineForm(forms.ModelForm):
    class Meta:
        model = SubscriptionLine
        fields = ["product", "variant", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "variant": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        }

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is not None and qty < 1:
            raise ValidationError("Quantity must be at least 1.")
        return qty


class BaseSubscriptionLineFormSet(forms.BaseInlineFormSet):
    def save_new(self, form, commit=True):
        instance = super().save_new(form, commit=False)
        subscription = self.instance

        # Snapshot unit_price and tax_rate only on creation
        if not instance.unit_price:
            plan = subscription.plan if subscription else None
            instance.unit_price = line_unit_price(instance.product, instance.variant, plan)

        if not instance.tax_rate:
            if instance.product and instance.product.tax:
                instance.tax_rate = instance.product.tax.rate
            else:
                default_tax = Tax.objects.filter(is_default=True).first()
                instance.tax_rate = default_tax.rate if default_tax else Decimal("0.00")

        if commit:
            instance.save()
        return instance


SubscriptionLineFormSet = inlineformset_factory(
    Subscription,
    SubscriptionLine,
    form=SubscriptionLineForm,
    formset=BaseSubscriptionLineFormSet,
    extra=1,
    can_delete=True,
)


class QuotationTemplateForm(forms.ModelForm):
    class Meta:
        model = QuotationTemplate
        fields = ["name", "plan", "validity_days", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Standard SaaS Offer"}),
            "plan": forms.Select(attrs={"class": "form-select"}),
            "validity_days": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class TemplateLineForm(forms.ModelForm):
    class Meta:
        model = TemplateLine
        fields = ["product", "variant", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select"}),
            "variant": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        }


TemplateLineFormSet = inlineformset_factory(
    QuotationTemplate,
    TemplateLine,
    form=TemplateLineForm,
    extra=1,
    can_delete=True,
)


class QuotationFromTemplateForm(forms.Form):
    template = forms.ModelChoiceField(
        queryset=QuotationTemplate.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Select Quotation Template",
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Customer",
    )
    start_date = forms.DateField(
        initial=date.today,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        label="Subscription Start Date",
    )
