"""M13 - Excepcion.tipo_referencia.

`renglon` trae valores de tres naturalezas distintas segun el control:
cuenta contable, NIT o renglon real del formulario. Renombrar el campo
tocaria cada control y cada consumidor por una ganancia cosmetica, asi que
se agrego `tipo_referencia` de forma ADITIVA: no cambia lo que ya habia en
`renglon`, solo lo etiqueta.
"""

from pathlib import Path

import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.tipos import REF_CUENTA, REF_NIT, REF_RENGLON

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


def _excepciones(ctx, control):
    return [e for e in ctx.informe.excepciones_ordenadas if e.control == control]


def test_c6_etiqueta_sus_excepciones_como_renglon(ctx):
    excs = _excepciones(ctx, "C6")
    assert excs, "julio 2026 siempre trae excepciones de C6"
    assert all(e.tipo_referencia == REF_RENGLON for e in excs)


def test_c11_etiqueta_sus_excepciones_de_cuenta_como_cuenta(ctx):
    """C11 trae excepciones sin renglon (NIT no legible) y con cuenta
    (fecha, base): solo estas ultimas deben llevar el tipo."""
    excs = _excepciones(ctx, "C11")
    assert excs
    con_referencia = [e for e in excs if e.renglon]
    assert con_referencia
    assert all(e.tipo_referencia == REF_CUENTA for e in con_referencia)


def test_c13_etiqueta_la_excepcion_de_cuenta_candidata(ctx):
    """Solo dispara si hay una candidata a contrapartida sin declarar; si no
    la hay en julio 2026, la prueba no exige nada mas."""
    excs = [e for e in _excepciones(ctx, "C13") if e.tipo_referencia]
    for e in excs:
        assert e.tipo_referencia == REF_CUENTA


def test_todas_las_excepciones_con_renglon_no_vacio_declaran_su_tipo(ctx):
    """Ninguna excepcion deja `renglon` con un valor sin decir de que tipo
    es -- esa es la sobrecarga original de M13."""
    huerfanas = [e for e in ctx.informe.excepciones_ordenadas
                if e.renglon and not e.tipo_referencia]
    assert huerfanas == [], [(e.control, e.renglon) for e in huerfanas]


def test_los_tres_tipos_conocidos_son_los_unicos_en_uso(ctx):
    tipos = {e.tipo_referencia for e in ctx.informe.excepciones_ordenadas}
    assert tipos <= {REF_CUENTA, REF_NIT, REF_RENGLON, ""}
