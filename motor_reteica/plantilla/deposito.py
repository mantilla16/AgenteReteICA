"""Etapa 6: depositar los datos del motor en la plantilla real de la firma.

El papel final no lo inventa el motor: es la plantilla que la firma ya usa,
con sus 9 hojas, su logo y su configuracion de impresion. El motor deposita
en ella lo que calculo.

REGLA DE ORO DE ESTE MODULO: BORRAR ANTES DE ESCRIBIR.
La plantilla llega con los 12 renglones de julio. Un mes con 3 lineas que
solo sobreescriba las 3 primeras deja las 9 de julio en el papel de agosto,
con toda la pinta de dato bueno. Es el fallo mas peligroso de esta etapa
porque no rompe nada: produce un papel plausible y equivocado.

FASE 1 (aqui): las tres hojas que son FUENTE y no resultado -- no dependen de
formulas de otras hojas.
    AUX FISCAL      <- ctx.lineas
    CUADRO RETEICA  <- ctx.filas_erp
    BALANCE         <- ctx.saldos (extracto de la cuenta 2368)
"""

import warnings
from pathlib import Path

import openpyxl
from openpyxl.cell.cell import MergedCell

from motor_reteica.plantilla.fidelidad import guardar_conservando_formato

PLANTILLA = Path(__file__).parent / "PT_ReteICA_plantilla.xlsx"

# (hoja, primera fila de datos, ultima fila que la plantilla trae ocupada)
# La ultima fila importa para BORRAR: es hasta donde puede haber residuo.
_AUX_FISCAL = ("AUX FISCAL", 7, 19)      # 19 incluye la fila TOTAL
_CUADRO = ("CUADRO RETEICA", 5, 10)      # 10 incluye la fila de sumas
_BALANCE = ("BALANCE", 5, 349)


def _escribible(celda) -> bool:
    """Una celda combinada solo acepta escritura en su ancla.

    Las tres hojas de esta fase traen celdas combinadas (encabezados,
    titulos). Escribir en una que no es el ancla lanza AttributeError.
    """
    return not isinstance(celda, MergedCell)


def _limpiar(hoja, desde: int, hasta: int, columnas: range) -> None:
    for fila in range(desde, hasta + 1):
        for columna in columnas:
            celda = hoja.cell(row=fila, column=columna)
            if _escribible(celda):
                celda.value = None


def _fecha(valor) -> str:
    """SAP las escribe como texto dd.mm.aaaa y asi las lee el auditor."""
    return valor.strftime("%d.%m.%Y")


def _depositar_aux_fiscal(libro, ctx) -> None:
    hoja = libro[_AUX_FISCAL[0]]
    inicio, fin = _AUX_FISCAL[1], _AUX_FISCAL[2]
    _limpiar(hoja, inicio, fin, range(2, 16))

    fila = inicio
    for linea in ctx.lineas:
        hoja.cell(row=fila, column=2, value=linea.cuenta)
        hoja.cell(row=fila, column=3,
                  value="Impuest ICA Reten %s" % linea.cuenta[-4:])
        hoja.cell(row=fila, column=4, value=linea.nit)
        hoja.cell(row=fila, column=5, value=linea.tercero)
        hoja.cell(row=fila, column=6, value=_fecha(linea.fecha_documento))
        hoja.cell(row=fila, column=7, value=_fecha(linea.fecha_contabilizacion))
        hoja.cell(row=fila, column=8, value=linea.referencia)
        # El auxiliar de SAP trae los importes en NEGATIVO (naturaleza
        # credito). El motor los normaliza a positivo para calcular; al
        # depositarlos se les devuelve el signo, o el papel deja de
        # parecerse al documento del cliente.
        hoja.cell(row=fila, column=9, value=-int(linea.retencion))
        hoja.cell(row=fila, column=10, value=int(ctx.periodo.split("-")[1]))
        hoja.cell(row=fila, column=11, value="RE")
        hoja.cell(row=fila, column=12, value=linea.documento)
        hoja.cell(row=fila, column=13, value=linea.concepto)
        hoja.cell(row=fila, column=15, value="DA09")
        fila += 1

    # El total se mueve con el numero de lineas: dejarlo en la fila 19 fija
    # lo dejaria sumando un rango que ya no corresponde.
    hoja.cell(row=fila, column=2, value="TOTAL")
    hoja.cell(row=fila, column=9,
              value="=SUM(I%d:I%d)" % (inicio, max(inicio, fila - 1)))


def _depositar_cuadro_reteica(libro, ctx) -> None:
    hoja = libro[_CUADRO[0]]
    inicio, fin = _CUADRO[1], _CUADRO[2]
    _limpiar(hoja, inicio, fin, range(2, 10))

    fila = inicio
    for registro in ctx.filas_erp or []:
        hoja.cell(row=fila, column=2, value=registro.nit)
        hoja.cell(row=fila, column=3, value="IS")
        hoja.cell(row=fila, column=4, value=int(registro.codigo_ret))
        hoja.cell(row=fila, column=7, value=int(registro.base))
        hoja.cell(row=fila, column=8, value=int(registro.retencion))
        fila += 1

    hoja.cell(row=fila, column=7,
              value="=SUM(G%d:G%d)" % (inicio, max(inicio, fila - 1)))
    hoja.cell(row=fila, column=8,
              value="=SUM(H%d:H%d)" % (inicio, max(inicio, fila - 1)))


def _depositar_balance(libro, ctx) -> None:
    """Solo las cuentas 2368, y el papel lo dice.

    El motor unicamente valida esas cuentas (C2). Depositar las 349 filas del
    balance completo pondria en el papel cifras que nunca miro, dando a
    entender que las reviso.
    """
    hoja = libro[_BALANCE[0]]
    inicio, fin = _BALANCE[1], _BALANCE[2]
    _limpiar(hoja, inicio, fin, range(2, 11))

    hoja.cell(row=3, column=2,
              value="EXTRACTO de la cuenta 2368 del balance de prueba. No es "
                    "el balance completo: el motor solo verifica esas cuentas.")

    if not ctx.saldos:
        hoja.cell(row=inicio, column=3,
                  value="NO EJECUTADO: no se obtuvo el balance de prueba")
        return

    fila = inicio
    for cuenta, saldo in sorted(ctx.saldos.items()):
        hoja.cell(row=fila, column=2, value="DA09")
        hoja.cell(row=fila, column=3, value=cuenta)
        hoja.cell(row=fila, column=4,
                  value="Impuest ICA Reten %s" % cuenta[-4:])
        hoja.cell(row=fila, column=5, value="COP")
        hoja.cell(row=fila, column=9, value=int(saldo))
        fila += 1


def depositar(ctx, destino, plantilla: Path = None) -> Path:
    """Escribe el papel final a partir de la plantilla de la firma."""
    plantilla = Path(plantilla or PLANTILLA)
    with warnings.catch_warnings():
        # openpyxl avisa que descarta el EMF al cargar; fidelidad.py lo
        # restituye al guardar, asi que el aviso aqui es ruido.
        warnings.simplefilter("ignore")
        libro = openpyxl.load_workbook(plantilla)

    _depositar_aux_fiscal(libro, ctx)
    _depositar_cuadro_reteica(libro, ctx)
    _depositar_balance(libro, ctx)

    return guardar_conservando_formato(libro, plantilla, Path(destino))
