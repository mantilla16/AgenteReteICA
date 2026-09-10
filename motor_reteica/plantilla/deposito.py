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

FASES 2 y 4: caratula, checklist de insumos, declaracion y cotejo de
facturas.
    Check List             <- datos del cliente + insumos_obtenidos (C13)
    DECLARACION            <- ctx.borrador.actividades
    Validacion de facturas <- ctx.facturas (es C11 hecho papel)
"""

import warnings
from datetime import date
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
_DECLARACION = ("DECLARACION", 3, 8)
_FACTURAS = ("Validación de facturas", 27, 31)

_MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")

# La marca del checklist va en Webdings: 'a' se dibuja como un visto y 'x'
# como una equis.
_VISTO, _EQUIS, _NO_APLICA = "a", "x", "N/A"

# Fila del Check List -> rol del insumo que la respalda.
# Las que no tienen rol NO las cubre este papel: certificados que le
# practicaron y clasificacion de actividades son de otro procedimiento, y el
# auxiliar de ingresos es de AUTORRETENCION (spec 2.2, fuera de alcance).
_CHECKLIST = {
    18: "balance",
    19: "borrador",
    20: None,           # certificados de retencion que les practicaron
    21: None,           # clasificacion de actividades sujetas/no sujetas
    22: "auxiliar",
    23: None,           # libro auxiliar 135518
    24: "pago_anterior",
    25: "FUERA_DE_ALCANCE",   # libro auxiliar de ingresos -> autorretencion
}


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


def _depositar_check_list(libro, ctx) -> None:
    hoja = libro["Check List"]
    anio, mes = (int(p) for p in ctx.periodo.split("-"))

    hoja["D2"] = ctx.borrador.razon_social
    hoja["D3"] = ctx.nit
    hoja["D6"] = "Revisión Reteica"
    hoja["D7"] = _MESES[mes - 1]
    try:
        hoja["D5"] = ctx.municipio.vencimiento(ctx.periodo)
    except KeyError:
        hoja["D5"] = None

    # El motor prepara el papel, asi que firma como ELABORADO POR. NUNCA
    # llena REVISADO POR: escribir ahi un nombre seria fabricar evidencia de
    # una revision que no ha ocurrido.
    declarante = getattr(ctx.manifiesto, "declarado_por", "") if ctx.manifiesto else ""
    hoja["D10"] = declarante or "Motor de Revision de ReteICA"
    hoja["G10"] = date.today()
    hoja["D11"] = None
    hoja["G11"] = None
    hoja["D12"] = None

    for fila, rol in _CHECKLIST.items():
        if rol == "FUERA_DE_ALCANCE":
            marca = _NO_APLICA
        elif rol is None:
            marca = _EQUIS
        else:
            marca = _VISTO if rol in ctx.insumos_obtenidos else _EQUIS
        hoja.cell(row=fila, column=5, value=marca)


def _depositar_declaracion(libro, ctx) -> None:
    hoja = libro[_DECLARACION[0]]
    inicio, fin = _DECLARACION[1], _DECLARACION[2]
    _limpiar(hoja, inicio, fin, range(9, 13))

    fila = inicio
    for actividad in ctx.borrador.actividades:
        hoja.cell(row=fila, column=9, value=int(actividad.codigo))
        hoja.cell(row=fila, column=10, value=float(actividad.tarifa))
        hoja.cell(row=fila, column=11, value=int(actividad.base))
        hoja.cell(row=fila, column=12, value=int(actividad.impuesto))
        fila += 1

    hoja.cell(row=fila, column=11,
              value="=SUM(K%d:K%d)" % (inicio, max(inicio, fila - 1)))
    hoja.cell(row=fila, column=12,
              value="=SUM(L%d:L%d)" % (inicio, max(inicio, fila - 1)))


def _depositar_facturas(libro, ctx) -> None:
    """Es C11 hecho papel: base del PDF x tarifa de la cuenta contra lo
    contabilizado. La FECHA que se muestra es la del documento, no la del
    auxiliar: es lo que hace visible el desfase de FE10."""
    hoja = libro[_FACTURAS[0]]
    inicio, fin = _FACTURAS[1], _FACTURAS[2]
    _limpiar(hoja, inicio, fin, range(2, 12))

    por_referencia = {l.referencia: l for l in ctx.lineas}
    fila = inicio
    for factura in ctx.facturas or []:
        linea = por_referencia.get(factura.numero)
        tarifa = (ctx.municipio.tarifa_por_cuenta.get(linea.cuenta)
                  if linea else None)
        hoja.cell(row=fila, column=2, value=linea.documento if linea else None)
        hoja.cell(row=fila, column=3, value=factura.numero)
        hoja.cell(row=fila, column=4, value=factura.fecha)
        hoja.cell(row=fila, column=5, value=linea.tercero if linea else None)
        hoja.cell(row=fila, column=6, value=linea.concepto if linea else None)
        if factura.base is not None:
            hoja.cell(row=fila, column=7, value=int(factura.base))
        if tarifa is not None:
            hoja.cell(row=fila, column=8, value=float(tarifa))
        # El recalculo y la diferencia quedan VIVOS como formula (D11).
        hoja.cell(row=fila, column=9, value="=G%d*H%d" % (fila, fila))
        if linea is not None:
            hoja.cell(row=fila, column=10, value=int(linea.retencion))
        hoja.cell(row=fila, column=11, value="=+I%d-J%d" % (fila, fila))
        fila += 1


# NOTA sobre la traza del motor en estas celdas.
# Se intento dejar la cifra del motor como COMENTARIO de celda, para tener la
# traza sin invadir el layout de la firma. Se descarto: openpyxl crea partes
# nuevas (comments.xml, vmlDrawing) que la estrategia de fidelidad no arrastra
# y la hoja queda apuntando a una relacion inexistente -- archivo corrupto.
# Hacer la cirugia de zip para eso exigiria renumerar rIds y arriesgar
# colisiones, a cambio de un tooltip.
# No hace falta: la cifra que la formula lee esta A LA VISTA en la hoja
# BALANCE, que el propio motor deposito. La trazabilidad ya existe.


def _depositar_revision_ica(libro, ctx) -> None:
    """D11 y D12.

    D11: las referencias que cruzan hojas se anclan al SIGNIFICADO. Siguen
    siendo formulas -- el papel esta vivo -- pero ya no dependen de que la
    cuenta 2368010007 caiga justo en la fila 157 del balance.

    D12: G28 apuntaba a DECLARACION!J21, que esta vacia, y F28 estaba fija
    en 0. La fila TOTAL A PAGAR mostraba 474.000 de diferencia -- el
    impuesto entero -- dos filas encima de una conclusion que afirma que
    todo es integro. Se corrige.
    """
    hoja = libro["REVISION ICA"]
    inicio, fin = _BALANCE[1], _BALANCE[2]
    decl_ini, decl_fin = _DECLARACION[1], _DECLARACION[2]

    # Saldo del balance POR NUMERO DE CUENTA. Coincidencia exacta a
    # proposito: si la cuenta no esta, VLOOKUP devuelve #N/A -- un error
    # ruidoso. SUMIF devolveria 0 en silencio, que es justo lo que este
    # proyecto no acepta.
    for celda, cuenta in (("N12", "2368010007"), ("N13", "2368010010")):
        hoja[celda] = ('=VLOOKUP(%s,BALANCE!$C$%d:$I$%d,7,FALSE)'
                       % (cuenta, inicio, fin))

    # Totales declarados: se suman las filas que TIENEN codigo de actividad,
    # en vez de apuntar a la fila del total. Si el borrador trae 7
    # actividades en vez de 5, la formula sigue sirviendo.
    rango_codigo = "DECLARACION!$I$%d:$I$%d" % (decl_ini, decl_fin)
    hoja["F20"] = '=SUMIF(%s,">0",DECLARACION!$K$%d:$K$%d)' % (
        rango_codigo, decl_ini, decl_fin)
    hoja["G20"] = '=SUMIF(%s,">0",DECLARACION!$L$%d:$L$%d)' % (
        rango_codigo, decl_ini, decl_fin)

    # D12: la fila TOTAL A PAGAR compara contra el total declarado, no
    # contra una celda vacia.
    hoja["F28"] = "=+F26"
    hoja["G28"] = "=+G26"


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
    _depositar_check_list(libro, ctx)
    _depositar_declaracion(libro, ctx)
    _depositar_facturas(libro, ctx)
    _depositar_revision_ica(libro, ctx)

    return guardar_conservando_formato(libro, plantilla, Path(destino))
