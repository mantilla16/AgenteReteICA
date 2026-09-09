from decimal import Decimal
from datetime import date

import pytest

from motor_reteica.tipos import Estado, Severidad, LineaAuxiliar, ResultadoControl, Excepcion
from motor_reteica.parametros.tolerancias import TOLERANCIAS


def test_estados_son_tres():
    assert {e.value for e in Estado} == {"OK", "FALLA", "NO EJECUTADO"}


def test_linea_auxiliar_exige_decimal():
    linea = LineaAuxiliar(
        cuenta="2368010010", nit="800193573", tercero="SUPER PORTUARIA S.A.S",
        fecha_documento=date(2026, 7, 27), fecha_contabilizacion=date(2026, 7, 31),
        referencia="250530", documento="5100013904",
        concepto="SERVICIOS DE OPERACION PORTUARIA", retencion=Decimal("18296"),
    )
    assert isinstance(linea.retencion, Decimal)


def test_linea_auxiliar_rechaza_float():
    with pytest.raises(TypeError):
        LineaAuxiliar(
            cuenta="2368010010", nit="800193573", tercero="X",
            fecha_documento=date(2026, 7, 27), fecha_contabilizacion=date(2026, 7, 31),
            referencia="250530", documento="5100013904", concepto="X",
            retencion=18296.0,
        )


def test_resultado_no_ejecutado_no_es_ok():
    r = ResultadoControl(codigo="C2", nombre="Balance vs auxiliar",
                         estado=Estado.NO_EJECUTADO, detalle="falta el balance")
    assert r.estado is not Estado.OK
    assert not r.paso


def test_severidades_disponibles():
    assert {s.value for s in Severidad} == {"HALLAZGO", "OBSERVACION", "AVISO"}


def test_excepcion_lleva_impacto_decimal():
    e = Excepcion(severidad=Severidad.OBSERVACION, control="C6",
                  descripcion="actividad 7112 vs 7490", renglon="7490")
    assert e.impacto_pesos == Decimal("0")
    assert isinstance(e.impacto_pesos, Decimal)


def test_tolerancias_son_decimal():
    assert TOLERANCIAS["redondeo_declaracion_pesos"] == Decimal("1000")
    assert isinstance(TOLERANCIAS["diferencia_maxima_cruce_pesos"], Decimal)
