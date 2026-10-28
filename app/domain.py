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
        super().__init__(_transition_message(action, current))


# Cómo se describe cada estado al usuario
_STATE_TEXT = {
    "DRAFT": "aún no ha sido confirmado",
    "CONFIRMED": "ya fue confirmado",
    "SHIPPED": "ya fue enviado",
    "DELIVERED": "ya fue entregado",
    "CANCELLED": "fue cancelado",
    "RETURNED": "fue devuelto",
}
_ACTION_OBJECT = {"confirmar": "confirmarlo", "enviar": "enviarlo", "cancelar": "cancelarlo",
                  "entregar": "entregarlo", "devolver": "devolverlo"}


def _transition_message(action: str, current: "OrderStatus") -> str:
    """Mensaje claro para el usuario cuando una transición no está permitida."""
    state = current.value
    obj = _ACTION_OBJECT.get(action, action)
    if action == "confirmar" and state == "CONFIRMED":
        return "Este pedido ya fue confirmado; no se puede confirmar otra vez."
    if action == "agregar artículos a":
        return (f"Este pedido {_STATE_TEXT[state]}; solo se pueden agregar artículos "
                "mientras el pedido está en borrador.")
    if state == "DRAFT":
        return f"Este pedido aún no ha sido confirmado; primero confírmalo para poder {obj}."
    if action in ("entregar", "devolver") and state == "CONFIRMED":
        return f"Este pedido todavía no ha sido enviado; primero envíalo para poder {obj}."
    if state in ("DELIVERED", "CANCELLED", "RETURNED"):
        return f"Este pedido {_STATE_TEXT[state]} y ya no admite cambios."
    return f"Este pedido {_STATE_TEXT[state]}, por eso ya no se puede {action}."


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
            raise InvalidOrderData("El monto debe expresarse con Decimal, no con float.")
        if not self.amount.is_finite() or self.amount < 0:
            raise InvalidOrderData("El monto no es válido: no puede ser negativo.")
        if not isinstance(self.currency, str) or len(self.currency.strip()) != 3:
            raise InvalidOrderData("La moneda no es válida.")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("No se pueden sumar importes en monedas distintas.")
        return Money(self.amount + other.amount, self.currency)

    def multiply(self, quantity: int) -> "Money":
        return Money(self.amount * quantity, self.currency)

    def percentage(self, percent: Decimal) -> "Money":
        """Devuelve el porcentaje indicado del importe, redondeado a centavos."""
        value = (self.amount * percent / Decimal("100")).quantize(CENTS, rounding=ROUND_HALF_UP)
        return Money(value, self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("No se pueden restar importes en monedas distintas.")
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
            raise InvalidOrderData("El cliente debe tener un identificador.")


@dataclass(frozen=True)
class OrderItem:
    """Un renglón del pedido. El subtotal se calcula; nunca se captura a mano."""

    sku: str
    quantity: int
    unit_price: Money

    def __post_init__(self):
        if not isinstance(self.sku, str) or not self.sku.strip():
            raise InvalidOrderData("El artículo debe tener un SKU.")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise InvalidOrderData("La cantidad debe ser un número entero mayor que cero.")
        if not isinstance(self.unit_price, Money):
            raise InvalidOrderData("El precio del artículo debe ser un Money.")

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
    description: str  # qué pasó, en palabras del negocio
    detail: str = ""  # dato asociado: número de guía o motivo de cancelación
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
            raise InvalidOrderData("El pedido debe tener un identificador.")
        if not isinstance(self.customer, Customer):
            raise InvalidOrderData("El pedido debe tener un cliente.")

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
            raise InvalidOrderData("Solo se pueden agregar objetos OrderItem.")
        if item.unit_price.currency != CURRENCY:
            raise InvalidOrderData(f"Solo se aceptan precios en {CURRENCY}.")
        if self.units + item.quantity > MAX_UNITS_PER_ORDER:
            raise OrderItemLimitExceeded(
                f"El pedido no puede tener más de {MAX_UNITS_PER_ORDER} unidades: ya tiene "
                f"{self.units} y se intentan agregar {item.quantity}."
            )
        self.items.append(item)

    # ----- máquina de estados ---------------------------------------------
    def confirm(self) -> None:
        self._require_status("confirmar", OrderStatus.DRAFT)
        if not self.items:
            raise InvalidOrderData("El pedido no tiene artículos; agrega al menos uno antes de confirmarlo.")
        if not self.customer.active:
            raise InvalidOrderData(f"El cliente {self.customer.id} está inactivo, por eso no puede confirmar pedidos.")
        self._change_to(OrderStatus.CONFIRMED, ORDER_CONFIRMED, "Pedido confirmado")

    def ship(self, tracking_number: str | None) -> None:
        self._require_status("enviar", OrderStatus.CONFIRMED)
        if tracking_number is None or not str(tracking_number).strip():
            raise InvalidOrderData("Falta el número de guía; es obligatorio para enviar el pedido.")
        guide = str(tracking_number).strip()
        self._change_to(OrderStatus.SHIPPED, ORDER_SHIPPED, f"Pedido enviado con la guía {guide}", guide)

    def cancel(self, reason: str | None) -> None:
        self._require_status("cancelar", OrderStatus.CONFIRMED)
        if reason is None or not str(reason).strip():
            raise InvalidOrderData("Indica el motivo de la cancelación.")
        motive = str(reason).strip()
        self._change_to(OrderStatus.CANCELLED, ORDER_CANCELLED, f"Pedido cancelado. Motivo: {motive}", motive)

    def deliver(self) -> None:
        self._require_status("entregar", OrderStatus.SHIPPED)
        self._change_to(OrderStatus.DELIVERED, ORDER_DELIVERED, "Pedido entregado al cliente")

    def return_order(self) -> None:
        self._require_status("devolver", OrderStatus.SHIPPED)
        self._change_to(OrderStatus.RETURNED, ORDER_RETURNED, "Pedido devuelto por el cliente")

    # ----- auxiliares privados ---------------------------------------------
    def _require_status(self, action: str, expected: OrderStatus) -> None:
        if self.status != expected:
            raise InvalidOrderTransition(action, self.status)

    def _change_to(self, new_status: OrderStatus, event_name: str, description: str,
                   detail: str = "") -> None:
        # Solo se llega aquí si todas las validaciones pasaron.
        self.status = new_status
        self.events.append(
            DomainEvent(event_name, self.id, self.customer.id, self.total, description, detail)
        )
