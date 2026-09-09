from datetime import date
from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta.auxiliar import leer_auxiliar

FIXTURE = Path(__file__).parent / "fixtures" / "terlica_202607" / "auxiliar_2368.xlsx"


def test_lee_doce_lineas():
    assert len(leer_auxiliar(FIXTURE)) == 12


def test_total_es_el_ancla():
    assert sum(l.retencion for l in leer_auxiliar(FIXTURE)) == Decimal("474561")


def test_importes_se_normalizan_a_positivo():
    assert all(l.retencion > 0 for l in leer_auxiliar(FIXTURE))


def test_descarta_filas_de_totales():
    assert all(l.cuenta.startswith("2368") for l in leer_auxiliar(FIXTURE))


def test_nit_y_nombre_no_estan_invertidos():
    """Asignacion trae el NIT y Tercero el nombre, no al reves."""
    linea = next(l for l in leer_auxiliar(FIXTURE) if l.referencia == "FE10")
    assert linea.nit == "901670478"
    assert linea.tercero == "JACH DESIGNS S.A.S."


def test_parsea_las_fechas():
    """El auxiliar registra FE10 con fecha de documento 01.07.2026.

    La factura fisica es del 26/06/2026: ese desfase NO es visible desde el
    auxiliar y solo lo puede detectar C11 al cotejar contra el PDF. C8, que
    solo mira el auxiliar, vera todas las lineas dentro de julio.
    """
    fe10 = next(l for l in leer_auxiliar(FIXTURE) if l.referencia == "FE10")
    assert fe10.fecha_documento == date(2026, 7, 1)
    assert fe10.fecha_contabilizacion == date(2026, 7, 1)


def test_ninguna_linea_del_auxiliar_esta_fuera_de_julio():
    """Confirma que C8 sobre el auxiliar no puede disparar en este periodo."""
    for linea in leer_auxiliar(FIXTURE):
        assert (linea.fecha_contabilizacion.year,
                linea.fecha_contabilizacion.month) == (2026, 7)


def test_conserva_las_dos_lineas_del_mismo_tercero():
    """CDEM tiene dos facturas de distinta naturaleza; agregarlas las oculta."""
    cdem = [l for l in leer_auxiliar(FIXTURE) if l.nit == "811033997"]
    assert len(cdem) == 2
    assert {l.referencia for l in cdem} == {"FE338057", "FE338043"}
    assert sum(l.retencion for l in cdem) == Decimal("37430")


def test_conserva_el_concepto_para_clasificar():
    cdem = {l.referencia: l.concepto for l in leer_auxiliar(FIXTURE) if l.nit == "811033997"}
    assert "COMPRA" in cdem["FE338057"]
    assert "REPARACION" in cdem["FE338043"]


def test_retenciones_son_decimal():
    assert all(isinstance(l.retencion, Decimal) for l in leer_auxiliar(FIXTURE))
