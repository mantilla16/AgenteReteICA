"""Etapa 5: la IA como insumo del papel, con la misma disciplina que el resto.

Ninguna prueba llama a la red. Se usa un cliente doble: lo que se prueba es la
CONTENCION -- que la IA no pueda hacer dano y que su ausencia no produzca OK.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.ia.cliente import (VARIABLE_LLAVE, VARIABLE_MODELO_LOCAL,
                                      VARIABLE_PROVEEDOR, VARIABLE_URL_LOCAL,
                                      ClienteIA, Respuesta, hash_prompt,
                                      ia_configurada, proveedor)
from motor_reteica.ia.controles_ia import ia1_plausibilidad, ia3_consistencia
from motor_reteica.hallazgos import consolidar
from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.borrador_pdf import leer_borrador
from motor_reteica.ingesta.sap_retenciones import leer_sap_retenciones
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import mapa_actividad, revisar
from motor_reteica.reconstruccion import reconstruir
from motor_reteica.tipos import Estado, Severidad

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


class ClienteFalso:
    """Devuelve lo que se le diga y guarda el prompt que recibio."""

    def __init__(self, texto="[]", motivo=""):
        self.texto = texto
        self.motivo = motivo
        self.prompts = []

    def preguntar(self, sistema, prompt):
        self.prompts.append(prompt)
        return Respuesta(texto="" if self.motivo else self.texto,
                         motivo=self.motivo, modelo="doble",
                         hash_prompt=hash_prompt(prompt), momento="",
                         prompt=prompt)


@pytest.fixture(scope="module")
def recon():
    lineas = leer_auxiliar(BASE / "auxiliar_2368.xlsx")
    erp = leer_sap_retenciones(BASE / "sap_retenciones.xlsx")
    borrador = leer_borrador(BASE / "borrador.pdf")
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    return reconstruir(lineas, erp, MUNICIPIO, mapa), borrador


# --------------------------------------------------------------------------
# Sin modelo NO hay OK
# --------------------------------------------------------------------------

def test_sin_llave_ia1_es_no_ejecutado(recon, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reconstruccion, borrador = recon
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=ClienteIA())
    assert resultado.estado is Estado.NO_EJECUTADO
    assert "llave" in resultado.detalle


def test_un_error_de_api_es_no_ejecutado_no_ok(recon):
    reconstruccion, borrador = recon
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=ClienteFalso(motivo="APIStatusError: 500"))
    assert resultado.estado is Estado.NO_EJECUTADO
    assert resultado.estado is not Estado.OK


def test_una_respuesta_que_no_es_json_es_no_ejecutado(recon):
    reconstruccion, borrador = recon
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=ClienteFalso(texto="no soy json"))
    assert resultado.estado is Estado.NO_EJECUTADO


def test_el_motor_no_se_cae_si_el_sdk_no_esta_instalado(recon):
    """Importar y correr el motor no puede depender de tener 'anthropic'."""
    reconstruccion, borrador = recon
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=ClienteIA(api_key="x"))
    assert resultado.estado in (Estado.NO_EJECUTADO, Estado.OK, Estado.FALLA)


# --------------------------------------------------------------------------
# 5.7 el prompt no lleva lo que no necesita
# --------------------------------------------------------------------------

def test_el_prompt_no_manda_nit_ni_nombres_ni_montos(recon):
    reconstruccion, borrador = recon
    doble = ClienteFalso()
    ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO, cliente=doble)
    prompt = doble.prompts[0]

    for nit in ("800193573", "811033997", "901670478"):
        assert nit not in prompt, "el NIT %s no debe salir del motor" % nit
    for nombre in ("SUPER PORTUARIA", "CDEM", "TERLICA"):
        assert nombre not in prompt
    for monto in ("18296", "474561", "38965609"):
        assert monto not in prompt


def test_el_prompt_si_manda_concepto_cuenta_y_renglon(recon):
    reconstruccion, borrador = recon
    doble = ClienteFalso()
    ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO, cliente=doble)
    prompt = doble.prompts[0]
    assert "REPARACION MANGUERA" in prompt
    assert "2368010010" in prompt
    assert "4669" in prompt


def test_el_prompt_pide_plausibilidad_no_clasificacion(recon):
    reconstruccion, borrador = recon
    doble = ClienteFalso()
    ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO, cliente=doble)
    prompt = doble.prompts[0]
    assert "PLAUSIBILIDAD" in prompt
    assert "No propones la clasificacion correcta como veredicto" in prompt


def test_la_prohibicion_de_calcular_esta_en_el_sistema():
    from motor_reteica.ia.controles_ia import _SISTEMA
    assert "NO calculas" in _SISTEMA


# --------------------------------------------------------------------------
# La consecuencia la calcula el MOTOR, no la IA
# --------------------------------------------------------------------------

def _contradiccion(linea="L5", sugerida=""):
    return json.dumps([{"linea": linea, "contradice": True,
                        "evidencia": "el concepto dice reparacion",
                        "actividad_sugerida": sugerida}])


def test_misma_clase_de_tarifa_es_observacion_sin_impacto(recon):
    reconstruccion, borrador = recon
    doble = ClienteFalso(texto=_contradiccion(sugerida="5224"))
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=doble)
    assert resultado.estado is Estado.FALLA
    excepcion = resultado.excepciones[0]
    assert excepcion.severidad is Severidad.OBSERVACION
    assert excepcion.impacto_pesos == Decimal("0")


def test_otra_clase_de_tarifa_sube_a_hallazgo_con_impacto_del_motor(recon):
    """La IA sugiere 7490 (7 por mil) para una linea al 10: el motor calcula."""
    reconstruccion, borrador = recon
    doble = ClienteFalso(texto=_contradiccion(sugerida="7490"))
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=doble)
    excepcion = resultado.excepciones[0]
    assert excepcion.severidad is Severidad.HALLAZGO
    assert excepcion.impacto_pesos > 0


def test_la_ia_no_puede_inventar_una_linea(recon):
    """Si nombra una linea que no existe, se descarta en vez de creerle."""
    reconstruccion, borrador = recon
    doble = ClienteFalso(texto=_contradiccion(linea="L999"))
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=doble)
    assert resultado.excepciones == ()


def test_la_ia_no_puede_alterar_una_cifra_del_motor(recon):
    """Aunque devuelva un impacto, el motor no lo lee."""
    reconstruccion, borrador = recon
    antes = reconstruccion.total_impuesto_contable
    doble = ClienteFalso(texto=json.dumps([{
        "linea": "L5", "contradice": True, "evidencia": "x",
        "actividad_sugerida": "5224", "impacto_pesos": "999999999"}]))
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=doble)
    assert reconstruccion.total_impuesto_contable == antes
    assert resultado.excepciones[0].impacto_pesos == Decimal("0")


# --------------------------------------------------------------------------
# La condicion de redaccion
# --------------------------------------------------------------------------

def test_el_detalle_dice_que_es_plausibilidad_y_no_clasificacion(recon):
    reconstruccion, borrador = recon
    detalle = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                cliente=ClienteFalso()).detalle
    assert "PLAUSIBILIDAD" in detalle
    assert "NO que la clasificacion sea correcta" in detalle


# --------------------------------------------------------------------------
# D7: el carril propio bloquea la conclusion limpia
# --------------------------------------------------------------------------

def test_un_hallazgo_de_la_ia_impide_concluir_limpio(recon):
    reconstruccion, borrador = recon
    ia1 = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                            cliente=ClienteFalso(_contradiccion(sugerida="7490")))
    informe = consolidar([ia1])
    assert informe.puede_concluir_limpio is False
    assert "IA-1" in informe.controles_en_falla


def test_ia3_comenta_sin_tocar_estados(recon):
    reconstruccion, borrador = recon
    ia1 = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                            cliente=ClienteFalso())
    informe = consolidar([ia1])
    estados_antes = [r.estado for r in [ia1]]
    ia3 = ia3_consistencia([ia1], informe, cliente=ClienteFalso(json.dumps([
        {"asunto": "conclusion", "comentario": "revisar C7", "escalar": True}])))
    assert [r.estado for r in [ia1]] == estados_antes
    assert ia3.excepciones[0].severidad is Severidad.OBSERVACION


def test_el_pipeline_sin_cliente_no_agrega_controles_de_ia():
    ctx = revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    assert not [r for r in ctx.resultados if r.codigo.startswith("IA-")]


def test_el_pipeline_con_cliente_agrega_los_dos_carriles():
    ctx = revisar(BASE, nit="819002433", periodo="2026-07",
                  municipio=MUNICIPIO, cliente_ia=ClienteFalso())
    codigos = [r.codigo for r in ctx.resultados]
    assert "IA-1" in codigos and "IA-3" in codigos


def test_la_ia_no_cambia_las_anclas():
    """Lo que sostiene todo: ningun numero depende de la IA."""
    sin_ia = revisar(BASE, nit="819002433", periodo="2026-07",
                     municipio=MUNICIPIO)
    con_ia = revisar(BASE, nit="819002433", periodo="2026-07",
                     municipio=MUNICIPIO,
                     cliente_ia=ClienteFalso(_contradiccion(sugerida="7490")))
    assert (sin_ia.reconstruccion.total_impuesto_contable
            == con_ia.reconstruccion.total_impuesto_contable
            == Decimal("474561"))
    assert sin_ia.reconstruccion.total_base == con_ia.reconstruccion.total_base
    deterministas = [r for r in con_ia.resultados
                     if not r.codigo.startswith("IA-")]
    assert [r.estado for r in sin_ia.resultados] == [r.estado for r in deterministas]


# --------------------------------------------------------------------------
# El modelo local (Ollama): mismo contrato, sin llave
# --------------------------------------------------------------------------

class _RespuestaHTTP:
    """Doble de la respuesta de httpx. No hay red en ninguna prueba."""

    def __init__(self, datos, estado=200):
        self._datos = datos
        self.status_code = estado

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)

    def json(self):
        return self._datos


def _sin_ia(monkeypatch):
    for v in (VARIABLE_LLAVE, VARIABLE_PROVEEDOR, VARIABLE_MODELO_LOCAL,
              VARIABLE_URL_LOCAL):
        monkeypatch.delenv(v, raising=False)


def test_sin_nada_configurado_el_proveedor_sigue_siendo_anthropic(monkeypatch):
    """La bateria de pruebas no configura nada: el default no puede cambiar."""
    _sin_ia(monkeypatch)
    assert proveedor() == "anthropic"
    assert not ia_configurada()


def test_con_modelo_local_no_hace_falta_llave(monkeypatch):
    _sin_ia(monkeypatch)
    monkeypatch.setenv(VARIABLE_MODELO_LOCAL, "qwen2.5:3b-instruct")
    assert proveedor() == "local"
    assert ia_configurada(), "con modelo local no se necesita ANTHROPIC_API_KEY"


def test_el_papel_estampa_que_el_modelo_fue_local(monkeypatch):
    """D9: el id exacto del modelo se estampa. Debe distinguirse de la nube."""
    _sin_ia(monkeypatch)
    monkeypatch.setenv(VARIABLE_MODELO_LOCAL, "qwen2.5:3b-instruct")
    assert ClienteIA().modelo == "ollama/qwen2.5:3b-instruct"


def test_al_modelo_local_se_le_pide_reproducibilidad(monkeypatch):
    """Lo que D9 no pudo pedirle a Anthropic, aqui si: temperatura 0 y seed."""
    _sin_ia(monkeypatch)
    monkeypatch.setenv(VARIABLE_MODELO_LOCAL, "qwen2.5:3b-instruct")
    enviado = {}

    def falso_post(url, json=None, timeout=None):
        enviado["url"] = url
        enviado["cuerpo"] = json
        return _RespuestaHTTP({"message": {"content": "[]"}})

    import httpx
    monkeypatch.setattr(httpx, "post", falso_post)

    respuesta = ClienteIA().preguntar("eres un revisor", "revisa esto")

    assert respuesta.texto == "[]"
    assert enviado["url"].endswith("/api/chat")
    assert enviado["cuerpo"]["model"] == "qwen2.5:3b-instruct"
    assert enviado["cuerpo"]["stream"] is False
    assert enviado["cuerpo"]["options"]["temperature"] == 0
    assert enviado["cuerpo"]["options"]["seed"] == 0
    roles = [m["role"] for m in enviado["cuerpo"]["messages"]]
    assert roles == ["system", "user"]


def test_si_el_modelo_local_no_responde_es_no_ejecutado_no_ok(recon,
                                                             monkeypatch):
    """D7 tambien aplica al modelo local: caido no puede significar OK."""
    _sin_ia(monkeypatch)
    monkeypatch.setenv(VARIABLE_MODELO_LOCAL, "qwen2.5:3b-instruct")

    def falso_post(url, json=None, timeout=None):
        raise OSError("connection refused")

    import httpx
    monkeypatch.setattr(httpx, "post", falso_post)

    reconstruccion, borrador = recon
    resultado = ia1_plausibilidad(reconstruccion, borrador, MUNICIPIO,
                                  cliente=ClienteIA())
    assert resultado.estado is Estado.NO_EJECUTADO
    assert resultado.estado is not Estado.OK
