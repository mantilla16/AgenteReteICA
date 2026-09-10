"""Correcciones que salieron de la primera corrida real de la IA (IA-3).

V4 es la mas importante: el papel afirmaba que ninguna excepcion tiene
impacto. Con C7 sin ejecutar -- sin tabla de tarifas validada -- reclasificar
un renglon puede cambiar la tarifa, asi que el impacto no es CERO: es
INDETERMINADO. Cuantificado sobre julio 2026 con la tabla preliminar de la
Resolucion 098: hasta 10.985 pesos.
"""

from decimal import Decimal

import pytest

from motor_reteica.hallazgos import consolidar
from motor_reteica.tipos import (Estado, Excepcion, ResultadoControl,
                                 Severidad, etiqueta_estado)


def _control(codigo, estado, aplica=True, excepciones=()):
    return ResultadoControl(codigo=codigo, nombre=codigo, estado=estado,
                            detalle="", excepciones=tuple(excepciones),
                            aplica=aplica)


_OBSERVACION = Excepcion(severidad=Severidad.OBSERVACION, control="C6",
                         descripcion="clasificacion dudosa",
                         impacto_pesos=Decimal("0"))


# --------------------------------------------------------------------------
# V4: sin tabla de tarifas validada, el impacto es INDETERMINADO
# --------------------------------------------------------------------------

def test_sin_c7_el_impacto_no_se_declara_cero():
    informe = consolidar([
        _control("C7", Estado.NO_EJECUTADO),
        _control("C6", Estado.FALLA, excepciones=[_OBSERVACION]),
    ])
    conclusion = informe.conclusion.lower()
    assert "indetermin" in conclusion
    assert "ninguna excepcion tiene impacto" not in conclusion


def test_sin_c7_la_conclusion_explica_por_que_es_indeterminado():
    informe = consolidar([
        _control("C7", Estado.NO_EJECUTADO),
        _control("C6", Estado.FALLA, excepciones=[_OBSERVACION]),
    ])
    assert "tarifa" in informe.conclusion.lower()


def test_con_c7_ejecutado_si_puede_decir_que_no_hay_impacto():
    informe = consolidar([
        _control("C7", Estado.OK),
        _control("C6", Estado.FALLA, excepciones=[_OBSERVACION]),
    ])
    assert "ninguna excepcion tiene impacto" in informe.conclusion.lower()


def test_con_c7_atestado_tambien_vale():
    """ATESTADO es testimonio del auditor sobre la tarifa: hay respaldo."""
    informe = consolidar([
        _control("C7", Estado.ATESTADO),
        _control("C6", Estado.FALLA, excepciones=[_OBSERVACION]),
    ])
    assert "indetermin" not in informe.conclusion.lower()


def test_si_hay_impacto_real_se_reporta_igual():
    """La correccion no puede tapar un impacto que si esta cuantificado."""
    con_impacto = Excepcion(severidad=Severidad.HALLAZGO, control="C9",
                            descripcion="diferencia",
                            impacto_pesos=Decimal("5000"))
    informe = consolidar([
        _control("C7", Estado.NO_EJECUTADO),
        _control("C9", Estado.FALLA, excepciones=[con_impacto]),
    ])
    assert "5000" in informe.conclusion


# --------------------------------------------------------------------------
# V6: "no aplica" y "no ejecutado" son cosas distintas
# --------------------------------------------------------------------------

def test_un_control_que_no_aplica_no_se_muestra_como_no_ejecutado():
    """C14 mostraba 'NO EJECUTADO' en el estado y 'no aplica' en el detalle:
    el papel decia las dos cosas a la vez."""
    c14 = _control("C14", Estado.NO_EJECUTADO, aplica=False)
    assert etiqueta_estado(c14) == "NO APLICA"


def test_un_control_que_si_aplica_conserva_su_estado():
    c7 = _control("C7", Estado.NO_EJECUTADO)
    assert etiqueta_estado(c7) == "NO EJECUTADO"
    assert etiqueta_estado(_control("C1", Estado.OK)) == "OK"
