# TechStore U4 — Núcleo de negocio de pedidos

**Materia:** Componentes de Lógica de Negocio · FIME UANL
**Actividad 4:** Laboratorio guiado — programa para administrar pedidos
**Profesor:** Miguel Ángel Gómez Marroquín
**Equipo 12:**

| Integrante | Matrícula |
|---|---|
| Roberto Carlos Sánchez Flores | 2151262 |
| Donovan Adrian Serrato Lores | 2154304 |
| Laura Sofía Vargas Ramírez | 2152053 |

Programa que lee clientes, productos y pedidos de archivos CSV, los convierte en objetos del dominio, aplica reglas de descuento con **Specification Pattern**, controla el ciclo de vida de cada pedido con una **máquina de estados** que registra **Domain Events** y expone las operaciones mediante una **API REST con FastAPI**. Los datos viven en memoria: al cerrar el programa los cambios se pierden.

## Requisitos

- Python 3.11 o superior (probado con Python 3.13)
- FastAPI, Uvicorn, pytest y httpx

## Instalación

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows CMD
.venv\Scripts\activate.bat
# macOS / Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
```

## Ejecución

| Qué | Comando |
|---|---|
| Cargar los 16 pedidos de los CSV | `python cargar_csv.py` |
| Ejecutar los escenarios E01–E15 (una línea por caso) | `python ejecutar_escenarios.py` |
| Correr las pruebas | `python -m pytest -v` |
| Levantar la API | `uvicorn app.api:app --reload` |
| Documentación Swagger | http://127.0.0.1:8000/docs |
| Contrato OpenAPI | http://127.0.0.1:8000/openapi.json |

## Estructura

```
techstore-u4/
├── datos/                  ← 5 CSV del paquete del alumno (sin modificar)
├── cargar_csv.py           ← cargador del paquete (sin modificar)
├── ejecutar_escenarios.py  ← ejecuta E01–E15 y compara con escenarios.csv
├── app/
│   ├── domain.py           ← Money, Customer, OrderItem, Order, estados, eventos, excepciones
│   ├── specifications.py   ← Specifications, AND/OR/NOT y reglas de descuento
│   ├── services.py         ← Application Service y repositorio en memoria
│   └── api.py              ← endpoints FastAPI y traducción de excepciones a HTTP
├── tests/                  ← pruebas pytest (dominio, specifications, escenarios y API)
└── docs/                   ← diagrama de estados y evidencias
```

Las dependencias van de afuera hacia adentro: `api → services → domain`. El dominio no conoce FastAPI ni los CSV.

## Reglas de negocio

| Regla | Dónde se protege |
|---|---|
| `Money` usa `Decimal`, no admite negativos ni `float`; solo suma la misma moneda | `Money.__post_init__`, `Money.add` |
| `OrderItem` exige SKU y cantidad entera mayor que cero; el subtotal se calcula | `OrderItem.__post_init__`, `OrderItem.subtotal` |
| Máximo **20 unidades** por pedido (suma de cantidades, no renglones) | `Order.add_item` |
| Solo un pedido `DRAFT` admite artículos | `Order.add_item` |
| Confirmar exige `DRAFT`, al menos un artículo y cliente activo | `Order.confirm` |
| Enviar exige `CONFIRMED` y número de guía no vacío | `Order.ship` |
| Cancelar exige `CONFIRMED` y motivo no vacío | `Order.cancel` |
| Entregar y devolver exigen `SHIPPED` | `Order.deliver`, `Order.return_order` |
| Descuento 10 %: VIP **y** total > 500 **y** ≥ 4 unidades **y no** promoción | `TEN_PERCENT_RULE` |
| Descuento 5 %: total > 5000 **y no** promoción | `FIVE_PERCENT_RULE` |
| Si se cumplen ambas, prioridad 10 % | `evaluate_discount` |

El stock de `productos.csv` es solo información del catálogo: no se descuenta inventario.

## Máquina de estados y eventos

```
DRAFT --confirm--> CONFIRMED --ship--> SHIPPED --deliver--> DELIVERED
                       |                  |
                     cancel             return
                       |                  |
                   CANCELLED           RETURNED
