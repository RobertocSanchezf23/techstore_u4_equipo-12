"""Pruebas de la API REST: códigos HTTP 200/201, 404, 409 y 422."""
import pytest
from fastapi.testclient import TestClient

from app import api

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def datos_limpios():
    """Cada prueba empieza con los 16 pedidos originales en DRAFT."""
    api.reset_data()


def test_documentacion_openapi_disponible():
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/orders/{order_id}/confirm" in paths


def test_listar_pedidos():
    response = client.get("/orders")
    assert response.status_code == 200
    assert len(response.json()) == 16


def test_consultar_pedido():
    response = client.get("/orders/O001")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DRAFT" and body["units"] == 4 and body["total"] == "2100.00"


def test_pedido_inexistente_404():
    response = client.post("/orders/O999/confirm")
    assert response.status_code == 404
    assert client.get("/orders/O999").status_code == 404


def test_confirmar_200_y_evento():
    response = client.post("/orders/O013/confirm")
    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"
    assert [e["name"] for e in response.json()["events"]] == ["OrderConfirmed"]


def test_confirmar_dos_veces_409():
    client.post("/orders/O013/confirm")
    response = client.post("/orders/O013/confirm")
    assert response.status_code == 409
    assert response.json()["detail"] == "Este pedido ya fue confirmado; no se puede confirmar otra vez."
    assert response.json()["error"] == "InvalidOrderTransition"


def test_confirmar_pedido_vacio_422():
    response = client.post("/orders/O007/confirm")
    assert response.status_code == 422
    assert client.get("/orders/O007").json()["status"] == "DRAFT"


def test_confirmar_cliente_inactivo_422():
    assert client.post("/orders/O003/confirm").status_code == 422


def test_enviar_sin_guia_422():
    client.post("/orders/O012/confirm")
    response = client.post("/orders/O012/ship", json={"tracking_number": ""})
    assert response.status_code == 422
    assert client.get("/orders/O012").json()["status"] == "CONFIRMED"


def test_cancelar_desde_shipped_409():
    client.post("/orders/O014/confirm")
    client.post("/orders/O014/ship", json={"tracking_number": "GUIA-O014"})
    response = client.post("/orders/O014/cancel", json={"reason": "Cliente desiste"})
    assert response.status_code == 409


def test_flujo_completo_entrega_y_devolucion():
    for order_id, last, final in (("O016", "deliver", "DELIVERED"), ("O015", "return", "RETURNED")):
        client.post(f"/orders/{order_id}/confirm")
        client.post(f"/orders/{order_id}/ship", json={"tracking_number": f"GUIA-{order_id}"})
        response = client.post(f"/orders/{order_id}/{last}")
        assert response.status_code == 200
        assert response.json()["status"] == final


def test_agregar_articulo_que_excede_20_unidades_422():
    response = client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 2})
    assert response.status_code == 422
    assert client.get("/orders/O009").json()["units"] == 19


def test_agregar_articulo_valido():
    response = client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 1})
    assert response.status_code == 200
    assert response.json()["units"] == 20


def test_descuento_por_api():
    assert client.get("/orders/O001/discount").json()["percent"] == "10"
    assert client.get("/orders/O006/discount").json()["total_with_discount"] == "17100.00"


def test_crear_pedido_201_en_draft():
    response = client.post("/orders", json={"customer_id": "C001"})
    assert response.status_code == 201
    assert response.json()["id"] == "O017"
    assert response.json()["status"] == "DRAFT"


def test_crear_pedido_con_cliente_inexistente_422():
    assert client.post("/orders", json={"customer_id": "C999"}).status_code == 422


def test_reload_restaura_los_datos():
    client.post("/orders/O013/confirm")
    assert client.post("/fixtures/reload").json() == {"orders_loaded": 16}
    assert client.get("/orders/O013").json()["status"] == "DRAFT"


def test_respuesta_exitosa_trae_mensaje_para_el_usuario():
    body = client.post("/orders/O013/confirm").json()
    assert body["message"] == "El pedido O013 se confirmó correctamente."
    assert body["events"][0]["description"] == "Pedido confirmado"


def test_mensajes_de_error_claros_para_el_usuario():
    client.post("/orders/O014/confirm")
    client.post("/orders/O014/ship", json={"tracking_number": "GUIA-O014"})
    cancel = client.post("/orders/O014/cancel", json={"reason": "Cliente desiste"}).json()
    assert cancel["detail"] == "Este pedido ya fue enviado, por eso ya no se puede cancelar."
    assert client.get("/orders/O999").json()["detail"].startswith("No encontramos el pedido O999")


def test_swagger_funciona_sin_internet():
    html = client.get("/docs").text
    assert "/static/swagger-ui-bundle.js" in html and "cdn.jsdelivr.net" not in html
    assert client.get("/static/swagger-ui-bundle.js").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/docs"
