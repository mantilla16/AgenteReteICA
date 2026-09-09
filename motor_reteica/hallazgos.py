"""Consolidacion de excepciones y generacion de la conclusion.

La conclusion NO se redacta libremente: se deriva del estado de los controles.
Un papel con controles en FALLA o NO_EJECUTADO no puede concluir limpio.
"""

from dataclasses import dataclass
from decimal import Decimal

from motor_reteica.tipos import Estado, Severidad

_ORDEN = {Severidad.HALLAZGO: 0, Severidad.OBSERVACION: 1, Severidad.AVISO: 2}

LIMITACION_INTEGRIDAD = (
    "ALCANCE: esta revision parte de la cuenta 2368, es decir, de las "
    "retenciones que la compania si practico. NO cubre integridad: un "
    "proveedor gravado al que nunca se le retuvo no aparece en la fuente y "
    "por tanto no es detectable con este procedimiento."
)


@dataclass(frozen=True)
class Informe:
    excepciones_ordenadas: tuple
    impacto_total: Decimal
    puede_concluir_limpio: bool
    conclusion: str
    controles_en_falla: tuple
    controles_no_ejecutados: tuple
    controles_no_aplicables: tuple


def consolidar(resultados) -> Informe:
    excepciones = [e for r in resultados for e in r.excepciones]
    excepciones.sort(key=lambda e: (_ORDEN[e.severidad], -e.impacto_pesos))

    en_falla = tuple(r.codigo for r in resultados if r.estado is Estado.FALLA)
    no_ejecutados = tuple(
        r.codigo for r in resultados
        if r.estado is Estado.NO_EJECUTADO and r.aplica)
    no_aplicables = tuple(
        r.codigo for r in resultados if not r.aplica)
    impacto = sum((e.impacto_pesos for e in excepciones), Decimal("0"))
    limpio = not en_falla and not no_ejecutados

    partes = []
    if limpio:
        partes.append(
            "De acuerdo con los procedimientos aplicados, la declaracion "
            "revisada no presenta diferencias.")
    else:
        if en_falla:
            partes.append(
                "Los siguientes controles presentan excepciones: %s."
                % ", ".join(en_falla))
        if no_ejecutados:
            partes.append(
                "Los siguientes controles NO se ejecutaron por falta de "
                "insumos y por tanto no respaldan conclusion alguna: %s."
                % ", ".join(no_ejecutados))
        partes.append(
            "En consecuencia, la revision NO es concluyente en su totalidad.")

    if impacto > 0:
        partes.append(
            "El impacto cuantificado de las excepciones asciende a %s pesos."
            % impacto)
    else:
        partes.append(
            "Ninguna excepcion tiene impacto cuantificado en el impuesto a "
            "cargo; las detectadas son de clasificacion y presentacion.")

    if no_aplicables:
        partes.append(
            "No aplican al municipio de la declaracion: %s."
            % ", ".join(no_aplicables))

    partes.append(LIMITACION_INTEGRIDAD)

    return Informe(
        excepciones_ordenadas=tuple(excepciones),
        impacto_total=impacto,
        puede_concluir_limpio=limpio,
        conclusion=" ".join(partes),
        controles_en_falla=en_falla,
        controles_no_ejecutados=no_ejecutados,
        controles_no_aplicables=no_aplicables,
    )
