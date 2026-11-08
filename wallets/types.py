"""Contracts for validated wallet requests and balance service results."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from customers.types import CustomerRequest

ReservationCheck = Callable[[], None]
OperationResult = tuple[dict[str, str | int], int]


class TransactionData(TypedDict):
    type: str
    amount: Decimal


class OperationFingerprint(TypedDict):
    wallet_type_id: int
    type: str
    amount: str


class WalletRequest(CustomerRequest):
    """Attributes populated by validation and idempotency decorators."""

    transaction_data: TransactionData
    wallet_request_id: UUID
    ensure_wallet_reservation: ReservationCheck
