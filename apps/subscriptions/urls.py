from django.urls import path
from apps.subscriptions import views

app_name = "subscriptions"

urlpatterns = [
    # Subscriptions
    path("", views.SubscriptionListView.as_view(), name="subscription_list"),
    path("new/", views.SubscriptionCreateView.as_view(), name="subscription_create"),
    path("<int:pk>/", views.SubscriptionDetailView.as_view(), name="subscription_detail"),
    path("<int:pk>/<str:action>/", views.SubscriptionTransitionView.as_view(), name="subscription_action"),

    # Quotation Templates
    path("templates/", views.QuotationTemplateListView.as_view(), name="template_list"),
    path("templates/new/", views.QuotationTemplateCreateView.as_view(), name="template_create"),
    path("templates/<int:pk>/", views.QuotationTemplateDetailView.as_view(), name="template_detail"),
    path("templates/<int:pk>/delete/", views.QuotationTemplateDeleteView.as_view(), name="template_delete"),
]
