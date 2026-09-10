import shutil
from pathlib import Path

import pytest

from motor_reteica import cli
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.revision_ia import aplicar_revision, construir_prompt

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


def test_el_prompt_incluye_controles_y_excepciones(ctx):
    prompt = construir_prompt(ctx)
    assert "C7" in prompt and "7112" in prompt


def test_el_prompt_prohibe_calcular(ctx):
    assert "no calcules" in construir_prompt(ctx).lower()


def test_el_prompt_incluye_las_lineas_para_juzgar_clasificacion(ctx):
    prompt = construir_prompt(ctx)
    assert "FE338043" in prompt and "REPARACION" in prompt


def test_la_revision_no_puede_alterar_cifras(ctx):
    antes = ctx.informe.impacto_total
    estados = [r.estado for r in ctx.resultados]
    aplicar_revision(ctx, '[{"control":"C6","comentario":"x","sugerencia":"y"}]')
    assert ctx.informe.impacto_total == antes
    assert [r.estado for r in ctx.resultados] == estados


def test_la_revision_produce_comentarios_no_estados(ctx):
    comentarios = aplicar_revision(
        ctx, '[{"control":"C6","comentario":"x","sugerencia":"y"}]')
    assert len(comentarios) == 1
    assert not hasattr(comentarios[0], "estado")


def test_una_respuesta_invalida_no_revienta(ctx):
    assert aplicar_revision(ctx, "no soy json") == []
    assert aplicar_revision(ctx, '{"no":"es lista"}') == []


def test_el_cli_corre_extremo_a_extremo(tmp_path, capsys):
    salida = tmp_path / "papel.xlsx"
    copia = tmp_path / "copia"
    shutil.copytree(BASE, copia)
    codigo = cli.main(["--carpeta", str(copia), "--nit", "819002433",
                       "--periodo", "2026-07", "--salida", str(salida)])
    impreso = capsys.readouterr().out
    # M6: antes esperaba 0 y esa era justamente la mentira. La corrida imprime
    # "Conclusion limpia: NO" -- con C7 y C12 sin ejecutar -- asi que el codigo
    # de salida tiene que decir lo mismo: 3, no concluyente.
    assert codigo == cli.NO_CONCLUYENTE
    assert codigo != 0, "un exit 0 contradiria la conclusion impresa"
    assert salida.exists()
    assert "474561" in impreso
    assert "Conclusion limpia: NO" in impreso


def test_el_cli_se_detiene_con_periodo_equivocado(tmp_path, capsys):
    copia = tmp_path / "copia"
    shutil.copytree(BASE, copia)
    codigo = cli.main(["--carpeta", str(copia), "--nit", "819002433",
                       "--periodo", "2026-06",
                       "--salida", str(tmp_path / "p.xlsx")])
    assert codigo == 2
    assert "DETUVO LA REVISION" in capsys.readouterr().err
