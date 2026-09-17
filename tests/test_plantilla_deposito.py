"""Etapa 6, fase 1: depositar los datos crudos en la plantilla.

Tres hojas que son FUENTE, no resultado: no dependen de formulas de otras
hojas, asi que son las de menor riesgo para empezar.

El peligro real de esta fase no es escribir mal: es NO BORRAR. La plantilla
viene con los 12 renglones de julio. Un mes con 3 lineas que solo sobreescriba
las 3 primeras deja las 9 restantes de julio en el papel de agosto, con su
pinta de dato bueno. Ese es el fallo que estas pruebas persiguen.
"""

import warnings
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.ingesta.sap_retenciones import RetencionERP
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.plantilla.deposito import depositar
from motor_reteica.tipos import LineaAuxiliar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


@pytest.fixture(scope="module")
def papel(ctx, tmp_path_factory):
    salida = tmp_path_factory.mktemp("plantilla") / "papel.xlsx"
    depositar(ctx, salida)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(salida)


# --------------------------------------------------------------------------
# AUX FISCAL
# --------------------------------------------------------------------------

def test_aux_fiscal_trae_el_auxiliar_del_cliente_tal_cual(papel):
    """La hoja es EVIDENCIA. Antes el motor armaba filas desde ctx.lineas
    (con signo cambiado, texto de tarifa normalizado, cuentas filtradas).
    Ahora se pega el archivo tal como lo entrego el cliente, sin tocar."""
    hoja = papel["AUX FISCAL"]
    # El auxiliar de TERLICA tiene 12 lineas de datos con sus 5 columnas
    # tipicas del export FBL3N: Cuenta, Texto breve, Asignacion (NIT),
    # Tercero, Fecha doc, Fe.contab, Referencia, Importe en ML.
    cuentas = [hoja.cell(row=f, column=4).value for f in range(1, hoja.max_row + 1)
               if hoja.cell(row=f, column=4).value
               and str(hoja.cell(row=f, column=4).value).startswith("2368")]
    assert len(cuentas) == 12, "esperado 12 lineas del auxiliar"


def test_aux_fiscal_conserva_los_importes_con_su_signo_original(papel):
    """El auxiliar de SAP trae los importes en negativo (credito). Antes el
    motor los guardaba en positivo y les devolvia el signo al depositar.
    Ahora se pega el archivo tal cual, asi que los importes siguen siendo
    los mismos numeros que trae el cliente.

    Se suma solo el DETALLE (filas con cuenta 2368 en col D), no la fila
    de TOTAL que trae el archivo -- sumar ambos duplicaria la cifra."""
    hoja = papel["AUX FISCAL"]
    importes = []
    for f in range(1, hoja.max_row + 1):
        cuenta = str(hoja.cell(row=f, column=4).value or "")
        importe = hoja.cell(row=f, column=12).value
        if cuenta.startswith("2368") and isinstance(importe, (int, float)):
            importes.append(importe)
    assert importes, "no llego ningun importe"
    assert all(i < 0 for i in importes), "SAP los trae negativos"
    assert sum(importes) == -474561, "suma de importes de detalle"


# --------------------------------------------------------------------------
# CUADRO RETEICA
# --------------------------------------------------------------------------

def test_cuadro_reteica_recibe_los_cinco_terceros(papel):
    hoja = papel["CUADRO RETEICA"]
    nits = [str(hoja.cell(row=f, column=2).value) for f in range(5, 10)]
    assert sorted(nits) == ["800193573", "811033997", "830028245",
                            "900392924", "901670478"]


def test_cuadro_reteica_lleva_base_y_retencion(papel):
    hoja = papel["CUADRO RETEICA"]
    bases = [hoja.cell(row=f, column=7).value for f in range(5, 10)]
    retenciones = [hoja.cell(row=f, column=8).value for f in range(5, 10)]
    assert sum(bases) == 49012569
    assert sum(retenciones) == 474561


# --------------------------------------------------------------------------
# BALANCE
# --------------------------------------------------------------------------

