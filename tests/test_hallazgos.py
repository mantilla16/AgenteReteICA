from dataclasses import replace
from decimal import Decimal

from motor_reteica.controles import c9_reconstruccion_vs_borrador
from motor_reteica.hallazgos import consolidar
from motor_reteica.tipos import Estado, Excepcion, ResultadoControl, Severidad


def test_c9_no_encuentra_diferencias_en_julio(recon, borrador):
    assert c9_reconstruccion_vs_borrador(recon, borrador).estado is Estado.OK


def test_c9_detecta_base_alterada_en_el_borrador(recon, borrador):
    actividades = [replace(a, base=Decimal("30000000")) if a.codigo == "5224" else a
                   for a in borrador.actividades]
    malo = replace(borrador, actividades=actividades)
    r = c9_reconstruccion_vs_borrador(recon, malo)
    assert r.estado is Estado.FALLA
    assert r.excepciones[0].renglon == "5224"


def test_c9_detecta_impuesto_alterado_y_cuantifica(recon, borrador):
    actividades = [replace(a, impuesto=Decimal("300000")) if a.codigo == "5224" else a
                   for a in borrador.actividades]
    malo = replace(borrador, actividades=actividades)
    r = c9_reconstruccion_vs_borrador(recon, malo)
    assert r.estado is Estado.FALLA
    assert r.excepciones[0].impacto_pesos == Decimal("90000")


def test_c9_detecta_actividad_ausente_en_el_borrador(recon, borrador):
    malo = replace(borrador,
                   actividades=[a for a in borrador.actividades if a.codigo != "9609"])
    assert c9_reconstruccion_vs_borrador(recon, malo).estado is Estado.FALLA


def test_un_control_no_ejecutado_impide_conclusion_limpia():
    resultados = [
        ResultadoControl("C9", "Reconstruccion vs borrador", Estado.OK, ""),
        ResultadoControl("C7", "Tarifas vs estatuto", Estado.NO_EJECUTADO,
                         "PENDIENTE_VALIDACION_ESTATUTO"),
    ]
    informe = consolidar(resultados)
    assert informe.puede_concluir_limpio is False
    assert "C7" in informe.conclusion


def test_los_hallazgos_van_antes_que_las_observaciones():
    resultados = [ResultadoControl("C6", "Clasificacion", Estado.FALLA, "", excepciones=(
        Excepcion(Severidad.OBSERVACION, "C6", "actividad 7112 vs 7490", "7490",
                  Decimal("0")),
        Excepcion(Severidad.HALLAZGO, "C6", "tarifa incorrecta", "5224",
                  Decimal("120000")),
    ))]
    informe = consolidar(resultados)
    assert informe.excepciones_ordenadas[0].severidad is Severidad.HALLAZGO
    assert informe.impacto_total == Decimal("120000")


def test_conclusion_limpia_solo_con_todo_en_ok():
    resultados = [ResultadoControl("C%d" % i, "x", Estado.OK, "") for i in range(1, 10)]
    assert consolidar(resultados).puede_concluir_limpio is True


def test_la_conclusion_siempre_declara_la_limitacion_de_integridad():
    informe = consolidar([ResultadoControl("C9", "x", Estado.OK, "")])
    assert "integridad" in informe.conclusion.lower()
