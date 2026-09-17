"""El extractor universal saca NIT, municipio, periodo y total de CUALQUIER
borrador de ReteICA, sin conocer la estructura del formulario.

Es lo que permite que el motor no se rija a que le pasen todos los formatos:
con esos cuatro datos alcanza para el cruce declarado-vs-auxiliar, que es lo
que Robinson revisa a mano y funciona en cualquier municipio.

D9 sigue: la extraccion PROPONE, el auditor CONFIRMA. Cada dato viene con su
confianza para que el auditor sepa donde mirar. Un NIT de baja confianza es
casi peor que no tenerlo -- oculta que el motor adivino.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.ingesta.borrador_universal import leer_borrador_universal

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def terlica():
    """Santa Marta, formulario tipico con renglones y checkboxes de mes."""
    return leer_borrador_universal(BASE / "borrador.pdf")


def test_saca_el_nit_del_declarante_no_el_del_municipio(terlica):
    """El primer NIT del PDF suele ser el del municipio. Firmar el papel con
    ese seria el error de auditoria mas grave posible."""
    assert terlica.nit == "819002433"
    assert terlica.nit_confianza == "alta"


def test_reconoce_el_municipio_por_su_encabezado(terlica):
    """Santa Marta viene como DISTRITO DE, no MUNICIPIO DE."""
    assert terlica.municipio == "Santa Marta"


def test_no_se_come_declaracion_de_correccion(terlica):
    """El formulario dice 'DECLARACION DE CORRECCION' varias lineas abajo del
    encabezado del municipio. Un regex laxo tomaba CORRECCION como municipio."""
    assert "Correc" not in (terlica.municipio or "")


def test_lee_el_periodo_por_la_casilla_marcada(terlica):
    """Santa Marta usa checkboxes: ENE FEB MAR ABR MAY JUN JUL con casillas
    debajo. El X del JUL da el mes exacto."""
    assert terlica.periodo == "2026-07"
    assert terlica.periodo_confianza == "alta"


def test_saca_el_total_declarado(terlica):
    """474.000 -- lo que el auxiliar tiene que igualar."""
    assert terlica.total_declarado == Decimal("474000")
    assert terlica.total_confianza == "alta"


def test_una_ruta_que_no_existe_no_lanza():
    """El motor nunca puede caer por un archivo que no leyo bien."""
    ext = leer_borrador_universal(Path("no-existe.pdf"))
    assert ext.nit is None
    assert ext.municipio is None
    assert ext.total_declarado is None
