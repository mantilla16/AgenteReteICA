"""D2 sin cablear: el motor nunca escribia la plantilla de atestacion.

X1 decidio que el auditor entra como testigo de las tarifas, y D2 que el
motor "falla con mensaje util y ESCRIBE UNA PLANTILLA con el rol faltante
marcado; el auditor la completa y reejecuta". La funcion plantilla() existia
desde el principio y no la llamaba nadie: en la practica habia que redactar
atestacion.json a mano, y por eso NADIE ha atestado nunca.

Solo se pide lo que el borrador declara -- 5 actividades en julio, no las 453
de la norma. Atestar 5 tarifas es trabajo de minutos.
"""

import json
import shutil
from pathlib import Path

import pytest

from motor_reteica.atestacion import NOMBRE_ARCHIVO, leer_atestacion
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.tipos import Estado

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
PLANTILLA_ATESTACION = "atestacion.plantilla.json"


@pytest.fixture
def carpeta(tmp_path):
    destino = tmp_path / "corrida"
    shutil.copytree(BASE, destino)
    return destino


def test_sin_atestacion_el_motor_escribe_la_plantilla(carpeta):
    revisar(carpeta, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    assert (carpeta / PLANTILLA_ATESTACION).exists(), \
        "el motor debe dejar la plantilla lista para llenar (D2)"


def test_la_plantilla_pide_solo_las_actividades_del_borrador(carpeta):
    revisar(carpeta, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    contenido = json.loads(
        (carpeta / PLANTILLA_ATESTACION).read_text(encoding="utf-8"))
    actividades = sorted(t["actividad"] for t in contenido["tarifas"])
    assert actividades == ["4669", "5224", "7490", "9609", "9903"]


def test_la_plantilla_deja_en_blanco_lo_que_debe_declarar_la_persona(carpeta):
    """El motor no propone tarifas: no las sabe, y sugerirlas anclaria al
    auditor a confirmar un valor que el motor no puede respaldar."""
    revisar(carpeta, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    contenido = json.loads(
        (carpeta / PLANTILLA_ATESTACION).read_text(encoding="utf-8"))
    for entrada in contenido["tarifas"]:
        assert entrada["tarifa"] == ""
        assert entrada["acuerdo"] == ""
        assert entrada["articulo"] == ""
    assert contenido["declarada_por"] == ""


def test_la_plantilla_no_pisa_una_atestacion_ya_hecha(carpeta):
    """Si el auditor ya atesto, el motor no puede sobreescribirle el trabajo."""
    real = carpeta / NOMBRE_ARCHIVO
    real.write_text(json.dumps({
        "declarada_por": "analitica@rbcol.co", "fecha": "2026-09-10",
        "tarifas": [], "cuentas": []}), encoding="utf-8")
    revisar(carpeta, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    assert leer_atestacion(carpeta).declarada_por == "analitica@rbcol.co"


def test_con_la_plantilla_completada_c7_queda_atestado(carpeta):
    """El circuito completo: el motor pide, la persona llena, C7 cambia."""
    revisar(carpeta, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    contenido = json.loads(
        (carpeta / PLANTILLA_ATESTACION).read_text(encoding="utf-8"))

    tarifas_reales = {"9609": "0.007", "7490": "0.007", "4669": "0.010",
                      "5224": "0.010", "9903": "0.010"}
    contenido["declarada_por"] = "analitica@rbcol.co"
    for entrada in contenido["tarifas"]:
        entrada["tarifa"] = tarifas_reales[entrada["actividad"]]
        entrada["acuerdo"] = "Resolucion 098 de 30-ene-2026"
        entrada["articulo"] = "primero"
        entrada["vigencia_desde"] = "2026-01-01"
    (carpeta / NOMBRE_ARCHIVO).write_text(
        json.dumps(contenido, ensure_ascii=False), encoding="utf-8")

    ctx = revisar(carpeta, nit="819002433", periodo="2026-07",
                  municipio=MUNICIPIO)
    c7 = next(r for r in ctx.resultados if r.codigo == "C7")
    assert c7.estado is Estado.ATESTADO
