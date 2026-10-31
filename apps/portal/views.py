from django.http import HttpResponse

def portal_dashboard(request):
    return HttpResponse("<h1>Customer Portal</h1><p>Welcome to your portal.</p>")