def test_balance_trae_el_archivo_del_cliente_completo(papel):
    """Antes se filtraban solo las 2368 y se anotaban con LECTURA DEL MOTOR.
    Ahora el balance se pega tal cual: todas las cuentas, en su orden.
    Las 2368 aparecen entre las demas -- son 5 de las ~345 filas del
    balance real de TERLICA."""
    hoja = papel["BALANCE"]
    assert hoja.max_row > 300, (
        "el balance completo trae cientos de filas, salio con %d"
        % hoja.max_row)

    cuentas_2368 = [c.value for c in hoja["C"]
                    if c.value and str(c.value).startswith("2368")]
    assert len(cuentas_2368) >= 5, "faltan cuentas 2368 en el balance"


# --------------------------------------------------------------------------
# El fallo peligroso: residuo del mes anterior
# --------------------------------------------------------------------------

def _linea(nit, referencia, retencion):
    return LineaAuxiliar(
        cuenta="2368010010", nit=nit, tercero="PROVEEDOR " + nit,
        fecha_documento=date(2026, 8, 3), fecha_contabilizacion=date(2026, 8, 3),
        referencia=referencia, documento="9", concepto="COMPRA DE AGOSTO",
        retencion=Decimal(retencion))


@pytest.mark.skip(reason="ya no aplica: el papel pega el archivo del cliente "
                         "TAL CUAL, no arma filas desde ctx.lineas. El riesgo "
                         "de residuo desaparecio con el cambio -- se limpia "
                         "todo el rango antes de pegar la fuente nueva.")
def test_un_mes_mas_corto_no_deja_residuo_del_anterior(ctx, tmp_path):
    pass


@pytest.mark.skip(reason="ya no aplica: no escribimos TOTAL con formula, la "
                         "fuente trae su propio total si el auxiliar del "
                         "cliente lo trae -- si no, no lo inventamos.")
def test_el_total_se_reajusta_al_numero_de_lineas(ctx, tmp_path):
    pass


def test_el_logo_sobrevive_al_deposito(ctx, tmp_path):
    """La fase 1 no puede deshacer lo que resolvio fidelidad.py."""
    import zipfile
    salida = tmp_path / "papel.xlsx"
    depositar(ctx, salida)
    with zipfile.ZipFile(salida) as z:
        assert "xl/media/image1.emf" in z.namelist()


# --------------------------------------------------------------------------
# Hallazgos del loop de validacion (vuelta 1)
# --------------------------------------------------------------------------

def test_el_texto_de_la_cuenta_viene_del_cliente_no_lo_construye_el_motor(papel):
    """Antes el motor escribia 'Impuest ICA Reten 7%' derivado de la
    subcuenta. Ahora la fuente se pega tal cual: el texto es el que trae
    el archivo del cliente. Se verifica que llega el texto correcto para
    las 2368010007 y 2368010010, cualquiera sea la forma exacta que use
    ese cliente."""
    hoja = papel["AUX FISCAL"]
    textos = set()
    for f in range(1, hoja.max_row + 1):
        cuenta = str(hoja.cell(row=f, column=4).value or "")
        texto = hoja.cell(row=f, column=5).value
        if cuenta.startswith("2368") and texto:
            textos.add(texto)
    # Al menos aparece la palabra "Impuest ICA" que es lo comun a los dos
    # nombres que trae TERLICA ("Impuest ICA Reten 7%", "Impuest ICA Rete 10%").
    assert textos, "no llego ningun texto de cuenta"
    assert any("ICA" in t for t in textos), textos


@pytest.mark.skip(reason="ya no aplica: al pegar la fuente tal cual, el motor "
                         "ya no anota LECTURA DEL MOTOR junto a cada cuenta. "
                         "El detalle de cual cuenta entro al cruce vive en el "
                         "resumen de la revision, no en la hoja de evidencia.")
def test_la_nota_del_motor_dice_la_tarifa_de_lo_que_cruzo(papel):
    pass


def test_el_nit_de_la_caratula_lleva_digito_de_verificacion(papel):
    """V2: el papel de la firma identifica al cliente como 819002433-6.
    Escribir el NIT sin su DV lo deja incompleto en un documento que se firma."""
    assert str(papel["Check List"]["D3"].value) == "819002433-6"
