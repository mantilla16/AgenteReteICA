"""M6: el codigo de salida del CLI refleja la CONCLUSION, no solo el impacto.

Antes devolvia 0 si impacto_total == 0, aunque hubiera controles NO EJECUTADO
y la conclusion dijera "NO limpia". Cualquier automatizacion que leyera el
codigo de salida entendia "todo bien".

Escala, de menos a mas grave:
  0  la revision puede concluir limpio
  1  ejecutada con excepciones (haya o no impacto en pesos)
  2  insumo obligatorio faltante, o C0 detuvo por identidad
  3  hay controles NO EJECUTADO -> la revision no es concluyente

3 pesa mas que 1: una excepcion encontrada es un resultado; un control sin
ejecutar es la ausencia de resultado, y eso impide concluir.
"""

import shutil
from pathlib import Path

import pytest

from motor_reteica import cli
from motor_reteica.hallazgos import consolidar
from motor_reteica.tipos import Estado

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"

_ARGS = ["--nit", "819002433", "--periodo", "2026-07"]


def _correr(tmp_path, carpeta=None, extra=()):
    """Nunca contra BASE: el CLI escribe la plantilla de atestacion en la
    carpeta que analiza, y las fixtures son de solo lectura."""
    if carpeta is None:
        carpeta = tmp_path / "copia"
        shutil.copytree(BASE, carpeta)
    return cli.main(["--carpeta", str(carpeta), *_ARGS,
                     "--salida", str(tmp_path / "papel.xlsx"), *extra])


def test_julio_2026_devuelve_3_porque_hay_controles_no_ejecutados(tmp_path):
    """C7 (sin Acuerdo municipal) y C12 (sin pago anterior) no se ejecutaron.

    Es el caso que motivo M6: antes devolvia 0 -- exito -- con la conclusion
    diciendo que la revision no era concluyente.
    """
    assert _correr(tmp_path) == 3


def test_el_3_pesa_mas_que_el_1_cuando_hay_ambos(tmp_path, capsys):
    """Julio tiene FALLA en C6/C11/C13 y NO EJECUTADO en C7/C12.

    Con las dos condiciones presentes debe ganar el 3: lo que impide concluir
    no es lo que se encontro, es lo que no se pudo mirar.
    """
    codigo = _correr(tmp_path)
    salida = capsys.readouterr().out
    assert "FALLA" in salida and "NO EJECUTADO" in salida
    assert codigo == 3


def test_sin_controles_no_ejecutados_pero_con_excepciones_devuelve_1(monkeypatch,
                                                                    tmp_path):
    """Si todo se ejecuto y quedaron excepciones, el codigo es 1, no 0.

    Se fuerza el escenario neutralizando los NO EJECUTADO del informe, sin
    tocar las cifras: lo que se prueba es la traduccion estado -> codigo.
    """
    real = cli.revisar

    def sin_no_ejecutados(*args, **kwargs):
        ctx = real(*args, **kwargs)
        for resultado in ctx.resultados:
            if resultado.estado is Estado.NO_EJECUTADO and resultado.aplica:
                object.__setattr__(resultado, "estado", Estado.OK)
        object.__setattr__(ctx, "informe", consolidar(ctx.resultados))
        return ctx

    monkeypatch.setattr(cli, "revisar", sin_no_ejecutados)
    assert _correr(tmp_path) == 1


def test_conclusion_limpia_devuelve_0(monkeypatch, tmp_path):
    """El 0 queda reservado para lo que de verdad es un exito."""
    real = cli.revisar

    def todo_ok(*args, **kwargs):
        ctx = real(*args, **kwargs)
        for resultado in ctx.resultados:
            if resultado.aplica:
                object.__setattr__(resultado, "estado", Estado.OK)
                object.__setattr__(resultado, "excepciones", ())
        object.__setattr__(ctx, "informe", consolidar(ctx.resultados))
        return ctx

    monkeypatch.setattr(cli, "revisar", todo_ok)
    assert _correr(tmp_path) == 0


def test_insumo_faltante_sigue_siendo_2(tmp_path):
    vacia = tmp_path / "sin_nada"
    vacia.mkdir()
    assert _correr(tmp_path, carpeta=vacia) == 2


def test_identidad_incompatible_sigue_siendo_2(tmp_path):
    copia = tmp_path / "copia"
    shutil.copytree(BASE, copia)
    codigo = cli.main(["--carpeta", str(copia), "--nit", "819002433",
                       "--periodo", "2026-06",
                       "--salida", str(tmp_path / "p.xlsx")])
    assert codigo == 2
