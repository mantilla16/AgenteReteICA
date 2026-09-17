"""Cliente de Anthropic para la Revision Inteligente.

D7: si el modelo NO se puede llamar -- sin llave, sin red, error de API -- los
controles de IA salen NO_EJECUTADO, nunca OK. Esta clase no lanza excepciones
hacia el pipeline: devuelve una Respuesta que dice si hubo texto o por que no.
La IA es un insumo del papel con la misma disciplina que el balance de prueba.

D9: la reproducibilidad no viene de la temperatura.

  OJO -- CORRECCION AL DISENO: D9 pedia "temperatura en cero". El parametro
  `temperature` FUE ELIMINADO en los modelos actuales de Anthropic: enviarlo a
  claude-opus-5 devuelve HTTP 400. No es que se ignore, es que rechaza la
  peticion. La reproducibilidad se sostiene entonces sobre lo que si
  controlamos y queda impreso en el papel:
    - el prompt esta VERSIONADO y su hash se estampa,
    - el id exacto del modelo se estampa,
    - la respuesta cruda se archiva como evidencia.
  Y sobre la regla que de verdad sostiene todo (D9): ningun estado de control
  determinista depende de una salida de IA no verificada.
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

MODELO_POR_DEFECTO = "claude-opus-5"
VARIABLE_LLAVE = "ANTHROPIC_API_KEY"
_MAX_TOKENS = 16000

# Modelo local servido por Ollama. Se reutilizan los nombres de variable que ya
# usa analitica-puc en el mismo servidor para no tener dos convenciones.
VARIABLE_PROVEEDOR    = "RETEICA_IA_PROVEEDOR"
VARIABLE_MODELO_LOCAL = "OLLAMA_MODELO"
VARIABLE_URL_LOCAL    = "OLLAMA_URL"
VARIABLE_TIMEOUT      = "IA_TIMEOUT"
MODELO_LOCAL_POR_DEFECTO = "qwen2.5:3b-instruct"
URL_LOCAL_POR_DEFECTO    = "http://127.0.0.1:11434"
_TIMEOUT_LOCAL_POR_DEFECTO = 600.0


@dataclass(frozen=True)
class Respuesta:
    """Resultado de una llamada. `texto` vacio con `motivo` = no se ejecuto."""

    texto: str = ""
    motivo: str = ""
    modelo: str = ""
    hash_prompt: str = ""
    momento: str = ""
    prompt: str = field(default="", repr=False)

    @property
    def hubo_respuesta(self) -> bool:
        return bool(self.texto)


def hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def hay_llave() -> bool:
    return bool(os.environ.get(VARIABLE_LLAVE, "").strip())


def _var(nombre: str, defecto: str = "") -> str:
    return os.environ.get(nombre, defecto).strip()


def _proveedor_actual() -> str:
    elegido = _var(VARIABLE_PROVEEDOR).lower()
    if elegido:
        return "local" if elegido in ("local", "ollama") else "anthropic"
    if _var(VARIABLE_MODELO_LOCAL) or _var(VARIABLE_URL_LOCAL):
        return "local"
    return "anthropic"


def proveedor() -> str:
    """Que motor de IA se usa: 'local' (Ollama) o 'anthropic'.

    Si nadie lo dice explicitamente se deduce: hay modelo local configurado ->
    local; si no, Anthropic. Asi la bateria de pruebas, que no configura nada,
    sigue viendo el comportamiento de siempre.
    """
    return _proveedor_actual()


def modelo_local() -> str:
    return _var(VARIABLE_MODELO_LOCAL) or MODELO_LOCAL_POR_DEFECTO


def url_local() -> str:
    return (_var(VARIABLE_URL_LOCAL) or URL_LOCAL_POR_DEFECTO).rstrip("/")


def _timeout_local() -> float:
    try:
        return float(_var(VARIABLE_TIMEOUT) or _TIMEOUT_LOCAL_POR_DEFECTO)
    except ValueError:
        return _TIMEOUT_LOCAL_POR_DEFECTO


def ia_configurada() -> bool:
    """Hay con que llamar a un modelo, sea local o de Anthropic.

    Quien arma el pipeline usa esto para decidir si pasa un cliente o pasa None.
    Pasar None deja los controles de IA fuera del papel; pasar un cliente que
    luego falla los deja en NO_EJECUTADO. Son cosas distintas y el papel las
    distingue, por eso la pregunta se hace antes.
    """
    return proveedor() == "local" or hay_llave()


class ClienteIA:
    """Envoltura delgada sobre el SDK de Anthropic.

    No se instancia el SDK hasta que se llama: asi el motor se puede importar
    y correr entero sin tener `anthropic` instalado ni llave configurada, que
    es el caso normal en la bateria de pruebas.
    """

    def __init__(self, modelo: str = None, api_key: str = None,
                 cliente=None, proveedor: str = None):
        self._proveedor = (proveedor or _proveedor_actual()).lower()
        self._local = self._proveedor == "local"
        # El id crudo es lo que se le manda al servidor; `modelo` es lo que se
        # estampa en el papel, y ahi si conviene que diga de donde salio.
        self._modelo_crudo = modelo or (modelo_local() if self._local
                                        else MODELO_POR_DEFECTO)
        self.modelo = ("ollama/%s" % self._modelo_crudo if self._local
                       else self._modelo_crudo)
        self._api_key = api_key
        self._cliente = cliente

    def _resolver(self):
        if self._cliente is not None:
            return self._cliente, ""
        if not (self._api_key or hay_llave()):
            return None, ("no hay llave de API: defina %s o pase --api-key"
                          % VARIABLE_LLAVE)
        try:
            import anthropic
        except ImportError:
            return None, ("el paquete 'anthropic' no esta instalado "
                          "(pip install anthropic)")
        return anthropic.Anthropic(api_key=self._api_key), ""

    def preguntar(self, sistema: str, prompt: str) -> Respuesta:
        base = dict(modelo=self.modelo, hash_prompt=hash_prompt(prompt),
                    momento=datetime.now(timezone.utc).isoformat(),
                    prompt=prompt)
        if self._local and self._cliente is None:
            return self._preguntar_local(sistema, prompt, base)
        return self._preguntar_anthropic(sistema, prompt, base)

    def _preguntar_anthropic(self, sistema: str, prompt: str,
                             base: dict) -> Respuesta:
        cliente, motivo = self._resolver()
        if cliente is None:
            return Respuesta(motivo=motivo, **base)

        try:
            respuesta = cliente.messages.create(
                model=self._modelo_crudo,
                max_tokens=_MAX_TOKENS,
                system=sistema,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # el motor no puede caerse por la IA
            return Respuesta(
                motivo="%s: %s" % (type(error).__name__, error), **base)

        texto = "".join(bloque.text for bloque in respuesta.content
                        if getattr(bloque, "type", "") == "text")
        if not texto.strip():
            return Respuesta(motivo="el modelo no devolvio texto", **base)
        return Respuesta(texto=texto, **base)

    def _preguntar_local(self, sistema: str, prompt: str,
                         base: dict) -> Respuesta:
        """Ollama por HTTP. Mismo contrato: nunca lanza hacia el pipeline.

        Aqui SI se puede honrar D9 al pie de la letra, a diferencia del camino
        de Anthropic: el servidor local acepta `temperature` y `seed`, asi que
        la corrida es reproducible de verdad, no solo trazable.
        """
        try:
            import httpx
        except ImportError:
            return Respuesta(
                motivo="el paquete 'httpx' no esta instalado", **base)

        cuerpo = {
            "model": self._modelo_crudo,
            "stream": False,
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": prompt}],
            "options": {"temperature": 0, "seed": 0,
                        "num_predict": _MAX_TOKENS},
        }
        try:
            respuesta = httpx.post("%s/api/chat" % url_local(), json=cuerpo,
                                   timeout=_timeout_local())
            respuesta.raise_for_status()
            datos = respuesta.json()
        except Exception as error:
            return Respuesta(
                motivo="%s: %s" % (type(error).__name__, error), **base)

        texto = (datos.get("message") or {}).get("content", "")
        if not texto.strip():
            return Respuesta(motivo="el modelo no devolvio texto", **base)
        return Respuesta(texto=texto, **base)
