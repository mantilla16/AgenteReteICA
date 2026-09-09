from dataclasses import replace
from decimal import Decimal

from motor_reteica.controles import (c1_formulario_cuadra, c4_recalculo,
                                     c7_tarifas_vs_estatuto, c10_redondeo)
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.reconstruccion import reconstruir
from motor_reteica.tipos import Estado

MAPA = {"800193573": "5224", "811033997": "4669", "830028245": "9903",
        "900392924": "9609", "901670478": "7490"}


def test_c1_el_formulario_cuadra_consigo_mismo(borrador):
    assert c1_formulario_cuadra(borrador, MUNICIPIO).estado is Estado.OK


def test_c1_detecta_renglon_24_alterado(borrador):
    malo = replace(borrador, renglones={**borrador.renglones, "24": Decimal("500000")})
    assert c1_formulario_cuadra(malo, MUNICIPIO).estado is Estado.FALLA


def test_c1_detecta_base_del_renglon_23_alterada(borrador):
    malo = replace(borrador, renglones={**borrador.renglones, "23": Decimal("1")})
    assert c1_formulario_cuadra(malo, MUNICIPIO).estado is Estado.FALLA


def test_c1_no_usa_la_formula_impresa_27_mas_28_mas_29(borrador):
    """El formulario imprime 31=27+28+29, que da 948.000 y es falso."""
    assert borrador.renglones["27"] + borrador.renglones["28"] != borrador.renglones["31"]
    assert c1_formulario_cuadra(borrador, MUNICIPIO).estado is Estado.OK


def test_c1_cierra_el_riesgo_m12_de_una_actividad_truncada_por_desborde_de_pagina(borrador):
    """M12: leer_borrador solo lee pdf.pages[0]. Si algun mes el cuadro C
    desbordara a una pagina real que el parser no lee, la actividad faltante
    NO pasaria en silencio: la suma de impuestos por actividad dejaria de
    cuadrar contra el renglon 24, y C1 lo cazaria ANTES de mirar la
    contabilidad, con el impacto en pesos de lo que se perdio.

    No se fabrica un PDF de dos paginas -- nunca se ha visto uno real -- se
    prueba la red de seguridad que ya existe quitando una actividad del
    borrador ya parseado, que es el efecto equivalente de una que el parser
    jamas hubiera leido."""
    faltan_una = replace(borrador, actividades=borrador.actividades[:-1])
    r = c1_formulario_cuadra(faltan_una, MUNICIPIO)
    assert r.estado is Estado.FALLA
    excepcion = next(e for e in r.excepciones if "renglon 24" in e.descripcion)
    assert excepcion.impacto_pesos == borrador.actividades[-1].impuesto


def test_c4_absorbe_el_peso_de_redondeo_del_erp(recon):
    assert c4_recalculo(recon).estado is Estado.OK


def test_c4_detecta_una_base_alterada(lineas, erp):
    """C4 compara base_ERP x tarifa contra la retencion del auxiliar."""
    alterado = [replace(f, base=Decimal("9999999")) if f.nit == "830028245" else f
                for f in erp]
    malo = reconstruir(lineas, alterado, MUNICIPIO, MAPA)
    r = c4_recalculo(malo)
    assert r.estado is Estado.FALLA
    assert r.excepciones[0].renglon == "830028245"


def test_c4_no_reacciona_a_la_retencion_del_erp(lineas, erp):
    """Alterar la retencion del ERP es asunto de C3, no de C4."""
    alterado = [replace(f, retencion=Decimal("99999")) if f.nit == "830028245" else f
                for f in erp]
    igual = reconstruir(lineas, alterado, MUNICIPIO, MAPA)
    assert c4_recalculo(igual).estado is Estado.OK


def test_c4_es_no_ejecutado_si_la_base_es_derivada(lineas):
    """Sin ERP el recalculo seria circular: no puede reportarse OK."""
    sin_erp = reconstruir(lineas, None, MUNICIPIO, MAPA)
    assert c4_recalculo(sin_erp).estado is Estado.NO_EJECUTADO


def test_c7_es_no_ejecutado_mientras_no_haya_acuerdo_municipal(borrador):
    r = c7_tarifas_vs_estatuto(borrador, MUNICIPIO)
    assert r.estado is Estado.NO_EJECUTADO
    assert "PENDIENTE_VALIDACION_ESTATUTO" in r.detalle


def test_c7_evalua_cuando_el_acuerdo_esta_cargado(borrador):
    validado = replace(MUNICIPIO, estado_tarifas="ACUERDO_004_2016")
    assert c7_tarifas_vs_estatuto(borrador, validado).estado is Estado.OK


def test_c7_detecta_tarifa_que_no_coincide_con_el_estatuto(borrador):
    validado = replace(MUNICIPIO, estado_tarifas="ACUERDO_004_2016",
                       tarifas_actividad={**MUNICIPIO.tarifas_actividad,
                                          "5224": Decimal("0.007")})
    r = c7_tarifas_vs_estatuto(borrador, validado)
    assert r.estado is Estado.FALLA
    assert r.excepciones[0].impacto_pesos > 0


def test_c10_redondeo_explica_los_561_pesos(borrador, recon):
    r = c10_redondeo(borrador, recon)
    assert r.estado is Estado.OK
    assert "561" in r.detalle
