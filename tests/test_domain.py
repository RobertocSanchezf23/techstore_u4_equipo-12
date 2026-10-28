"""Pruebas del dominio: Value Objects, invariantes de Order y máquina de estados.

Cada prueba sigue tres partes: preparar datos, ejecutar la acción y comprobar.
"""
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domain import (
    Customer,
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    Order,
    OrderItem,
    OrderItemLimitExceeded,
    OrderStatus,
)


def make_order(units=1, active=True, price="100.00"):
    order = Order(customer=Customer("CX", is_vip=False, active=active), id="TEST")
    if units:
        order.add_item(OrderItem("SKU-T", units, Money(Decimal(price))))
    return order


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def test_money_negativo():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("-1"))


def test_money_rechaza_float():
    with pytest.raises(InvalidOrderData):
        Money(600.00)


def test_money_es_inmutable():
    money = Money(Decimal("100"))
    with pytest.raises(FrozenInstanceError):
        money.amount = Decimal("1")


def test_money_add_devuelve_objeto_nuevo():
    a, b = Money(Decimal("100")), Money(Decimal("50"))
    c = a.add(b)
    assert c == Money(Decimal("150"))
    assert a.amount == Decimal("100") and b.amount == Decimal("50")


def test_money_add_rechaza_monedas_distintas():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("1"), "MXN").add(Money(Decimal("1"), "USD"))


def test_money_se_compara_por_valor():
    assert Money(Decimal("100"), "MXN") == Money(Decimal("100"), "MXN")


# ---------------------------------------------------------------------------
# OrderItem y Customer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("quantity", [0, -3])
def test_orderitem_rechaza_cantidad_cero_o_negativa(quantity):
    with pytest.raises(InvalidOrderData):
        OrderItem("SKU001", quantity, Money(Decimal("600.00")))


def test_orderitem_rechaza_sku_vacio():
    with pytest.raises(InvalidOrderData):
        OrderItem("  ", 1, Money(Decimal("600.00")))


def test_orderitem_calcula_subtotal():
    item = OrderItem("SKU001", 2, Money(Decimal("600.00")))
    assert item.subtotal == Money(Decimal("1200.00"))


def test_customer_requiere_id():
    with pytest.raises(InvalidOrderData):
        Customer("")


# ---------------------------------------------------------------------------
# Carga de los CSV
# ---------------------------------------------------------------------------
def test_se_cargan_16_pedidos_en_draft(orders):
    assert len(orders) == 16
    assert all(o.status == OrderStatus.DRAFT for o in orders.values())
    assert all(o.events == [] for o in orders.values())


def test_pedido_o001_inicia_draft(orders):
    assert orders["O001"].status.value == "DRAFT"
    assert orders["O001"].units == 4
    assert orders["O001"].total.amount == Decimal("2100.00")


@pytest.mark.parametrize(
    "order_id, customer, units, total",
    [("O001", "C001", 4, "2100.00"), ("O006", "C006", 1, "18000.00"), ("O010", "C010", 2, "500.00")],
)
def test_calculo_manual_de_la_seccion_5(orders, order_id, customer, units, total):
    order = orders[order_id]
    assert order.customer.id == customer
    assert order.units == units
    assert order.total.amount == Decimal(total)


def test_units_suma_cantidades_no_cuenta_renglones(orders):
    order = orders["O011"]  # 2 renglones: SKU001 x1 y SKU002 x2
    assert len(order.items) == 2
    assert order.units == 3


# ---------------------------------------------------------------------------
# Límite de 20 unidades
# ---------------------------------------------------------------------------
def test_veinte_unidades_permitidas(orders):
    assert orders["O008"].units == 20


def test_unidad_21_lanza_limite_y_no_modifica_items(orders):
    order = orders["O009"]  # 19 unidades
    with pytest.raises(OrderItemLimitExceeded):
        order.add_item(OrderItem("SKU003", 2, Money(Decimal("120.00"))))
    assert order.units == 19
    assert len(order.items) == 1


def test_no_se_agregan_articulos_despues_de_confirmar(orders):
    order = orders["O013"]
    order.confirm()
    with pytest.raises(InvalidOrderTransition):
        order.add_item(OrderItem("SKU001", 1, Money(Decimal("600.00"))))
    assert order.units == 1


