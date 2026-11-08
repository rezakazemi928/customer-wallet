"""Types shared by customer authentication and protected views."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypedDict

from django.http import HttpRequest, HttpResponse

if TYPE_CHECKING:
    from .models import Customer


class CustomerRequest(HttpRequest):
    customer: Customer


class TokenPayload(TypedDict):
    userId: str
    iat: int
    exp: int


# Decorators forward URL arguments and can return authentication errors.
View = Callable[..., HttpResponse]
