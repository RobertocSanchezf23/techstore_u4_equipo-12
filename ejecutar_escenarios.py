"""Ejecuta los escenarios E01-E15 de datos/escenarios.csv sobre el dominio.

Cada escenario usa una carga NUEVA de los CSV (load_fixture), para que los
cambios de estado de un caso no afecten al siguiente.

Uso:  python ejecutar_escenarios.py
"""
from decimal import Decimal

from app.domain import DomainException, Money, OrderItem
from app.specifications import evaluate_discount
from cargar_csv import load_fixture, rows

PRICES = {x["sku"]: Decimal(x["precio_mxn"]) for x in rows("productos.csv")}


def step(order, name, action, log):
    """Ejecuta una operación y registra si fue exitosa o rechazada."""
    before = len(order.events)
    try:
        action()
        new_events = [e.name for e in order.events[before:]]
        log.append((name, "OK", order.status.value, ", ".join(new_events) or "-"))
        return True
    except DomainException as exc:
        log.append((name, f"RECHAZO ({type(exc).__name__}: {exc})", order.status.value, "sin evento"))
        return False


def run(case):
    order = load_fixture()[case["pedido_id"]]
    initial = f'{order.status.value}, {order.units} u, {order.total.amount} MXN'
    action, log, oid = case["accion"], [], order.id

    if action == "evaluar_descuento":
        r = evaluate_discount(order)
        result = f"{r.percent.normalize():f}%"
        log.append(("evaluar_descuento", f"{result} -> paga {r.total.amount} MXN", order.status.value, "-"))
        return initial, log, result

    if action == "confirmar":
        ok = step(order, "confirm()", order.confirm, log)
        return initial, log, "exito" if ok else "rechazo"

    if action.startswith("agregar"):  # "agregar SKU003 x2"
        _, sku, qty = action.split()
        item = OrderItem(sku, int(qty.lstrip("x")), Money(PRICES[sku]))
        ok = step(order, f"add_item({sku} x{qty.lstrip('x')})", lambda: order.add_item(item), log)
        return initial, log, "exito" if ok else "rechazo"

    if action == "confirmar y enviar sin guia":
        a = step(order, "confirm()", order.confirm, log)
        b = step(order, 'ship("")', lambda: order.ship(""), log)
        return initial, log, "rechazo envio" if a and not b else "inesperado"

    if action == "confirmar dos veces":
        a = step(order, "confirm()", order.confirm, log)
        b = step(order, "confirm() otra vez", order.confirm, log)
        return initial, log, "rechazo segunda" if a and not b else "inesperado"

    if action.startswith("confirmar, enviar y "):
        a = step(order, "confirm()", order.confirm, log)
        b = step(order, f'ship("GUIA-{oid}")', lambda: order.ship(f"GUIA-{oid}"), log)
        last = action.rsplit(" ", 1)[-1]
        if last == "cancelar":
            c = step(order, 'cancel("Cliente desiste")', lambda: order.cancel("Cliente desiste"), log)
            return initial, log, "rechazo cancelacion" if a and b and not c else "inesperado"
        method = {"devolver": ("return_order()", order.return_order),
                  "entregar": ("deliver()", order.deliver)}[last]
        c = step(order, method[0], method[1], log)
        return initial, log, "exito" if a and b and c else "inesperado"

    raise ValueError(f"Acción no reconocida: {action}")


def main():
    cases = rows("escenarios.csv")
    passed = 0
    for case in cases:
        initial, log, obtained = run(case)
        ok = obtained == case["objetivo"]
        passed += ok
        print(f'\n{case["caso_id"]} | {case["pedido_id"]} | {case["accion"]} | objetivo: {case["objetivo"]}')
        print(f"   estado inicial: {initial}")
        for name, res, status, events in log:
            print(f"   {name:<28} {res}")
            print(f"   {'':<28} estado: {status} | evento: {events}")
        print(f"   resultado: {obtained} -> {'COINCIDE' if ok else 'NO COINCIDE'}")
    print(f"\n{passed}/{len(cases)} escenarios coinciden con el objetivo de escenarios.csv")


if __name__ == "__main__":
    main()