```

| Transición | Evento |
|---|---|
| `confirm()` | `OrderConfirmed` |
| `ship(tracking_number)` | `OrderShipped` |
| `cancel(reason)` | `OrderCancelled` |
| `deliver()` | `OrderDelivered` |
| `return_order()` | `OrderReturned` |

Cada método valida primero, cambia el estado después y registra el evento al final. Una operación rechazada no cambia el estado ni agrega eventos. Diagrama: [`docs/diagrama-estados.png`](docs/diagrama-estados.png).

## Endpoints

| Método | Ruta | Descripción | Respuestas |
|---|---|---|---|
| GET | `/orders` | Lista los pedidos | 200 |
| GET | `/orders/{order_id}` | Detalle con artículos y eventos | 200, 404 |
| GET | `/orders/{order_id}/discount` | Descuento aplicable (no modifica el pedido) | 200, 404 |
| POST | `/orders` | Crea un pedido en `DRAFT` | 201, 422 |
| POST | `/orders/{order_id}/items` | Agrega un artículo del catálogo | 200, 404, 409, 422 |
| POST | `/orders/{order_id}/confirm` | Confirma | 200, 404, 409, 422 |
| POST | `/orders/{order_id}/ship` | Envía (body: `tracking_number`) | 200, 404, 409, 422 |
| POST | `/orders/{order_id}/cancel` | Cancela (body: `reason`) | 200, 404, 409, 422 |
| POST | `/orders/{order_id}/deliver` | Entrega | 200, 404, 409 |
| POST | `/orders/{order_id}/return` | Devuelve | 200, 404, 409 |
| POST | `/fixtures/reload` | Vuelve a cargar los CSV | 200 |

| Código | Excepción del dominio |
|---|---|
| 404 | `OrderNotFound` — el pedido no existe |
| 409 | `InvalidOrderTransition` — transición no permitida |
| 422 | `InvalidOrderData`, `OrderItemLimitExceeded` — datos inválidos |

Las respuestas exitosas traen un campo `message` para el usuario (por ejemplo, *"El pedido O013 se confirmó correctamente."*). Los errores traen `detail`, con un mensaje claro (*"Este pedido ya fue confirmado; no se puede confirmar otra vez."*), y `error`, con el nombre técnico de la excepción del dominio.

## Escenarios E01–E15

| Caso | Pedido | Operación | Resultado |
|---|---|---|---|
| E01 | O001 | Evaluar descuento | 10 % |
| E02 | O002 | Evaluar descuento | 0 % |
| E03 | O003 | Confirmar | Rechazo: cliente inactivo |
| E04 | O005 | Evaluar descuento | 0 %: promoción activa |
| E05 | O006 | Evaluar descuento | 5 % |
| E06 | O007 | Confirmar | Rechazo: pedido sin artículos |
| E07 | O008 | Confirmar | Éxito con 20 unidades |
| E08 | O009 | Agregar SKU003 x2 | Rechazo: 21 unidades |
| E09 | O010 | Evaluar descuento | 0 %: total exactamente 500 |
| E10 | O011 | Evaluar descuento | 0 %: solo 3 unidades |
| E11 | O012 | Confirmar y enviar sin guía | Rechazo del envío |
| E12 | O013 | Confirmar dos veces | Rechazo de la segunda |
| E13 | O014 | Confirmar, enviar y cancelar | Rechazo de la cancelación |
| E14 | O015 | Confirmar, enviar y devolver | Éxito: `RETURNED` |
| E15 | O016 | Confirmar, enviar y entregar | Éxito: `DELIVERED` |

La bitácora completa (precondiciones, operación, resultado, evento y prueba) está en el reporte. Cada caso tiene su prueba en `tests/test_escenarios.py`.
