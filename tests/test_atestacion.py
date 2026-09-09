"""X1 y M11: el mecanismo de atestacion del auditor.

Tres decisiones del diseno comparten esta forma: el motor senala lo que no
puede decidir solo, la persona decide, y queda impreso. No declarar NUNCA
produce un OK.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.atestacion import (AtestacionInvalida, CONTRAPARTIDA,
                                      leer_atestacion, plantilla)
from motor_reteica.controles import c7_tarifas_vs_estatuto
from motor_reteica.hallazgos import consolidar
from motor_reteica.ingesta.borrador_pdf import leer_borrador
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.tipos import Estado, ResultadoControl, Severidad

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"

_TARIFAS_REALES = {"9609": "0.007", "7490": "0.007", "4669": "0.010",
                   "5224": "0.010", "9903": "0.010"}


@pytest.fixture(scope="module")
def borrador():
    return leer_borrador(BASE / "borrador.pdf")


def _escribir(carpeta, tarifas=None, cuentas=None, **extra):
    contenido = {"declarada_por": "analitica@rbcol.co", "fecha": "2026-09-09",
                 "tarifas": tarifas or [], "cuentas": cuentas or []}
    contenido.update(extra)
    (carpeta / "atestacion.json").write_text(
        json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
    return carpeta


def _tarifas_completas():
    return [{"municipio": "Santa Marta", "actividad": codigo, "tarifa": tarifa,
             "vigencia_desde": "2026-01-01", "acuerdo": "Acuerdo 013 de 2024",
             "articulo": "52"}
            for codigo, tarifa in _TARIFAS_REALES.items()]


# --------------------------------------------------------------------------
# Sin atestacion no pasa nada bueno
# --------------------------------------------------------------------------

def test_sin_archivo_la_atestacion_esta_vacia(tmp_path):
    atestacion = leer_atestacion(tmp_path)
    assert atestacion.tarifas == {}
    assert atestacion.hay_tarifas is False


def test_sin_atestacion_c7_sigue_no_ejecutado(borrador, tmp_path):
    """Vacia no significa 'todo bien'."""
    resultado = c7_tarifas_vs_estatuto(borrador, MUNICIPIO,
                                       leer_atestacion(tmp_path))
    assert resultado.estado is Estado.NO_EJECUTADO


# --------------------------------------------------------------------------
# La procedencia es obligatoria
# --------------------------------------------------------------------------

@pytest.mark.parametrize("campo", ["acuerdo", "articulo", "vigencia_desde",
                                   "tarifa", "municipio"])
def test_una_tarifa_sin_procedencia_es_invalida(tmp_path, campo):
    entrada = _tarifas_completas()[0]
    del entrada[campo]
    _escribir(tmp_path, tarifas=[entrada])
    with pytest.raises(AtestacionInvalida) as error:
        leer_atestacion(tmp_path)
    assert campo in str(error.value)


def test_sin_quien_atesta_es_invalida(tmp_path):
    (tmp_path / "atestacion.json").write_text(
        json.dumps({"fecha": "2026-09-09"}), encoding="utf-8")
    with pytest.raises(AtestacionInvalida):
        leer_atestacion(tmp_path)


def test_una_naturaleza_de_cuenta_inventada_es_invalida(tmp_path):
    _escribir(tmp_path, cuentas=[{"cuenta": "2368010090",
                                  "naturaleza": "lo_que_sea",
                                  "motivo": "porque si"}])
    with pytest.raises(AtestacionInvalida):
        leer_atestacion(tmp_path)


# --------------------------------------------------------------------------
# X1: C7 atestado NO es C7 en OK
# --------------------------------------------------------------------------

def test_con_atestacion_completa_c7_queda_atestado_no_ok(borrador, tmp_path):
    _escribir(tmp_path, tarifas=_tarifas_completas())
    resultado = c7_tarifas_vs_estatuto(borrador, MUNICIPIO,
                                       leer_atestacion(tmp_path))
    assert resultado.estado is Estado.ATESTADO
    assert resultado.estado is not Estado.OK


def test_el_detalle_declara_que_es_testimonio_y_no_recalculo(borrador, tmp_path):
    _escribir(tmp_path, tarifas=_tarifas_completas())
    detalle = c7_tarifas_vs_estatuto(borrador, MUNICIPIO,
                                     leer_atestacion(tmp_path)).detalle
    assert "LIMITE" in detalle
    assert "analitica@rbcol.co" in detalle


def test_atestado_impide_concluir_limpio():
    """5.3: se sostiene sobre testimonio, no sobre fuente externa."""
    informe = consolidar([
        ResultadoControl(codigo="C1", nombre="x", estado=Estado.OK, detalle=""),
        ResultadoControl(codigo="C7", nombre="y", estado=Estado.ATESTADO,
                         detalle=""),
    ])
    assert informe.puede_concluir_limpio is False
    assert informe.controles_atestados == ("C7",)
    assert "atestacion del auditor" in informe.conclusion


def test_mutacion_el_auditor_atesta_una_tarifa_distinta(borrador, tmp_path):
    """El borrador aplica 10 por mil a 4669 y el auditor atesta 7."""
    tarifas = _tarifas_completas()
    for entrada in tarifas:
        if entrada["actividad"] == "4669":
            entrada["tarifa"] = "0.007"
    _escribir(tmp_path, tarifas=tarifas)
    resultado = c7_tarifas_vs_estatuto(borrador, MUNICIPIO,
                                       leer_atestacion(tmp_path))
    assert resultado.estado is Estado.FALLA
    excepcion = next(e for e in resultado.excepciones if "4669" in e.descripcion)
    assert excepcion.severidad is Severidad.HALLAZGO
    assert excepcion.impacto_pesos > 0


def test_una_actividad_del_borrador_sin_atestar_es_hallazgo(borrador, tmp_path):
    tarifas = [t for t in _tarifas_completas() if t["actividad"] != "5224"]
    _escribir(tmp_path, tarifas=tarifas)
    resultado = c7_tarifas_vs_estatuto(borrador, MUNICIPIO,
                                       leer_atestacion(tmp_path))
    assert resultado.estado is Estado.FALLA
    assert any("5224" in e.descripcion and "sin respaldo" in e.descripcion
               for e in resultado.excepciones)


# --------------------------------------------------------------------------
# M11: cuentas
# --------------------------------------------------------------------------

def test_la_cuenta_atestada_como_contrapartida_se_excluye(tmp_path):
    _escribir(tmp_path, cuentas=[{"cuenta": "2368010090",
                                  "naturaleza": CONTRAPARTIDA,
                                  "motivo": "Ret. Ffe ICA a pagar"}])
    assert leer_atestacion(tmp_path).cuentas_excluidas() == {"2368010090"}


def test_la_plantilla_trae_los_huecos_a_llenar():
    """D2: nada interactivo. El motor deja el esqueleto y el auditor lo llena."""
    esqueleto = plantilla("Santa Marta", ["4669", "5224"], ["2368010090"])
    assert esqueleto["declarada_por"] == ""
    assert [t["actividad"] for t in esqueleto["tarifas"]] == ["4669", "5224"]
    assert esqueleto["cuentas"][0]["cuenta"] == "2368010090"
    assert all(t["acuerdo"] == "" for t in esqueleto["tarifas"])
