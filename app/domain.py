"""Dominio de TechStore: Value Objects, entidades, máquina de estados y Domain Events.

Este módulo no depende de FastAPI ni de los archivos CSV. Todas las reglas de
negocio de los pedidos viven aquí, de modo que la API, las pruebas o cualquier
otro proceso obtienen el mismo comportamiento.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

MAX_UNITS_PER_ORDER = 20
CURRENCY = "MXN"
CENTS = Decimal("0.01")


# ---------------------------------------------------------------------------
# Excepciones de dominio: DomainException -> OrderException -> casos concretos
# ---------------------------------------------------------------------------
class DomainException(Exception):
    """Una operación solicitada viola una regla del negocio."""


class OrderException(DomainException):
    """Error relacionado con un pedido."""


class InvalidOrderData(OrderException):
    """Los datos no cumplen una invariante (monto, cantidad, artículos, cliente...)."""


class InvalidOrderTransition(OrderException):
    """La máquina de estados no permite la operación desde el estado actual."""

    def __init__(self, action: str, current: "OrderStatus"):
        self.action = action
        self.current = current
        super().__init__(f"No se puede {action} un pedido en estado {current.value}")


class OrderItemLimitExceeded(OrderException):
    """Se superaría el máximo de unidades por pedido."""


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Money:
    """Importe inmutable en una moneda. Nunca es negativo y siempre usa Decimal."""

    amount: Decimal
    currency: str = CURRENCY

    def __post_init__(self):
        # bool y float se rechazan a propósito: el dinero no se representa con float.
        if not isinstance(self.amount, Decimal):
            raise InvalidOrderData("El monto debe ser Decimal, no float ni int")
        if not self.amount.is_finite() or self.amount < 0:
            raise InvalidOrderData("Monto inválido: no se permiten importes negativos")
        if not isinstance(self.currency, str) or len(self.currency.strip()) != 3:
            raise InvalidOrderData("Moneda inválida")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("No se pueden sumar monedas distintas")
        return Money(self.amount + other.amount, self.currency)

    def multiply(self, quantity: int) -> "Money":
        return Money(self.amount * quantity, self.currency)

    def percentage(self, percent: Decimal) -> "Money":
        """Devuelve el porcentaje indicado del importe, redondeado a centavos."""
        value = (self.amount * percent / Decimal("100")).quantize(CENTS, rounding=ROUND_HALF_UP)
        return Money(value, self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("No se pueden restar monedas distintas")
        return Money(self.amount - other.amount, self.currency)

    @classmethod
    def zero(cls, currency: str = CURRENCY) -> "Money":
        return cls(Decimal("0.00"), currency)


@dataclass(frozen=True)
class Customer:
    """Cliente del catálogo. es_vip y activo vienen de clientes.csv."""

    id: str
    is_vip: bool = False
    active: bool = True

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise InvalidOrderData("El cliente requiere un identificador")


@dataclass(frozen=True)
class OrderItem:
    """Un renglón del pedido. El subtotal se calcula; nunca se captura a mano."""

    sku: str
    quantity: int
    unit_price: Money

    def __post_init__(self):
        if not isinstance(self.sku, str) or not self.sku.strip():
            raise InvalidOrderData("Artículo inválido: SKU vacío")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise InvalidOrderData("Artículo inválido: la cantidad debe ser un entero mayor que cero")
        if not isinstance(self.unit_price, Money):
            raise InvalidOrderData("Artículo inválido: el precio debe ser Money")

    @property
    def subtotal(self) -> Money:
        return self.unit_price.multiply(self.quantity)


# ---------------------------------------------------------------------------
# Estados y Domain Events
# ---------------------------------------------------------------------------
class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


@dataclass(frozen=True)
class DomainEvent:
    """Hecho del negocio que ya ocurrió. Inmutable y con fecha/hora UTC."""

    name: str
    order_id: str
    customer_id: str
    total: Money
    detail: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Nombres de los eventos (en pasado, como hechos ya ocurridos)
ORDER_CONFIRMED = "OrderConfirmed"
ORDER_SHIPPED = "OrderShipped"
ORDER_CANCELLED = "OrderCancelled"
ORDER_DELIVERED = "OrderDelivered"
ORDER_RETURNED = "OrderReturned"


# ---------------------------------------------------------------------------
# Order: Aggregate Root
# ---------------------------------------------------------------------------
@dataclass
class Order:
    """Pedido. Protege sus invariantes y controla su propia máquina de estados.

    Regla de cada transición: validar primero, cambiar status después y
    registrar el evento al final. Si una validación falla, el pedido queda
    exactamente igual (mismo estado y mismos eventos).
    """

    customer: Customer
    id: str
    has_promotion: bool = False
    status: OrderStatus = OrderStatus.DRAFT
    items: list[OrderItem] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise InvalidOrderData("El pedido requiere un identificador")
        if not isinstance(self.customer, Customer):
            raise InvalidOrderData("El pedido requiere un cliente")

    # ----- consultas -------------------------------------------------------
    @property
    def units(self) -> int:
        """Suma de cantidades (no número de renglones)."""
        return sum(item.quantity for item in self.items)

    @property
    def total(self) -> Money:
        total = Money.zero()
        for item in self.items:
            total = total.add(item.subtotal)
        return total

    # ----- modificación de artículos --------------------------------------
    def add_item(self, item: OrderItem) -> None:
        if self.status != OrderStatus.DRAFT:
            raise InvalidOrderTransition("agregar artículos a", self.status)
        if not isinstance(item, OrderItem):
            raise InvalidOrderData("Solo se pueden agregar objetos OrderItem")
        if item.unit_price.currency != CURRENCY:
            raise InvalidOrderData(f"Solo se aceptan precios en {CURRENCY}")
        if self.units + item.quantity > MAX_UNITS_PER_ORDER:
            raise OrderItemLimitExceeded(
                f"Un pedido no puede tener más de {MAX_UNITS_PER_ORDER} unidades "
                f"(tiene {self.units} y se intentan agregar {item.quantity})"
            )
        self.items.append(item)

    # ----- máquina de estados ---------------------------------------------
    def confirm(self) -> None:
        self._require_status("confirmar", OrderStatus.DRAFT)
        if not self.items:
            raise InvalidOrderData("No se puede confirmar un pedido sin artículos")
        if not self.customer.active:
            raise InvalidOrderData(f"No se puede confirmar: el cliente {self.customer.id} está inactivo")
        self._change_to(OrderStatus.CONFIRMED, ORDER_CONFIRMED)

    def ship(self, tracking_number: str | None) -> None:
        self._require_status("enviar", OrderStatus.CONFIRMED)
        if tracking_number is None or not str(tracking_number).strip():
            raise InvalidOrderData("No se puede enviar sin número de guía")
        self._change_to(OrderStatus.SHIPPED, ORDER_SHIPPED, detail=str(tracking_number).strip())

    def cancel(self, reason: str | None) -> None:
        self._require_status("cancelar", OrderStatus.CONFIRMED)
        if reason is None or not str(reason).strip():
            raise InvalidOrderData("La cancelación requiere un motivo")
        self._change_to(OrderStatus.CANCELLED, ORDER_CANCELLED, detail=str(reason).strip())

    def deliver(self) -> None:
        self._require_status("entregar", OrderStatus.SHIPPED)
        self._change_to(OrderStatus.DELIVERED, ORDER_DELIVERED)

    def return_order(self) -> None:
        self._require_status("devolver", OrderStatus.SHIPPED)
        self._change_to(OrderStatus.RETURNED, ORDER_RETURNED)

    # ----- auxiliares privados ---------------------------------------------
    def _require_status(self, action: str, expected: OrderStatus) -> None:
        if self.status != expected:
            raise InvalidOrderTransition(action, self.status)

    def _change_to(self, new_status: OrderStatus, event_name: str, detail: str = "") -> None:
        # Solo se llega aquí si todas las validaciones pasaron.
        self.status = new_status
        self.events.append(
            DomainEvent(event_name, self.id, self.customer.id, self.total, detail)
        )
