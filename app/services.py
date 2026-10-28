"""Application Service y repositorio en memoria.

El Application Service coordina cada caso de uso: obtiene el pedido del
repositorio, llama al método del dominio y lo guarda. No contiene reglas de
negocio; esas viven en Order y en las Specifications.
"""
from decimal import Decimal

from app.domain import Customer, DomainException, Money, Order, OrderItem
from app.specifications import DiscountResult, evaluate_discount


class OrderNotFound(Exception):
    """El pedido solicitado no existe en el repositorio (no es una regla de negocio)."""

    def __init__(self, order_id: str):
        super().__init__(f"No encontramos el pedido {order_id}. Revisa que el número sea correcto.")


class CatalogNotFound(DomainException):
    """El cliente o producto referenciado no existe en el catálogo."""


class InMemoryOrderRepository:
    """Repositorio en memoria: los cambios se pierden al cerrar el programa."""

    def __init__(self, orders: dict[str, Order] | None = None):
        self._orders: dict[str, Order] = dict(orders or {})

    def get(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFound(order_id)
        return order

    def list(self) -> list[Order]:
        return list(self._orders.values())

    def save(self, order: Order) -> None:
        self._orders[order.id] = order

    def next_id(self) -> str:
        numbers = [int(k[1:]) for k in self._orders if k[:1] == "O" and k[1:].isdigit()]
        return f"O{(max(numbers) + 1) if numbers else 1:03d}"


class OrderService:
    def __init__(
        self,
        repository: InMemoryOrderRepository,
        customers: dict[str, Customer],
        prices: dict[str, Decimal],
    ):
        self.repository = repository
        self.customers = customers
        self.prices = prices

    # ----- consultas -------------------------------------------------------
    def get(self, order_id: str) -> Order:
        return self.repository.get(order_id)

    def list(self) -> list[Order]:
        return self.repository.list()

    def discount(self, order_id: str) -> DiscountResult:
        return evaluate_discount(self.repository.get(order_id))

    # ----- comandos --------------------------------------------------------
    def create(self, customer_id: str, has_promotion: bool = False) -> Order:
        customer = self.customers.get(customer_id)
        if customer is None:
            raise CatalogNotFound(f"No existe el cliente {customer_id} en el catálogo.")
        order = Order(customer=customer, id=self.repository.next_id(), has_promotion=has_promotion)
        self.repository.save(order)
        return order

    def add_item(self, order_id: str, sku: str, quantity: int) -> Order:
        order = self.repository.get(order_id)
        price = self.prices.get(sku)
        if price is None:
            raise CatalogNotFound(f"No existe el producto {sku} en el catálogo.")
        order.add_item(OrderItem(sku, quantity, Money(price)))
        self.repository.save(order)
        return order

    def confirm(self, order_id: str) -> Order:
        return self._run(order_id, lambda o: o.confirm())

    def ship(self, order_id: str, tracking_number: str | None) -> Order:
        return self._run(order_id, lambda o: o.ship(tracking_number))

    def cancel(self, order_id: str, reason: str | None) -> Order:
        return self._run(order_id, lambda o: o.cancel(reason))

    def deliver(self, order_id: str) -> Order:
        return self._run(order_id, lambda o: o.deliver())

    def return_order(self, order_id: str) -> Order:
        return self._run(order_id, lambda o: o.return_order())

    def _run(self, order_id: str, operation) -> Order:
        order = self.repository.get(order_id)
        operation(order)  # el dominio valida; si falla, lanza la excepción y no se guarda
        self.repository.save(order)
        return order
