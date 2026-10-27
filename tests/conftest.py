import pytest

from cargar_csv import load_fixture


@pytest.fixture
def orders():
    """Carga nueva de los 16 pedidos para cada prueba (ningún caso afecta a otro)."""
    return load_fixture()
