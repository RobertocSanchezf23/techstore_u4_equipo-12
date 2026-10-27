"""Specification Pattern para las reglas de descuento de TechStore.

Cada Specification responde una pregunta de elegibilidad con True o False y
NUNCA modifica el pedido. Las reglas se combinan con:
    &  -> AND (todas deben cumplirse)
    |  -> OR  (basta una)
    ~  -> NOT (negación)
"""
from dataclasses import dataclass
from decimal import Decimal

from app.domain import Money, Order


class Specification:
    def is_satisfied_by(self, order: Order) -> bool:
        raise NotImplementedError

    def __and__(self, other: "Specification") -> "Specification":
        return AndSpec(self, other)

    def __or__(self, other: "Specification") -> "Specification":
        return OrSpec(self, other)

    def __invert__(self) -> "Specification":
        return NotSpec(self)


class AndSpec(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left, self.right = left, right

    def is_satisfied_by(self, order: Order) -> bool:
        return self.left.is_satisfied_by(order) and self.right.is_satisfied_by(order)


class OrSpec(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left, self.right = left, right

    def is_satisfied_by(self, order: Order) -> bool:
        return self.left.is_satisfied_by(order) or self.right.is_satisfied_by(order)


class NotSpec(Specification):
    def __init__(self, spec: Specification):
        self.spec = spec

    def is_satisfied_by(self, order: Order) -> bool:
        return not self.spec.is_satisfied_by(order)


# ---------------------------------------------------------------------------
# Specifications concretas
# ---------------------------------------------------------------------------
class MinimumAmountSpec(Specification):
    """El total del pedido SUPERA el umbral (estrictamente mayor: > y no >=)."""

    def __init__(self, threshold: Decimal):
        self.threshold = Decimal(threshold)

    def is_satisfied_by(self, order: Order) -> bool:
        return order.total.amount > self.threshold


class VIPCustomerSpec(Specification):
    """El cliente del pedido es VIP."""

    def is_satisfied_by(self, order: Order) -> bool:
        return order.customer.is_vip


class MinimumUnitsSpec(Specification):
    """El pedido tiene AL MENOS n unidades (suma de cantidades, no renglones)."""

    def __init__(self, minimum: int):
        self.minimum = minimum

    def is_satisfied_by(self, order: Order) -> bool:
        return order.units >= self.minimum


class ActivePromotionSpec(Specification):
    """El pedido tiene una promoción activa."""

    def is_satisfied_by(self, order: Order) -> bool:
        return order.has_promotion


# ---------------------------------------------------------------------------
# Reglas de negocio compuestas
# ---------------------------------------------------------------------------
# 10 %: VIP AND total > 500 AND unidades >= 4 AND NOT promoción
TEN_PERCENT_RULE = (
    MinimumAmountSpec(Decimal("500"))
    & VIPCustomerSpec()
    & MinimumUnitsSpec(4)
    & ~ActivePromotionSpec()
)

# 5 %: total > 5000 AND NOT promoción
FIVE_PERCENT_RULE = MinimumAmountSpec(Decimal("5000")) & ~ActivePromotionSpec()

# Alguna de las dos reglas: OR
ANY_DISCOUNT_RULE = TEN_PERCENT_RULE | FIVE_PERCENT_RULE


@dataclass(frozen=True)
class DiscountResult:
    percent: Decimal
    rule: str
    subtotal: Money
    discount: Money
    total: Money


def evaluate_discount(order: Order) -> DiscountResult:
    """Calcula el descuento aplicable sin modificar el pedido.

    Si se cumplen ambas reglas, tiene prioridad el 10 %.
    """
    subtotal = order.total
    if not ANY_DISCOUNT_RULE.is_satisfied_by(order):
        percent, rule = Decimal("0"), "Sin descuento"
    elif TEN_PERCENT_RULE.is_satisfied_by(order):
        percent, rule = Decimal("10"), "10 %: VIP, total > 500, >= 4 unidades y sin promoción"
    else:
        percent, rule = Decimal("5"), "5 %: total > 5000 y sin promoción"
    discount = subtotal.percentage(percent)
    return DiscountResult(percent, rule, subtotal, discount, subtotal.subtract(discount))
