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
    controles_atestados: tuple = ()


# El control que valida la tarifa aplicada contra la del municipio.
_CONTROL_DE_TARIFAS = "C7"


def _tarifas_con_respaldo(resultados) -> bool:
    """Hay tabla de tarifas verificada, sea por el estatuto o por atestacion."""
    for resultado in resultados:
        if resultado.codigo == _CONTROL_DE_TARIFAS:
            return resultado.estado in (Estado.OK, Estado.ATESTADO)
    return False


def consolidar(resultados) -> Informe:
    excepciones = [e for r in resultados for e in r.excepciones]
    excepciones.sort(key=lambda e: (_ORDEN[e.severidad], -e.impacto_pesos))

    en_falla = tuple(r.codigo for r in resultados if r.estado is Estado.FALLA)
    no_ejecutados = tuple(
        r.codigo for r in resultados
        if r.estado is Estado.NO_EJECUTADO and r.aplica)
    no_aplicables = tuple(
        r.codigo for r in resultados if not r.aplica)
    atestados = tuple(r.codigo for r in resultados
                      if r.estado is Estado.ATESTADO)
    impacto = sum((e.impacto_pesos for e in excepciones), Decimal("0"))
    # X1/5.3: un control ATESTADO se sostiene sobre el testimonio del auditor,
    # no sobre una fuente externa. No impide trabajar, pero impide concluir
    # limpio: el papel no puede dar a entender que hubo verificacion
    # independiente donde solo hubo testimonio.
    limpio = not en_falla and not no_ejecutados and not atestados

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
        if atestados:
            partes.append(
                "Los siguientes controles se sustentan en la atestacion del "
                "auditor y no en una fuente externa: %s." % ", ".join(atestados))
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
    elif excepciones and not _tarifas_con_respaldo(resultados):
        # V4, objecion de IA-3 confirmada y cuantificada. Sin C7 no hay tabla
        # de tarifas validada, y reclasificar un renglon normalmente CAMBIA
        # la tarifa: el efecto en el impuesto no es cero, es desconocido.
        # Medido sobre julio 2026 con la tabla preliminar de la Resolucion
        # 098: las reclasificaciones que sugiere la IA valen hasta 10.985
        # pesos. Decir "sin impacto" ahi es afirmar de mas.
        partes.append(
            "El impacto de las excepciones es INDETERMINADO, no nulo: sin la "
            "tabla de tarifas del municipio verificada (C7) no se puede "
            "afirmar que reclasificar un renglon deje el impuesto igual, "
            "porque normalmente implica otra tarifa.")
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
        controles_atestados=atestados,
    )
