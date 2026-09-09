from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.identidad import (verificar_identidad, verificar_tipo_documento,
                                     huella, IdentidadIncompatible)
from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.borrador_pdf import leer_borrador
from motor_reteica.tipos import Estado, LineaAuxiliar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
BORRADOR = leer_borrador(BASE / "borrador.pdf")
LINEAS = leer_auxiliar(BASE / "auxiliar_2368.xlsx")


def test_identidad_coincide():
    assert verificar_identidad(BORRADOR, LINEAS, "819002433", "2026-07").estado is Estado.OK


def test_periodo_distinto_detiene_el_proceso():
    with pytest.raises(IdentidadIncompatible):
        verificar_identidad(BORRADOR, LINEAS, "819002433", "2026-06")


def test_nit_distinto_detiene_el_proceso():
    with pytest.raises(IdentidadIncompatible):
        verificar_identidad(BORRADOR, LINEAS, "900000000", "2026-07")


def test_auxiliar_fuera_de_periodo_detiene_el_proceso():
    intrusa = LineaAuxiliar(
        cuenta="2368010010", nit="800193573", tercero="X",
        fecha_documento=date(2026, 5, 1), fecha_contabilizacion=date(2026, 5, 31),
        referencia="X", documento="X", concepto="X", retencion=Decimal("100"),
    )
    with pytest.raises(IdentidadIncompatible):
        verificar_identidad(BORRADOR, list(LINEAS) + [intrusa], "819002433", "2026-07")


def test_el_detalle_deja_constancia_de_la_identidad():
    r = verificar_identidad(BORRADOR, LINEAS, "819002433", "2026-07")
    assert "819002433" in r.detalle and "2026-07" in r.detalle


def test_huella_es_estable_y_sha256():
    h1 = huella(BASE / "auxiliar_2368.xlsx")
    h2 = huella(BASE / "auxiliar_2368.xlsx")
    assert h1 == h2 and len(h1) == 64


def test_huella_distingue_archivos():
    assert huella(BASE / "auxiliar_2368.xlsx") != huella(BASE / "balance.xlsx")


# --------------------------------------------------------------------------
# 1.5 - C0 verifica tipo de documento
# --------------------------------------------------------------------------

def test_tipo_de_documento_correcto_no_lanza_nada():
    verificar_tipo_documento("auxiliar", BASE / "auxiliar_2368.xlsx")
    verificar_tipo_documento("balance", BASE / "balance.xlsx")
    verificar_tipo_documento("erp", BASE / "sap_retenciones.xlsx")


def test_declarar_el_balance_en_el_rol_del_auxiliar_se_detiene():
    """Antes: el motor lo cargaba igual y reventaba mas adelante."""
    with pytest.raises(IdentidadIncompatible, match="balance"):
        verificar_tipo_documento("auxiliar", BASE / "balance.xlsx")


def test_declarar_el_erp_en_el_rol_del_balance_se_detiene():
    with pytest.raises(IdentidadIncompatible, match="erp"):
        verificar_tipo_documento("balance", BASE / "sap_retenciones.xlsx")


def test_el_borrador_y_las_facturas_no_tienen_esta_verificacion():
    """El PDF no tiene firma tabular: verificar_tipo_documento no interviene."""
    verificar_tipo_documento("borrador", BASE / "borrador.pdf")
    verificar_tipo_documento("facturas", BASE / "facturas" / "FE10.pdf")
