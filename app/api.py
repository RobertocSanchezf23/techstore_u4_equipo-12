"""API REST de TechStore con FastAPI.

Los controladores son delgados: reciben la petición, llaman al Application
Service y convierten el resultado en un DTO de respuesta. No calculan
descuentos ni cambian el estado por su cuenta; las excepciones del dominio se
traducen a códigos HTTP en un solo lugar (los exception handlers).

Ejecutar:  uvicorn app.api:app --reload
Swagger:   http://127.0.0.1:8000/docs
"""
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.domain import Customer, DomainException, InvalidOrderTransition, Order
from app.services import InMemoryOrderRepository, OrderNotFound, OrderService
from cargar_csv import load_fixture, rows

DESCRIPTION = """
Administración de pedidos de la tienda ficticia **TechStore** (Actividad 4, CLN · FIME UANL).

Los pedidos se cargan desde `datos/*.csv` al iniciar y viven **en memoria**.
Usa `POST /fixtures/reload` para volver a los datos originales entre pruebas.

| Código | Significado |
|---|---|
| 200 / 201 | Operación válida |
| 404 | El pedido no existe |
| 409 | Transición de estado no permitida (`InvalidOrderTransition`) |
| 422 | Datos inválidos según el dominio (`InvalidOrderData`, `OrderItemLimitExceeded`) |

Las respuestas exitosas incluyen `message`, un texto para el usuario. Los errores incluyen
`detail` (mensaje para el usuario) y `error` (nombre técnico de la excepción del dominio).
"""

# docs_url=None: la página /docs se define abajo con archivos locales de Swagger UI,
# para que funcione aunque la computadora no tenga internet.
app = FastAPI(title="TechStore U4", version="1.0.0", description=DESCRIPTION,
              docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="TechStore U4 - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon-32x32.png",
    )


@app.get("/", include_in_schema=False)
def home():
    """La dirección principal lleva directo a la documentación."""
    return RedirectResponse(url="/docs")


# ---------------------------------------------------------------------------
# Composición: datos de los CSV -> repositorio en memoria -> Application Service
# ---------------------------------------------------------------------------
def build_service() -> OrderService:
    customers = {
        x["cliente_id"]: Customer(x["cliente_id"], bool(int(x["es_vip"])), bool(int(x["activo"])))
        for x in rows("clientes.csv")
    }
    prices = {x["sku"]: Decimal(x["precio_mxn"]) for x in rows("productos.csv")}
    return OrderService(InMemoryOrderRepository(load_fixture()), customers, prices)


service = build_service()


def reset_data() -> int:
    """Vuelve a cargar los CSV (el repositorio en memoria no persiste cambios)."""
    global service
    service = build_service()
    return len(service.list())


# ---------------------------------------------------------------------------
# Excepciones del dominio -> códigos HTTP semánticos
# ---------------------------------------------------------------------------
@app.exception_handler(OrderNotFound)
def _not_found(request: Request, exc: OrderNotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc), "error": "OrderNotFound"})


@app.exception_handler(InvalidOrderTransition)
def _conflict(request: Request, exc: InvalidOrderTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc), "error": type(exc).__name__})


@app.exception_handler(DomainException)
def _unprocessable(request: Request, exc: DomainException):
    return JSONResponse(status_code=422, content={"detail": str(exc), "error": type(exc).__name__})


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    detail: str
    error: str


class ItemDTO(BaseModel):
    sku: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class EventDTO(BaseModel):
    name: str
    description: str
    occurred_at: str


STATUS_TEXT = {"DRAFT": "en borrador", "CONFIRMED": "confirmado", "SHIPPED": "enviado",
               "DELIVERED": "entregado", "CANCELLED": "cancelado", "RETURNED": "devuelto"}


class OrderDTO(BaseModel):
    message: str
    id: str
    customer_id: str
    customer_vip: bool
    customer_active: bool
    has_promotion: bool
    status: str
    units: int
    total: Decimal
    currency: str
    items: list[ItemDTO]
    events: list[EventDTO]

    @classmethod
    def from_order(cls, order: Order, message: str | None = None) -> "OrderDTO":
        return cls(
            message=message or f"El pedido {order.id} está {STATUS_TEXT[order.status.value]}.",
            id=order.id,
            customer_id=order.customer.id,
            customer_vip=order.customer.is_vip,
            customer_active=order.customer.active,
            has_promotion=order.has_promotion,
            status=order.status.value,
            units=order.units,
            total=order.total.amount,
            currency=order.total.currency,
            items=[
                ItemDTO(sku=i.sku, quantity=i.quantity, unit_price=i.unit_price.amount,
                        subtotal=i.subtotal.amount)
                for i in order.items
            ],
            events=[
                EventDTO(name=e.name, description=e.description, occurred_at=e.occurred_at.isoformat())
                for e in order.events
            ],
        )


