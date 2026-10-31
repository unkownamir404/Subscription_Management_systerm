from django.urls import path
from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    # Products
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/new/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_update"),
    path("products/<int:pk>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),

    # Plans
    path("plans/", views.PlanListView.as_view(), name="plan_list"),
    path("plans/new/", views.PlanCreateView.as_view(), name="plan_create"),
    path("plans/<int:pk>/edit/", views.PlanUpdateView.as_view(), name="plan_update"),
    path("plans/<int:pk>/delete/", views.PlanDeleteView.as_view(), name="plan_delete"),

    # Taxes
    path("taxes/", views.TaxListView.as_view(), name="tax_list"),
    path("taxes/new/", views.TaxCreateView.as_view(), name="tax_create"),
    path("taxes/<int:pk>/edit/", views.TaxUpdateView.as_view(), name="tax_update"),

    # Discounts
    path("discounts/", views.DiscountListView.as_view(), name="discount_list"),
    path("discounts/new/", views.DiscountCreateView.as_view(), name="discount_create"),
    path("discounts/<int:pk>/edit/", views.DiscountUpdateView.as_view(), name="discount_update"),
    path("discounts/<int:pk>/delete/", views.DiscountDeleteView.as_view(), name="discount_delete"),
]
