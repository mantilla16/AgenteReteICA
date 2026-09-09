"""Validacion extremo a extremo contra las anclas del spec (seccion 10.1)."""

from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.tipos import Estado

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


def _estado(ctx, codigo):
    return next(r for r in ctx.resultados if r.codigo == codigo).estado


def test_ancla_auxiliar_igual_erp(ctx):
    assert ctx.total_auxiliar == Decimal("474561")
    assert ctx.total_erp == Decimal("474561")


def test_ancla_base_gravable(ctx):
    assert ctx.reconstruccion.total_base == Decimal("49012569")


def test_ancla_impuesto_declarado_y_cinco_renglones(ctx):
    assert ctx.borrador.renglones["24"] == Decimal("474000")
    assert len(ctx.borrador.actividades) == 5
    assert len(ctx.reconstruccion.por_actividad) == 5


def test_ancla_detalle_por_renglon(ctx):
    esperado = {
        "9609": (Decimal("188341"), Decimal("1318")),
        "7490": (Decimal("5000000"), Decimal("35000")),
        "4669": (Decimal("3742993"), Decimal("37430")),
        "5224": (Decimal("38965609"), Decimal("389657")),
        "9903": (Decimal("1115626"), Decimal("11156")),
    }
    for codigo, (base, impuesto) in esperado.items():
        renglon = ctx.reconstruccion.por_actividad[codigo]
        assert renglon.base_contable == base
        assert renglon.impuesto_contable == impuesto


def test_ancla_impuesto_declarable(ctx):
    assert ctx.reconstruccion.total_impuesto_contable == Decimal("474561")
    assert ctx.reconstruccion.total_impuesto_declarable == Decimal("474000")


def test_c9_terminal_sin_diferencias(ctx):
    assert _estado(ctx, "C9") is Estado.OK


def test_los_amarres_contables_cuadran(ctx):
    for codigo in ("C0", "C1", "C2", "C3", "C4", "C5", "C8", "C10"):
        assert _estado(ctx, codigo) is Estado.OK, codigo


def test_la_revision_no_concluye_limpia(ctx):
    """C7 sin Acuerdo municipal y C12 sin pago anterior lo impiden."""
    assert ctx.informe.puede_concluir_limpio is False
    assert "C7" in ctx.informe.controles_no_ejecutados
    assert "C12" in ctx.informe.controles_no_ejecutados


def test_no_hay_hallazgos_con_impacto_en_pesos(ctx):
    assert ctx.informe.impacto_total == Decimal("0")


def test_se_registran_las_huellas_de_las_fuentes(ctx):
    assert set(ctx.huellas) >= {"auxiliar", "balance", "borrador", "erp"}
    assert all(len(h) == 64 for h in ctx.huellas.values())


def test_el_mapa_de_actividades_cubre_los_cinco_terceros(ctx):
    assert len(ctx.reconstruccion.por_tercero) == 5
