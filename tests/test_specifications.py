"""Pruebas de las Specifications y de la composición AND, OR y NOT."""
from decimal import Decimal

from app.domain import Customer, Money, Order, OrderItem
from app.specifications import (
    FIVE_PERCENT_RULE,
    TEN_PERCENT_RULE,
    ActivePromotionSpec,
    MinimumAmountSpec,
    MinimumUnitsSpec,
    VIPCustomerSpec,
    evaluate_discount,
)


def make_order(vip=True, promo=False, units=4, price="200.00"):
    order = Order(customer=Customer("CX", is_vip=vip), id="TEST", has_promotion=promo)
    order.add_item(OrderItem("SKU-T", units, Money(Decimal(price))))
    return order


# ---------------------------------------------------------------------------
# Specifications individuales
# ---------------------------------------------------------------------------
def test_minimum_amount_es_estricto(orders):
    spec = MinimumAmountSpec(Decimal("500"))
    assert orders["O010"].total.amount == Decimal("500.00")
    assert spec.is_satisfied_by(orders["O010"]) is False  # 500 no supera 500
    assert spec.is_satisfied_by(make_order(units=1, price="500.01")) is True


def test_vip_customer(orders):
    assert VIPCustomerSpec().is_satisfied_by(orders["O001"]) is True
    assert VIPCustomerSpec().is_satisfied_by(orders["O002"]) is False


def test_minimum_units_es_mayor_o_igual(orders):
    spec = MinimumUnitsSpec(4)
    assert spec.is_satisfied_by(orders["O001"]) is True   # 4 unidades
    assert spec.is_satisfied_by(orders["O011"]) is False  # 3 unidades


def test_active_promotion(orders):
    assert ActivePromotionSpec().is_satisfied_by(orders["O005"]) is True
    assert ActivePromotionSpec().is_satisfied_by(orders["O001"]) is False


# ---------------------------------------------------------------------------
# Composición
# ---------------------------------------------------------------------------
def test_and_requiere_ambas():
    spec = VIPCustomerSpec() & MinimumUnitsSpec(4)
    assert spec.is_satisfied_by(make_order(vip=True, units=4)) is True
    assert spec.is_satisfied_by(make_order(vip=False, units=4)) is False


def test_or_basta_una():
    spec = VIPCustomerSpec() | MinimumUnitsSpec(10)
    assert spec.is_satisfied_by(make_order(vip=False, units=10)) is True
    assert spec.is_satisfied_by(make_order(vip=False, units=1)) is False


def test_not_invierte():
    assert (~ActivePromotionSpec()).is_satisfied_by(make_order(promo=False)) is True
    assert (~ActivePromotionSpec()).is_satisfied_by(make_order(promo=True)) is False


def test_specification_no_modifica_el_pedido(orders):
    order = orders["O001"]
    before = (order.status, order.units, order.total, list(order.events))
    TEN_PERCENT_RULE.is_satisfied_by(order)
    evaluate_discount(order)
    assert (order.status, order.units, order.total, list(order.events)) == before


# ---------------------------------------------------------------------------
# Reglas de descuento
# ---------------------------------------------------------------------------
def test_descuento_vip_10(orders):
    result = evaluate_discount(orders["O001"])
    assert result.percent == Decimal("10")
    assert result.discount.amount == Decimal("210.00")
    assert result.total.amount == Decimal("1890.00")


def test_descuento_5_por_total_mayor_a_5000(orders):
    result = evaluate_discount(orders["O006"])
    assert result.percent == Decimal("5")
    assert result.total.amount == Decimal("17100.00")


def test_promocion_activa_bloquea_descuentos(orders):
    assert TEN_PERCENT_RULE.is_satisfied_by(orders["O005"]) is False
    assert evaluate_discount(orders["O005"]).percent == Decimal("0")
    assert FIVE_PERCENT_RULE.is_satisfied_by(make_order(units=1, price="9000.00", promo=True)) is False


def test_prioridad_10_si_ambas_reglas_se_cumplen():
    order = make_order(vip=True, units=4, price="2000.00")  # 8000 MXN, VIP, 4 unidades
    assert TEN_PERCENT_RULE.is_satisfied_by(order) and FIVE_PERCENT_RULE.is_satisfied_by(order)
    assert evaluate_discount(order).percent == Decimal("10")


def test_total_exacto_5000_no_tiene_5():
    order = make_order(vip=False, units=1, price="5000.00")
    assert evaluate_discount(order).percent == Decimal("0")
