"""Los 15 escenarios de datos/escenarios.csv, una prueba por caso.

Cada prueba recibe una carga nueva de los CSV (fixture `orders`), así que los
cambios de estado de un escenario no afectan a los demás.
"""
from decimal import Decimal

import pytest

from app.domain import (
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    OrderItem,
    OrderItemLimitExceeded,
    OrderStatus,
)
from app.specifications import evaluate_discount


def event_names(order):
    return [e.name for e in order.events]


# E01-E05: descuentos, VIP y promoción activa ---------------------------------
def test_e01_o001_vip_con_4_unidades_tiene_10(orders):
    assert evaluate_discount(orders["O001"]).percent == Decimal("10")


def test_e02_o002_no_vip_menor_a_5000_tiene_0(orders):
    assert evaluate_discount(orders["O002"]).percent == Decimal("0")


def test_e03_o003_cliente_inactivo_no_confirma(orders):
    order = orders["O003"]
    with pytest.raises(InvalidOrderData):
        order.confirm()
    assert order.status == OrderStatus.DRAFT and event_names(order) == []


def test_e04_o005_promocion_activa_bloquea_descuento(orders):
    assert evaluate_discount(orders["O005"]).percent == Decimal("0")


def test_e05_o006_total_mayor_a_5000_tiene_5(orders):
    assert evaluate_discount(orders["O006"]).percent == Decimal("5")


# E06-E10: pedido vacío, límite de 20 y valores frontera ----------------------
def test_e06_o007_pedido_vacio_no_confirma(orders):
    order = orders["O007"]
    with pytest.raises(InvalidOrderData):
        order.confirm()
    assert order.status == OrderStatus.DRAFT and event_names(order) == []


def test_e07_o008_veinte_unidades_confirma(orders):
    order = orders["O008"]
    order.confirm()
    assert order.status == OrderStatus.CONFIRMED
    assert event_names(order) == ["OrderConfirmed"]


def test_e08_o009_agregar_2_a_19_unidades_excede_limite(orders):
    order = orders["O009"]
    with pytest.raises(OrderItemLimitExceeded):
        order.add_item(OrderItem("SKU003", 2, Money(Decimal("120.00"))))
    assert order.units == 19 and order.status == OrderStatus.DRAFT


def test_e09_o010_total_exacto_500_no_supera_umbral(orders):
    assert orders["O010"].total.amount == Decimal("500.00")
    assert evaluate_discount(orders["O010"]).percent == Decimal("0")


def test_e10_o011_vip_con_3_unidades_tiene_0(orders):
    assert orders["O011"].units == 3
    assert evaluate_discount(orders["O011"]).percent == Decimal("0")


# E11-E13: guía obligatoria y transiciones prohibidas ------------------------
def test_e11_o012_confirma_pero_no_envia_sin_guia(orders):
    order = orders["O012"]
    order.confirm()
    with pytest.raises(InvalidOrderData):
        order.ship("")
    assert order.status == OrderStatus.CONFIRMED
    assert event_names(order) == ["OrderConfirmed"]


def test_e12_o013_segunda_confirmacion_rechazada(orders):
    order = orders["O013"]
    order.confirm()
    with pytest.raises(InvalidOrderTransition):
        order.confirm()
    assert order.status == OrderStatus.CONFIRMED
    assert event_names(order) == ["OrderConfirmed"]


def test_e13_o014_no_cancela_desde_shipped(orders):
    order = orders["O014"]
    order.confirm()
    order.ship("GUIA-O014")
    with pytest.raises(InvalidOrderTransition):
        order.cancel("Cliente desiste")
    assert order.status == OrderStatus.SHIPPED
    assert event_names(order) == ["OrderConfirmed", "OrderShipped"]


# E14-E15: devolución y entrega válidas --------------------------------------
def test_e14_o015_termina_en_returned(orders):
    order = orders["O015"]
    order.confirm()
    order.ship("GUIA-O015")
    order.return_order()
    assert order.status == OrderStatus.RETURNED
    assert event_names(order) == ["OrderConfirmed", "OrderShipped", "OrderReturned"]


def test_e15_o016_termina_en_delivered(orders):
    order = orders["O016"]
    order.confirm()
    order.ship("GUIA-O016")
    order.deliver()
    assert order.status == OrderStatus.DELIVERED
    assert event_names(order) == ["OrderConfirmed", "OrderShipped", "OrderDelivered"]
