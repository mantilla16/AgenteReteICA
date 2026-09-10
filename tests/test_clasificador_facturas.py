"""V5: el extracto de SAP entraba al papel como si fuera una factura.

En la corrida real, S_ALR_87012277_...ICA_IVA.pdf -- que es el REPORTE DE
SALDOS DE SAP -- fue clasificado como factura porque el clasificador de la
API tomaba como factura TODO PDF que no fuera el borrador. C11 lo reporto
entonces como HALLAZGO: "la factura no aparece en el auxiliar".

El papel le imputaba al cliente una factura sin contabilizar que no existe.
Un PDF tiene que PARECER una factura para que se le trate como tal; si no se
puede determinar, va a sin clasificar y se le dice al auditor.
"""

from pathlib import Path

import pytest

from motor_reteica.api.servidor import _clasificar, _es_factura_pdf

CARPETA = Path(r"C:/Users/Felipe Ríos/Downloads/OneDrive_1_9-9-2026")

pytestmark = pytest.mark.skipif(
    not CARPETA.is_dir(),
    reason="requiere la carpeta real del cliente")


def test_el_extracto_de_sap_no_es_una_factura():
    assert not _es_factura_pdf(
        CARPETA / "S_ALR_87012277_03ICADA0920260811090007_ICA_IVA.pdf")


def test_las_facturas_de_verdad_si_lo_son():
    for nombre in ("250530.pdf", "FE10.pdf", "FE338057.pdf"):
        assert _es_factura_pdf(CARPETA / nombre), nombre


def test_el_clasificador_no_mete_el_extracto_entre_las_facturas():
    rutas = [CARPETA / n for n in (
        "BORRADOR RTE ICA JULIO 2026.pdf",
        "S_ALR_87012277_03ICADA0920260811090007_ICA_IVA.pdf",
        "250530.pdf", "FE10.pdf", "FE338057.pdf")]
    archivos, facturas, sin_clasificar, conflictos = _clasificar(rutas)

    assert archivos["borrador"] == "BORRADOR RTE ICA JULIO 2026.pdf"
    assert sorted(facturas) == ["250530.pdf", "FE10.pdf", "FE338057.pdf"]
    assert any("S_ALR" in n for n in sin_clasificar), \
        "el extracto de SAP debe quedar SIN CLASIFICAR, no como factura"
    assert conflictos == []
