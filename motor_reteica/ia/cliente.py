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


class ClienteIA:
    """Envoltura delgada sobre el SDK de Anthropic.

    No se instancia el SDK hasta que se llama: asi el motor se puede importar
    y correr entero sin tener `anthropic` instalado ni llave configurada, que
    es el caso normal en la bateria de pruebas.
    """

    def __init__(self, modelo: str = MODELO_POR_DEFECTO, api_key: str = None,
                 cliente=None):
        self.modelo = modelo
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
        cliente, motivo = self._resolver()
        base = dict(modelo=self.modelo, hash_prompt=hash_prompt(prompt),
                    momento=datetime.now(timezone.utc).isoformat(),
                    prompt=prompt)
        if cliente is None:
            return Respuesta(motivo=motivo, **base)

        try:
            respuesta = cliente.messages.create(
                model=self.modelo,
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
