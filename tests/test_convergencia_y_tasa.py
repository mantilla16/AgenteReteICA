"""V7 y V8: las dos objeciones de IA-3 que faltaban.

V7 CONVERGENCIA. C6 (deterministico) e IA-1 (plausibilidad) marcaron los
   MISMOS documentos por la misma causa. Dos controles independientes
   apuntando al mismo error es CORROBORACION, no dos observaciones sueltas
   que el lector tiene que juntar por su cuenta.

   Lo que NO se hace: subirlas a HALLAZGO automaticamente. La regla del
   proyecto es que sin impacto cuantificado no hay hallazgo, y con C7 sin
   ejecutar el impacto es indeterminado (V4). Ademas reescribir la severidad
   que emitio un control le quitaria al control su propio veredicto. La
   convergencia se NOMBRA; la severidad la siguen decidiendo los controles.

V8 TASA. Tres de tres documentos revisados en clasificacion presentan
   excepcion. Una tasa del 100% es un hallazgo de proceso, no tres
   incidencias sueltas, y el papel no lo decia.
"""

from decimal import Decimal

import pytest

from motor_reteica.hallazgos import consolidar
from motor_reteica.tipos import (Estado, Excepcion, ResultadoControl,
                                 Severidad)


def _control(codigo, estado=Estado.FALLA, excepciones=()):
    return ResultadoControl(codigo=codigo, nombre=codigo, estado=estado,
                            detalle="", excepciones=tuple(excepciones))


def _exc(control, documento, severidad=Severidad.OBSERVACION):
    return Excepcion(severidad=severidad, control=control,
                     descripcion="%s: algo" % documento,
                     documento=documento, impacto_pesos=Decimal("0"))


# --------------------------------------------------------------------------
# V7: convergencia
# --------------------------------------------------------------------------

def test_dos_controles_sobre_el_mismo_documento_se_reportan_juntos():
    informe = consolidar([
        _control("C7", Estado.NO_EJECUTADO),
        _control("C6", excepciones=[_exc("C6", "FE338043")]),
        _control("IA-1", excepciones=[_exc("IA-1", "FE338043")]),
    ])
    assert "FE338043" in informe.convergencias
    assert sorted(informe.convergencias["FE338043"]) == ["C6", "IA-1"]


def test_la_convergencia_se_nombra_en_la_conclusion():
    informe = consolidar([
        _control("C7", Estado.NO_EJECUTADO),
        _control("C6", excepciones=[_exc("C6", "FE338043")]),
        _control("IA-1", excepciones=[_exc("IA-1", "FE338043")]),
    ])
    conclusion = informe.conclusion
    assert "FE338043" in conclusion
    assert "C6" in conclusion and "IA-1" in conclusion
    assert "corrobor" in conclusion.lower()


def test_un_solo_control_sobre_un_documento_no_es_convergencia():
    informe = consolidar([
        _control("C6", excepciones=[_exc("C6", "FE10")]),
    ])
    assert informe.convergencias == {}


def test_el_mismo_control_dos_veces_tampoco_es_convergencia():
    """Dos excepciones de C6 sobre el mismo documento son un control, no dos."""
    informe = consolidar([
        _control("C6", excepciones=[_exc("C6", "FE10"), _exc("C6", "FE10")]),
    ])
    assert informe.convergencias == {}


def test_la_convergencia_no_reescribe_la_severidad_de_los_controles():
    """Sin impacto cuantificado no hay hallazgo: la regla no se rompe porque
    dos controles coincidan."""
    informe = consolidar([
        _control("C7", Estado.NO_EJECUTADO),
        _control("C6", excepciones=[_exc("C6", "FE338043")]),
        _control("IA-1", excepciones=[_exc("IA-1", "FE338043")]),
    ])
    assert all(e.severidad is Severidad.OBSERVACION
               for e in informe.excepciones_ordenadas)


# --------------------------------------------------------------------------
# V8: tasa de excepcion
# --------------------------------------------------------------------------

def test_se_reporta_cuantos_documentos_distintos_tienen_excepcion():
    informe = consolidar([
        _control("C6", excepciones=[_exc("C6", "FE10"), _exc("C6", "FE338043")]),
        _control("IA-1", excepciones=[_exc("IA-1", "FEV21379")]),
    ])
    assert informe.documentos_con_excepcion == 3


def test_una_tasa_total_se_declara_como_asunto_de_proceso():
    """3 de 3 no son tres incidencias: es una falla de proceso."""
    informe = consolidar(
        [_control("C6", excepciones=[_exc("C6", "A"), _exc("C6", "B"),
                                     _exc("C6", "C")])],
        documentos_revisados=3)
    conclusion = informe.conclusion.lower()
    assert "3 de 3" in conclusion
    assert "proceso" in conclusion


def test_una_tasa_parcial_no_se_declara_como_falla_de_proceso():
    informe = consolidar(
        [_control("C6", excepciones=[_exc("C6", "A")])],
        documentos_revisados=10)
    assert "proceso" not in informe.conclusion.lower()
    assert "1 de 10" in informe.conclusion
