from django.urls import path
from apps.subscriptions import views

app_name = "subscriptions"

urlpatterns = [
    # Subscriptions
    path("subscriptions/", views.SubscriptionListView.as_view(), name="subscription_list"),
    path("subscriptions/new/", views.SubscriptionCreateView.as_view(), name="subscription_create"),
    path("subscriptions/<int:pk>/", views.SubscriptionDetailView.as_view(), name="subscription_detail"),
    path("subscriptions/<int:pk>/edit/", views.SubscriptionUpdateView.as_view(), name="subscription_update"),

    # State Machine Transitions (POST only)
    path(
        "subscriptions/<int:pk>/quotation/",
        views.SubscriptionTransitionView.as_view(action_name="quotation"),
        name="subscription_quotation",
    ),
    path(
        "subscriptions/<int:pk>/confirm/",
        views.SubscriptionTransitionView.as_view(action_name="confirm"),
        name="subscription_confirm",
    ),
    path(
        "subscriptions/<int:pk>/activate/",
        views.SubscriptionTransitionView.as_view(action_name="activate"),
        name="subscription_activate",
    ),
    path(
        "subscriptions/<int:pk>/pause/",
        views.SubscriptionTransitionView.as_view(action_name="pause"),
        name="subscription_pause",
    ),
    path(
        "subscriptions/<int:pk>/resume/",
        views.SubscriptionTransitionView.as_view(action_name="resume"),
        name="subscription_resume",
    ),
    path(
        "subscriptions/<int:pk>/close/",
        views.SubscriptionTransitionView.as_view(action_name="close"),
        name="subscription_close",
    ),
    path(
        "subscriptions/<int:pk>/renew/",
        views.SubscriptionTransitionView.as_view(action_name="renew"),
        name="subscription_renew",
    ),

    # Quotation Templates
    path("templates/", views.QuotationTemplateListView.as_view(), name="template_list"),
    path("templates/new/", views.QuotationTemplateCreateView.as_view(), name="template_create"),
    path("templates/<int:pk>/edit/", views.QuotationTemplateUpdateView.as_view(), name="template_update"),
    path("templates/create-quotation/", views.QuotationFromTemplateView.as_view(), name="create_quotation_from_template"),
]
