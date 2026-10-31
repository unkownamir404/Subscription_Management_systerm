from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from apps.catalog.models import Product, ProductVariant, Plan, Tax, Discount


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "product_type", "sales_price", "cost_price", "notes", "tax", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Product name"}),
            "product_type": forms.Select(attrs={"class": "form-select"}),
            "sales_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "0.00"}),
            "cost_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "0.00"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional internal notes"}),
            "tax": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_sales_price(self):
        price = self.cleaned_data.get("sales_price")
        if price is not None and price < Decimal("0.00"):
            raise ValidationError("Sales price cannot be negative.")
        return price

    def clean_cost_price(self):
        price = self.cleaned_data.get("cost_price")
        if price is not None and price < Decimal("0.00"):
            raise ValidationError("Cost price cannot be negative.")
        return price


class ProductVariantForm(forms.ModelForm):
    extra_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "0.00"}),
    )

    class Meta:
        model = ProductVariant
        fields = ["attribute", "value", "extra_price"]
        widgets = {
            "attribute": forms.TextInput(attrs={"class": "form-control", "placeholder": 'e.g. Brand'}),
            "value": forms.TextInput(attrs={"class": "form-control", "placeholder": 'e.g. Odoo'}),
        }

    def clean_extra_price(self):
        extra = self.cleaned_data.get("extra_price")
        if extra is None:
            return Decimal("0.00")
        if extra < Decimal("0.00"):
            raise ValidationError("Extra price cannot be negative.")
        return extra


ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    extra=1,
    can_delete=True,
)


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            "name",
            "price",
            "interval",
            "interval_count",
            "min_qty",
            "valid_from",
            "valid_to",
            "auto_close",
            "allow_early_close",
            "allow_pause",
            "allow_renew",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Plan name"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "0.00"}),
            "interval": forms.Select(attrs={"class": "form-select"}),
            "interval_count": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "min_qty": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "valid_from": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "valid_to": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "auto_close": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_early_close": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_pause": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_renew": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is not None and price < Decimal("0.00"):
            raise ValidationError("Plan price cannot be negative.")
        return price

    def clean_min_qty(self):
        qty = self.cleaned_data.get("min_qty")
        if qty is not None and qty < 1:
            raise ValidationError("Minimum quantity must be at least 1.")
        return qty

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get("valid_from")
        valid_to = cleaned_data.get("valid_to")
        if valid_from and valid_to and valid_to < valid_from:
            self.add_error("valid_to", "Valid to date must be on or after valid from date.")
        return cleaned_data


class TaxForm(forms.ModelForm):
    class Meta:
        model = Tax
        fields = ["name", "rate", "is_default", "priority"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. GST 18%"}),
            "rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "18.00"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "priority": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def clean_rate(self):
        rate = self.cleaned_data.get("rate")
        if rate is not None and (rate < Decimal("0.00") or rate > Decimal("100.00")):
            raise ValidationError("Tax rate must be between 0 and 100 percent.")
        return rate


class DiscountForm(forms.ModelForm):
    class Meta:
        model = Discount
        fields = [
            "name",
            "kind",
            "value",
            "min_amount",
            "min_qty",
            "start_date",
            "end_date",
            "usage_limit",
            "scope",
            "products",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Discount name"}),
            "kind": forms.Select(attrs={"class": "form-select"}),
            "value": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "min_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "min_qty": forms.NumberInput(attrs={"class": "form-control"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "usage_limit": forms.NumberInput(attrs={"class": "form-control", "placeholder": "Unlimited if empty"}),
            "scope": forms.Select(attrs={"class": "form-select"}),
            "products": forms.SelectMultiple(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        kind = cleaned_data.get("kind")
        value = cleaned_data.get("value")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date must be on or after start date.")

        if kind == Discount.Kind.PERCENT and value is not None:
            if value < Decimal("0.00") or value > Decimal("100.00"):
                self.add_error("value", "Percentage discount must be between 0 and 100.")
        elif kind == Discount.Kind.FIXED and value is not None:
            if value < Decimal("0.00"):
                self.add_error("value", "Fixed discount value cannot be negative.")

        return cleaned_data
