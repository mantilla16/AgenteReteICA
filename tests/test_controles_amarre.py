from dataclasses import replace
from decimal import Decimal

from motor_reteica.controles import (c2_balance_vs_auxiliar, c3_auxiliar_vs_erp,
                                     c5_coherencia_cuenta_codigo)
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.tipos import Estado


def test_c2_cuadra(saldos, lineas):
    assert c2_balance_vs_auxiliar(saldos, lineas).estado is Estado.OK


def test_c2_sin_balance_es_no_ejecutado(lineas):
    r = c2_balance_vs_auxiliar(None, lineas)
    assert r.estado is Estado.NO_EJECUTADO
    assert r.estado is not Estado.OK


def test_c2_detecta_descuadre(saldos, lineas):
    alterado = dict(saldos)
    alterado["2368010010"] = Decimal("438000")
    r = c2_balance_vs_auxiliar(alterado, lineas)
    assert r.estado is Estado.FALLA
    assert len(r.excepciones) == 1
    assert r.excepciones[0].impacto_pesos == Decimal("243")


def test_c3_cuadra_por_tercero(lineas, erp):
    assert c3_auxiliar_vs_erp(lineas, erp).estado is Estado.OK


def test_c3_sin_erp_es_no_ejecutado(lineas):
    assert c3_auxiliar_vs_erp(lineas, None).estado is Estado.NO_EJECUTADO


def test_c3_detecta_tercero_faltante_en_el_erp(lineas, erp):
    r = c3_auxiliar_vs_erp(lineas, [f for f in erp if f.nit != "830028245"])
    assert r.estado is Estado.FALLA


def test_c5_coherencia_cuenta_codigo(lineas, erp):
    assert c5_coherencia_cuenta_codigo(lineas, erp, MUNICIPIO).estado is Estado.OK


def test_c5_detecta_cuenta_con_tarifa_incoherente(lineas, erp):
    """Una linea de 10 por mil movida a la cuenta de 7 por mil."""
    alteradas = [replace(l, cuenta="2368010007") if l.referencia == "250530" else l
                 for l in lineas]
    assert c5_coherencia_cuenta_codigo(alteradas, erp, MUNICIPIO).estado is Estado.FALLA


def test_c5_sin_erp_es_no_ejecutado(lineas):
    assert c5_coherencia_cuenta_codigo(lineas, None, MUNICIPIO).estado is Estado.NO_EJECUTADO
