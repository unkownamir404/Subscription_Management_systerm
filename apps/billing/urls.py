from django.urls import path
from apps.billing import views

urlpatterns = [
    path('invoices/<int:pk>/confirm/', views.invoice_confirm, name='invoice_confirm'),
    path('invoices/<int:pk>/cancel/', views.invoice_cancel, name='invoice_cancel'),
    path('invoices/<int:pk>/send/', views.invoice_send, name='invoice_send'),
    path('invoices/<int:pk>/payments/', views.invoice_record_payment, name='invoice_record_payment'),
    path('invoices/<int:pk>/print/', views.invoice_print, name='invoice_print'),
]
