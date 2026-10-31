from django.urls import path
from apps.accounts import views
from apps.accounts import customer_views

urlpatterns = [
    path("", views.root_redirect_view, name="root_redirect"),
    path("staff/new/", views.StaffCreateView.as_view(), name="staff_create"),
    path("customers/", customer_views.CustomerListView.as_view(), name="customer_list"),
    path("customers/<int:pk>/", customer_views.CustomerDetailView.as_view(), name="customer_detail"),
    path("customers/<int:pk>/edit/", customer_views.CustomerUpdateView.as_view(), name="customer_update"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path("logout/", views.CustomLogoutView.as_view(), name="logout"),
    path("password-reset/", views.CustomPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.CustomPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", views.CustomPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset/complete/", views.CustomPasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
