"""M7(b)(c): el papel dice que version del motor lo genero.

El papel ya registra el SHA-256 de las cuatro fuentes, pero no el del programa
que las proceso. Un papel de trabajo firmado que no se puede reproducir es la
critica mas facil de hacer contra el producto.
"""

import re
from pathlib import Path

import openpyxl
import pytest

import motor_reteica
from motor_reteica.papel_excel import generar_papel
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.version import huella_del_codigo, sello

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def caratula(tmp_path_factory):
    ctx = revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    salida = tmp_path_factory.mktemp("papel") / "p.xlsx"
    generar_papel(salida, ctx)
    hoja = openpyxl.load_workbook(salida)["Caratula"]
    return [[c for c in fila if c is not None]
            for fila in hoja.iter_rows(values_only=True)]


def _valor(caratula, etiqueta):
    for fila in caratula:
        if fila and str(fila[0]).strip() == etiqueta:
            return str(fila[1])
    raise AssertionError("no esta la fila %r en la caratula" % etiqueta)


def test_el_motor_declara_una_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", motor_reteica.__version__)


def test_la_caratula_estampa_la_version_del_motor(caratula):
    assert _valor(caratula, "VERSION DEL MOTOR") == motor_reteica.__version__


def test_la_caratula_estampa_la_huella_del_codigo(caratula):
    """Sin git disponible la huella no puede quedar vacia ni inventada."""
    valor = _valor(caratula, "HUELLA DEL CODIGO")
    assert valor
    assert valor == huella_del_codigo()


def test_la_huella_dice_si_hay_cambios_sin_commitear():
    """Un papel generado con el arbol sucio no es reproducible y debe decirlo."""
    huella = huella_del_codigo()
    assert re.fullmatch(r"[0-9a-f]{7,40}(\+sucio)?|sin-git", huella), huella


def test_el_sello_junta_version_y_huella():
    assert sello() == "%s (%s)" % (motor_reteica.__version__,
                                   huella_del_codigo())
