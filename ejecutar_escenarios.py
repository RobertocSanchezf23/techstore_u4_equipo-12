"""Ejecuta los escenarios E01-E15 de datos/escenarios.csv sobre el dominio.

Cada escenario usa una carga NUEVA de los CSV (load_fixture), para que los
cambios de estado de un caso no afecten al siguiente. Imprime una línea por
escenario y, si una operación fue rechazada, el mensaje que recibió el usuario.

Uso:  python ejecutar_escenarios.py
"""
from decimal import Decimal

from app.domain import DomainException, Money, OrderItem
from app.specifications import evaluate_discount
from cargar_csv import load_fixture, rows

PRICES = {x["sku"]: Decimal(x["precio_mxn"]) for x in rows("productos.csv")}


def step(order, action):
    """Ejecuta una operación. Devuelve None si fue válida o el mensaje de rechazo."""
    try:
        action()
        return None
    except DomainException as exc:
        return f"{type(exc).__name__}: {exc}"


def run(case):
    """Devuelve (resultado obtenido, pedido, mensaje de rechazo o None)."""
    order = load_fixture()[case["pedido_id"]]
    action, oid = case["accion"], order.id

    if action == "evaluar_descuento":
        result = evaluate_discount(order)
        return f"{result.percent.normalize():f}%", order, None

    if action == "confirmar":
        error = step(order, order.confirm)
        return ("rechazo" if error else "exito"), order, error

    if action.startswith("agregar"):  # "agregar SKU003 x2"
        _, sku, qty = action.split()
        item = OrderItem(sku, int(qty.lstrip("x")), Money(PRICES[sku]))
        error = step(order, lambda: order.add_item(item))
        return ("rechazo" if error else "exito"), order, error

    if action == "confirmar y enviar sin guia":
        a = step(order, order.confirm)
        b = step(order, lambda: order.ship(""))
        return ("rechazo envio" if a is None and b else "inesperado"), order, b

    if action == "confirmar dos veces":
        a = step(order, order.confirm)
        b = step(order, order.confirm)
        return ("rechazo segunda" if a is None and b else "inesperado"), order, b

    if action.startswith("confirmar, enviar y "):
        a = step(order, order.confirm)
        b = step(order, lambda: order.ship(f"GUIA-{oid}"))
        last = action.rsplit(" ", 1)[-1]
        if last == "cancelar":
            c = step(order, lambda: order.cancel("El cliente ya no lo necesita"))
            ok = a is None and b is None and c
            return ("rechazo cancelacion" if ok else "inesperado"), order, c
        method = {"devolver": order.return_order, "entregar": order.deliver}[last]
        c = step(order, method)
        return ("exito" if a is None and b is None and c is None else "inesperado"), order, c

    raise ValueError(f"Acción no reconocida: {action}")


def main():
    cases = rows("escenarios.csv")
    header = (f"{'Caso':<5}{'Pedido':<7}{'Operación':<30}{'Objetivo':<21}{'Obtenido':<21}"
              f"{'Estado final':<13}{'Eventos':<8}Resultado")
    print(header)
    print("-" * len(header))
    passed = 0
    for case in cases:
        obtained, order, error = run(case)
        ok = obtained == case["objetivo"]
        passed += ok
        print(f'{case["caso_id"]:<5}{case["pedido_id"]:<7}{case["accion"]:<30}{case["objetivo"]:<21}'
              f'{obtained:<21}{order.status.value:<13}{len(order.events):<8}'
              f'{"COINCIDE" if ok else "NO COINCIDE"}')
        if error:
            print(f"{'':<12}-> {error}")
    print("-" * len(header))
    print(f"{passed}/{len(cases)} escenarios coinciden con el objetivo de datos/escenarios.csv")


if __name__ == "__main__":
    main()
