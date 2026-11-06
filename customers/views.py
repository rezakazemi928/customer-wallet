import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from .forms import CustomerRegistrationForm
from .models import Customer


@csrf_exempt
@sensitive_post_parameters('password')
@require_POST
def register(request):
    # Public JSON registration does not authenticate sessions or log users in.
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'Content-Type must be application/json.'}, status=415)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Body must be a JSON object.'}, status=400)

    allowed_fields = set(CustomerRegistrationForm.Meta.fields)
    errors = {}
    for field, value in data.items():
        if field not in allowed_fields:
            errors[field] = ['Unknown field.']
        elif not isinstance(value, str):
            errors[field] = ['Must be a string.']
    if errors:
        return JsonResponse({'errors': errors}, status=400)

    form = CustomerRegistrationForm(data)
    if not form.is_valid():
        return JsonResponse({'errors': dict(form.errors)}, status=400)
    
    try:
        with transaction.atomic():
            customer = Customer.objects.create_user(**form.cleaned_data)
    except IntegrityError:
        return JsonResponse(
            {'error': 'A customer with this mobile already exists.'},
            status=409,
        )

    return JsonResponse({
        'id': str(customer.id),
        'mobile': customer.mobile,
        'national_code': customer.national_code,
        'birthdate': customer.birthdate.isoformat() if customer.birthdate else None,
        'email': customer.email,
        'first_name': customer.first_name,
        'last_name': customer.last_name,
        'username': customer.username,
        'created_at': customer.created_at.isoformat(),
        'updated_at': customer.updated_at.isoformat(),
    }, status=201)
