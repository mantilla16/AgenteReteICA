"""El clasificador reconoce borradores de CUALQUIER municipio, no solo Santa Marta.

Bug real reportado por el auditor: el borrador de San Alberto quedaba como
'sin clasificar' en el tablero. Causa: la funcion _es_borrador_pdf usaba el
extractor de Santa Marta como criterio, y cualquier formato distinto fallaba.

Y el arreglo trajo su propia trampa: sin exclusion, las facturas caian como
borrador porque en su seccion de impuestos tambien dicen 'retencion'. Se
distingue por marcas fuertes que solo trae el formulario oficial.
"""

from pathlib import Path

import pytest

from motor_reteica.api.servidor import _es_borrador_pdf, _es_factura_pdf

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
INSUMOS = Path(
    r"C:\Users\manti\Desktop\Proyectos\Automatizacion impuestos"
    r"\Grupo Daabon\Insumos")


def test_reconoce_el_borrador_de_santa_marta():
    assert _es_borrador_pdf(BASE / "borrador.pdf")


@pytest.mark.skipif(not (INSUMOS / "BORRADOR RTE ICA JULIO 2026.pdf").exists(),
                    reason="requiere el PDF de San Alberto en Insumos/")
def test_reconoce_el_borrador_de_san_alberto():
    """El bug reportado: 'no reconocio: BORRADOR RETEICA ... .pdf'."""
    assert _es_borrador_pdf(INSUMOS / "BORRADOR RTE ICA JULIO 2026.pdf")


@pytest.mark.parametrize("factura", ["FE10.pdf", "250530.pdf", "FE338057.pdf"])
def test_las_facturas_no_caen_como_borrador(factura):
    """La factura 250530 caia como borrador porque tambien dice 'retencion'.
    Un mal clasificado ahi hace que dos archivos parezcan ser el borrador y
    el motor rechace el encargo entero."""
    ruta = BASE / "facturas" / factura
    assert _es_factura_pdf(ruta), "sigue siendo factura"
    assert not _es_borrador_pdf(ruta), "no puede ser borrador tambien"
