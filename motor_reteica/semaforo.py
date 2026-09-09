"""5.3: semaforo de SOLIDEZ DE LA REVISION.

Califica que tan bien respaldada esta la revision, NO la calidad del borrador
del cliente. Es DETERMINISTICO: sale de los estados de control. La IA no lo
calcula (D8).

  ROJO      algun control NO EJECUTADO, o hallazgo con impacto en pesos
  AMARILLO  todos ejecutados, con excepciones sin impacto; tambien si algun
            control quedo ATESTADO -- se sostiene sobre el testimonio del
            auditor y no sobre una fuente externa
  VERDE     todos ejecutados y sin excepciones. Exige el Acuerdo municipal
            cargado: con C7 en ATESTADO nunca se llega a verde.
"""

from dataclasses import dataclass
from decimal import Decimal

ROJO = "ROJO"
AMARILLO = "AMARILLO"
VERDE = "VERDE"

_SIMBOLO = {ROJO: "[X]", AMARILLO: "[!]", VERDE: "[OK]"}


@dataclass(frozen=True)
class Semaforo:
    color: str
    motivo: str

    @property
    def simbolo(self) -> str:
        return _SIMBOLO[self.color]


def evaluar(informe) -> Semaforo:
    if informe.controles_no_ejecutados:
        return Semaforo(ROJO, "no se ejecutaron %s: la revision no respalda "
                              "una conclusion limpia"
                        % ", ".join(informe.controles_no_ejecutados))

    if informe.impacto_total > Decimal("0"):
        return Semaforo(ROJO, "hay hallazgos con impacto cuantificado de %s "
                              "pesos" % informe.impacto_total)

    if informe.controles_atestados:
        return Semaforo(AMARILLO,
                        "%s se sustenta(n) en la atestacion del auditor y no "
                        "en una fuente externa"
                        % ", ".join(informe.controles_atestados))

    if informe.controles_en_falla:
        return Semaforo(AMARILLO, "excepciones sin impacto en %s"
                        % ", ".join(informe.controles_en_falla))

    return Semaforo(VERDE, "todos los controles ejecutados y sin excepciones")
