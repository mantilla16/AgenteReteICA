"""C15: el borrador contra el registro historico del propio cliente.

Se separo de C12 a proposito: C12 verifica el PAGO del mes anterior y sin el
comprobante no se puede ejecutar. Si las dos cosas vivieran en un mismo
control, la parte ejecutable lo pondria en OK y taparia que el pago nunca se
miro.
"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.controles import c15_formato_historico
from motor_reteica.ingesta.formato_historico import (PeriodoHistorico,
                                                     normalizar_periodo,
                                                     periodo_anterior)
from motor_reteica.ingesta.borrador_pdf import leer_borrador
from motor_reteica.tipos import Estado, Severidad

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def borrador():
    return leer_borrador(BASE / "borrador.pdf")


@pytest.fixture
def historico():
    """Lo que el formato real del cliente trae para julio 2026."""
    return {"2026-07": PeriodoHistorico(
        periodo="2026-07", base_declarada=Decimal("49013000"),
        retenciones_declaradas=Decimal("474000"), hoja="2026-07")}


# --------------------------------------------------------------------------
# La trampa del formato: nombres de hoja sucios
# --------------------------------------------------------------------------

@pytest.mark.parametrize("crudo,esperado", [
    ("2026-07", "2026-07"),
    ("2026- 3", "2026-03"),
    ("2026 - 4", "2026-04"),
    ("2026 - 05", "2026-05"),
    ("2026-02 ", "2026-02"),
    ("Hoja1", None),
    ("CUADRO RETEICA", None),
])
def test_los_nombres_de_hoja_sucios_se_normalizan(crudo, esperado):
    assert normalizar_periodo(crudo) == esperado


def test_periodo_anterior_cruza_el_ano():
    assert periodo_anterior("2026-07") == "2026-06"
    assert periodo_anterior("2026-01") == "2025-12"


# --------------------------------------------------------------------------
# El control
# --------------------------------------------------------------------------

def test_julio_coincide_con_el_formato_del_cliente(borrador, historico):
    resultado = c15_formato_historico(borrador, historico, "2026-07")
    assert resultado.estado is Estado.OK


def test_mutacion_el_formato_dice_otra_retencion(borrador, historico):
    """Dos versiones de la misma declaracion: hallazgo con impacto."""
    historico["2026-07"] = replace(historico["2026-07"],
                                   retenciones_declaradas=Decimal("500000"))
    resultado = c15_formato_historico(borrador, historico, "2026-07")
    assert resultado.estado is Estado.FALLA
    excepcion = next(e for e in resultado.excepciones
                     if "retenciones" in e.descripcion)
    assert excepcion.severidad is Severidad.HALLAZGO
    assert excepcion.impacto_pesos == Decimal("26000")


def test_mutacion_el_formato_dice_otra_base(borrador, historico):
    historico["2026-07"] = replace(historico["2026-07"],
                                   base_declarada=Decimal("50000000"))
    resultado = c15_formato_historico(borrador, historico, "2026-07")
    assert resultado.estado is Estado.FALLA
    assert any("base" in e.descripcion for e in resultado.excepciones)


def test_sin_formato_es_no_ejecutado(borrador):
    assert c15_formato_historico(borrador, {}, "2026-07").estado \
        is Estado.NO_EJECUTADO


def test_sin_hoja_del_periodo_es_no_ejecutado_y_dice_cuales_hay(borrador,
                                                                historico):
    resultado = c15_formato_historico(borrador, historico, "2026-08")
    assert resultado.estado is Estado.NO_EJECUTADO
    assert "2026-07" in resultado.detalle


def test_c15_no_puede_tapar_a_c12(borrador, historico):
    """C15 en OK no dice nada sobre el pago: son controles distintos."""
    resultado = c15_formato_historico(borrador, historico, "2026-07")
    assert "pago" not in resultado.detalle.lower()