# ---------------------------------------------------------------------------
# Confirmación
# ---------------------------------------------------------------------------
def test_confirmar_cambia_estado_y_registra_evento():
    order = make_order()
    order.confirm()
    assert order.status == OrderStatus.CONFIRMED
    assert [e.name for e in order.events] == ["OrderConfirmed"]
    assert order.events[0].order_id == "TEST"
    assert order.events[0].total == Money(Decimal("100.00"))


def test_cliente_inactivo_no_confirma(orders):
    order = orders["O003"]
    with pytest.raises(InvalidOrderData):
        order.confirm()
    assert order.status == OrderStatus.DRAFT
    assert order.events == []


def test_pedido_vacio_no_confirma(orders):
    order = orders["O007"]
    with pytest.raises(InvalidOrderData):
        order.confirm()
    assert order.status == OrderStatus.DRAFT
    assert order.events == []


def test_confirmacion_doble_falla_sin_agregar_evento(orders):
    order = orders["O013"]
    order.confirm()
    with pytest.raises(InvalidOrderTransition):
        order.confirm()
    assert order.status == OrderStatus.CONFIRMED
    assert [e.name for e in order.events] == ["OrderConfirmed"]


# ---------------------------------------------------------------------------
# Envío, cancelación, entrega y devolución
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tracking", [None, "", "   "])
def test_envio_sin_guia_falla(tracking):
    order = make_order()
    order.confirm()
    with pytest.raises(InvalidOrderData):
        order.ship(tracking)
    assert order.status == OrderStatus.CONFIRMED
    assert len(order.events) == 1


def test_envio_desde_draft_falla():
    order = make_order()
    with pytest.raises(InvalidOrderTransition):
        order.ship("GUIA-1")
    assert order.status == OrderStatus.DRAFT


def test_envio_valido_guarda_la_guia_en_el_evento():
    order = make_order()
    order.confirm()
    order.ship("GUIA-1")
    assert order.status == OrderStatus.SHIPPED
    assert order.events[-1].name == "OrderShipped"
    assert order.events[-1].detail == "GUIA-1"
    assert order.events[-1].description == "Pedido enviado con la guía GUIA-1"


def test_cancelar_desde_confirmed_con_motivo():
    order = make_order()
    order.confirm()
    order.cancel("Cliente desiste")
    assert order.status == OrderStatus.CANCELLED
    assert order.events[-1].name == "OrderCancelled"


def test_cancelar_sin_motivo_falla():
    order = make_order()
    order.confirm()
    with pytest.raises(InvalidOrderData):
        order.cancel(" ")
    assert order.status == OrderStatus.CONFIRMED


def test_cancelacion_desde_shipped_falla(orders):
    order = orders["O014"]
    order.confirm()
    order.ship("GUIA-O014")
    with pytest.raises(InvalidOrderTransition):
        order.cancel("Cliente desiste")
    assert order.status == OrderStatus.SHIPPED
    assert [e.name for e in order.events] == ["OrderConfirmed", "OrderShipped"]


def test_entregar_y_devolver_exigen_shipped():
    order = make_order()
    order.confirm()
    with pytest.raises(InvalidOrderTransition):
        order.deliver()
    with pytest.raises(InvalidOrderTransition):
        order.return_order()
    assert order.status == OrderStatus.CONFIRMED


@pytest.mark.parametrize("final_state", [OrderStatus.DELIVERED, OrderStatus.RETURNED])
def test_estados_finales_no_admiten_mas_transiciones(final_state):
    order = make_order()
    order.confirm()
    order.ship("GUIA-1")
    order.deliver() if final_state == OrderStatus.DELIVERED else order.return_order()
    events = len(order.events)
    for operation in (order.confirm, order.deliver, order.return_order,
                      lambda: order.ship("G"), lambda: order.cancel("x")):
        with pytest.raises(InvalidOrderTransition):
            operation()
    assert order.status == final_state
    assert len(order.events) == events


@pytest.mark.parametrize("operation, expected", [
    (lambda o: o.ship("G"), "Este pedido aún no ha sido confirmado; primero confírmalo para poder enviarlo."),
    (lambda o: (o.confirm(), o.deliver()), "Este pedido todavía no ha sido enviado; primero envíalo para poder entregarlo."),
    (lambda o: (o.confirm(), o.confirm()), "Este pedido ya fue confirmado; no se puede confirmar otra vez."),
])
def test_mensajes_de_transicion_claros_para_el_usuario(operation, expected):
    order = make_order()
    with pytest.raises(InvalidOrderTransition) as error:
        operation(order)
    assert str(error.value) == expected
