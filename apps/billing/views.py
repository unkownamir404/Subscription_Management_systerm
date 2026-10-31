from datetime import datetime
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST, require_GET

from apps.billing.models import Invoice, InvoiceStatus, PaymentMethod
from apps.billing.services.invoice_actions import (
    confirm_invoice,
    cancel_invoice,
    mark_sent,
    record_payment,
)


def _for_user_queryset(self, user):
    """
    Queryset filtering based on user role:
    - Admin/Staff: all invoices
    - Customer: only invoices belonging to customer
    - Anonymous: none
    """
    if not user or not user.is_authenticated:
        return self.none()
    if user.is_superuser or getattr(user, 'role', None) in ('admin', 'staff'):
        return self.all()
    if getattr(user, 'role', None) == 'customer':
        return self.filter(customer__user=user)
    return self.none()


# Ensure for_user is attached to Invoice.objects and QuerySets
if not hasattr(Invoice.objects, 'for_user'):
    models.QuerySet.for_user = _for_user_queryset
    models.Manager.for_user = _for_user_queryset


def _check_action_permissions(request, pk):
    """
    Enforces authorization rules:
    - Cross-customer access returns 404
    - Wrong role returns 403
    - Returns the target Invoice instance if authorized
    """
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    # 1. Existence check
    try:
        invoice = Invoice.objects.get(pk=pk)
    except Invoice.DoesNotExist:
        raise Http404("Invoice does not exist.")

    # 2. Cross-customer isolation (404 if not visible to user)
    visible = Invoice.objects.for_user(request.user).filter(pk=pk).exists()
    if not visible:
        raise Http404("Invoice not found.")

    # 3. Role enforcement for actions: staff/admin only (403 if customer or other role)
    is_staff_or_admin = (
        request.user.is_superuser or getattr(request.user, 'role', None) in ('admin', 'staff')
    )
    if not is_staff_or_admin:
        raise PermissionDenied("Only staff and admin can perform invoice actions.")

    return invoice


@require_POST
def invoice_confirm(request, pk):
    """POST /invoices/<id>/confirm/"""
    invoice = _check_action_permissions(request, pk)

    try:
        confirmed = confirm_invoice(invoice, user=request.user)
    except ValidationError as e:
        msg = e.message if hasattr(e, 'message') else str(e)
        return HttpResponseBadRequest(msg)

    messages.success(request, f"Invoice {confirmed.number} has been confirmed.")

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': confirmed.status, 'number': confirmed.number})

    redirect_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or f'/invoices/{confirmed.pk}/'
    return HttpResponseRedirect(redirect_url)


@require_POST
def invoice_cancel(request, pk):
    """POST /invoices/<id>/cancel/"""
    invoice = _check_action_permissions(request, pk)

    try:
        cancelled = cancel_invoice(invoice, user=request.user)
    except ValidationError as e:
        msg = e.message if hasattr(e, 'message') else str(e)
        return HttpResponseBadRequest(msg)

    messages.success(request, f"Invoice {cancelled.number or cancelled.pk} has been cancelled.")

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': cancelled.status})

    redirect_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or f'/invoices/{cancelled.pk}/'
    return HttpResponseRedirect(redirect_url)


@require_POST
def invoice_send(request, pk):
    """POST /invoices/<id>/send/"""
    invoice = _check_action_permissions(request, pk)

    sent = mark_sent(invoice)
    messages.success(request, f"Invoice {sent.number or sent.pk} marked as sent.")

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': sent.status, 'sent_at': sent.sent_at.isoformat()})

    redirect_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or f'/invoices/{sent.pk}/'
    return HttpResponseRedirect(redirect_url)


@require_POST
def invoice_record_payment(request, pk):
    """POST /invoices/<id>/payments/"""
    invoice = _check_action_permissions(request, pk)

    method = request.POST.get('method')
    amount_raw = request.POST.get('amount')
    paid_on_raw = request.POST.get('paid_on')
    note = request.POST.get('note', '')

    if not amount_raw:
        return HttpResponseBadRequest("Missing required 'amount' field.")

    if not method:
        return HttpResponseBadRequest("Missing required 'method' field.")

    paid_on = None
    if paid_on_raw:
        try:
            paid_on = datetime.strptime(paid_on_raw, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponseBadRequest("Invalid paid_on date format (YYYY-MM-DD expected).")

    try:
        payment = record_payment(
            invoice=invoice,
            method=method,
            amount=Decimal(str(amount_raw)),
            paid_on=paid_on,
            note=note,
            user=request.user,
        )
    except (ValidationError, TypeError) as e:
        msg = e.message if hasattr(e, 'message') else str(e)
        return HttpResponseBadRequest(msg)

    messages.success(request, f"Payment of {payment.amount} recorded for Invoice {invoice.number or invoice.pk}.")

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'payment_id': payment.id,
            'amount': str(payment.amount),
            'invoice_status': invoice.status,
            'invoice_amount_paid': str(invoice.amount_paid),
        })

    redirect_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or f'/invoices/{invoice.pk}/'
    return HttpResponseRedirect(redirect_url)


@require_GET
def invoice_print(request, pk):
    """GET /invoices/<id>/print/"""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    invoice = get_object_or_404(
        Invoice.objects.for_user(request.user)
        .select_related('customer', 'subscription')
        .prefetch_related('lines', 'payments'),
        pk=pk,
    )

    return render(request, 'billing/invoice_print.html', {'invoice': invoice})
