def role_flags(request):
    """
    Context processor providing boolean role flags to templates:
    role_flags.is_admin, role_flags.is_staff, role_flags.is_staff_or_admin, role_flags.is_customer.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {
            'role_flags': {
                'is_admin': False,
                'is_staff': False,
                'is_staff_or_admin': False,
                'is_customer': False,
            }
        }

    role = getattr(user, 'role', '')
    is_adm = (role == 'admin' or user.is_superuser)
    is_stf = (role == 'staff')

    return {
        'role_flags': {
            'is_admin': is_adm,
            'is_staff': is_stf,
            'is_staff_or_admin': is_adm or is_stf or user.is_staff,
            'is_customer': (role == 'customer'),
        }
    }