class OrderSummaryDTO(BaseModel):
    id: str
    customer_id: str
    status: str
    units: int
    total: Decimal


class DiscountDTO(BaseModel):
    message: str
    order_id: str
    percent: Decimal
    rule: str
    subtotal: Decimal
    discount: Decimal
    total_with_discount: Decimal


class CreateOrderRequest(BaseModel):
    customer_id: str = Field(examples=["C001"])
    has_promotion: bool = False


class AddItemRequest(BaseModel):
    sku: str = Field(examples=["SKU003"])
    quantity: int = Field(examples=[2])


class ShipRequest(BaseModel):
    tracking_number: str | None = Field(default=None, examples=["GUIA-123456"])


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, examples=["El cliente ya no lo necesita"])


NOT_FOUND = {404: {"model": ErrorResponse, "description": "El pedido no existe"}}
TRANSITION_ERRORS = {
    **NOT_FOUND,
    409: {"model": ErrorResponse, "description": "Transición de estado no permitida"},
    422: {"model": ErrorResponse, "description": "Datos inválidos según las reglas del dominio"},
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/orders", response_model=list[OrderSummaryDTO], tags=["Consultas"])
def list_orders():
    return [
        OrderSummaryDTO(id=o.id, customer_id=o.customer.id, status=o.status.value,
                        units=o.units, total=o.total.amount)
        for o in service.list()
    ]


@app.get("/orders/{order_id}", response_model=OrderDTO, responses=NOT_FOUND, tags=["Consultas"])
def get_order(order_id: str):
    return OrderDTO.from_order(service.get(order_id))


@app.get("/orders/{order_id}/discount", response_model=DiscountDTO, responses=NOT_FOUND,
         tags=["Consultas"])
def get_discount(order_id: str):
    result = service.discount(order_id)
    if result.percent:
        message = (f"El pedido {order_id} tiene {result.percent} % de descuento: paga "
                   f"{result.total.amount} MXN en lugar de {result.subtotal.amount} MXN.")
    else:
        message = f"El pedido {order_id} no tiene descuento: paga {result.total.amount} MXN."
    return DiscountDTO(message=message, order_id=order_id, percent=result.percent, rule=result.rule,
                       subtotal=result.subtotal.amount, discount=result.discount.amount,
                       total_with_discount=result.total.amount)


@app.post("/orders", response_model=OrderDTO, status_code=201, tags=["Pedidos"],
          responses={422: {"model": ErrorResponse, "description": "Cliente inexistente"}})
def create_order(body: CreateOrderRequest):
    order = service.create(body.customer_id, body.has_promotion)
    return OrderDTO.from_order(order, f"Se creó el pedido {order.id} en borrador.")


@app.post("/orders/{order_id}/items", response_model=OrderDTO, responses=TRANSITION_ERRORS,
          tags=["Pedidos"])
def add_item(order_id: str, body: AddItemRequest):
    order = service.add_item(order_id, body.sku, body.quantity)
    return OrderDTO.from_order(order, f"Se agregaron {body.quantity} unidades de {body.sku} al pedido {order_id}.")


@app.post("/orders/{order_id}/confirm", response_model=OrderDTO, responses=TRANSITION_ERRORS,
          tags=["Transiciones"])
def confirm_order(order_id: str):
    return OrderDTO.from_order(service.confirm(order_id), f"El pedido {order_id} se confirmó correctamente.")


@app.post("/orders/{order_id}/ship", response_model=OrderDTO, responses=TRANSITION_ERRORS,
          tags=["Transiciones"])
def ship_order(order_id: str, body: ShipRequest):
    order = service.ship(order_id, body.tracking_number)
    return OrderDTO.from_order(order, f"El pedido {order_id} se envió con la guía {order.events[-1].detail}.")


@app.post("/orders/{order_id}/cancel", response_model=OrderDTO, responses=TRANSITION_ERRORS,
          tags=["Transiciones"])
def cancel_order(order_id: str, body: CancelRequest):
    return OrderDTO.from_order(service.cancel(order_id, body.reason), f"El pedido {order_id} se canceló correctamente.")


@app.post("/orders/{order_id}/deliver", response_model=OrderDTO, responses=TRANSITION_ERRORS,
          tags=["Transiciones"])
def deliver_order(order_id: str):
    return OrderDTO.from_order(service.deliver(order_id), f"El pedido {order_id} se marcó como entregado.")


@app.post("/orders/{order_id}/return", response_model=OrderDTO, responses=TRANSITION_ERRORS,
          tags=["Transiciones"])
def return_order(order_id: str):
    return OrderDTO.from_order(service.return_order(order_id), f"El pedido {order_id} se registró como devuelto.")


@app.post("/fixtures/reload", tags=["Utilidades"])
def reload_fixtures():
    return {"orders_loaded": reset_data()}
