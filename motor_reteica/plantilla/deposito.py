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
from motor_reteica.tipos import Estado

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


def _texto_de_cuenta(tarifa) -> str:
    """'Impuest ICA Reten 7%', como lo escribe SAP.

    V1 del loop de validacion: se derivaba de los ultimos digitos de la
    cuenta (cuenta[-4:]) y salia 'Impuest ICA Reten 0007'. El porcentaje sale
    de la TARIFA, no del numero de cuenta.
    """
    return "Impuest ICA Reten %g%%" % (float(tarifa) * 1000)


def _digito_de_verificacion(nit: str) -> str:
    """DV del NIT segun el algoritmo de la DIAN.

    V2 del loop: la caratula mostraba 819002433 donde el papel de la firma
    dice 819002433-6. El DV no se inventa: es una funcion del NIT, y la
    prueba lo comprueba contra el del documento real.
    """
    pesos = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
    digitos = [int(c) for c in str(nit) if c.isdigit()]
    suma = sum(d * pesos[i] for i, d in enumerate(reversed(digitos)))
    residuo = suma % 11
    return str(residuo if residuo < 2 else 11 - residuo)


def _nit_con_dv(nit: str) -> str:
    return "%s-%s" % (nit, _digito_de_verificacion(nit))


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
                  value=_texto_de_cuenta(
                      ctx.municipio.tarifa_por_cuenta.get(linea.cuenta, 0)))
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

    LAS FILAS SOBRANTES SE BORRAN, no se ocultan. La plantilla viene con 338
    de sus 345 filas de balance OCULTAS -- la firma las colapso al archivar el
    mes anterior -- y el motor escribia justo ahi, asi que el deposito
    funcionaba y la hoja se veia vacia. Ocultar las que sobran arreglaba eso
    pero dejaba la numeracion saltando de la 9 a la 350, que se lee como una
    hoja rota. Ahora se eliminan: la hoja termina donde termina la evidencia.
    Se puede borrar filas porque ninguna formula apunta ya a esta hoja -- lo
    que cruza de hoja lo deposita el motor como valor.

    SE MUESTRAN TAMBIEN LAS CUENTAS EXCLUIDAS. El papel afirmaba que
    2368010090 se trato como contrapartida de pago y esa cuenta no aparecia
    por ningun lado: la exclusion no se podia verificar. Van al final, con su
    saldo acumulado, que es la cifra por la que el motor las senala (M11).
    """
    hoja = libro[_BALANCE[0]]
    inicio, fin = _BALANCE[1], _BALANCE[2]
    _limpiar(hoja, inicio, fin, range(2, 11))

    hoja.cell(row=3, column=2,
              value="EXTRACTO de la cuenta 2368 del balance de prueba. No es "
                    "el balance completo: el motor solo verifica esas "
                    "cuentas. La columna que entra a los cruces es 'Saldo "
                    "Haber per.inf.' -- el movimiento del periodo; el saldo "
                    "acumulado se muestra solo como referencia, porque "
                    "arrastra los periodos anteriores.")

    if not ctx.saldos:
        hoja.cell(row=inicio, column=3,
                  value="NO EJECUTADO: no se obtuvo el balance de prueba")
        hoja.row_dimensions[inicio].hidden = False
        _recortar(hoja, inicio + 1, fin)
        return

    fila = inicio
    for cuenta, saldo in sorted(ctx.saldos.items()):
        hoja.row_dimensions[fila].hidden = False
        hoja.cell(row=fila, column=2, value="DA09")
        hoja.cell(row=fila, column=3, value=cuenta)
        hoja.cell(row=fila, column=4,
                  value=_texto_de_cuenta(
                      ctx.municipio.tarifa_por_cuenta.get(cuenta, 0)))
        hoja.cell(row=fila, column=5, value="COP")
        hoja.cell(row=fila, column=9, value=int(saldo))
        acumulado = ctx.acumulados.get(cuenta)
        if acumulado is not None:
            hoja.cell(row=fila, column=10, value=int(acumulado))
        fila += 1

    for cuenta in sorted(ctx.candidatas_sin_declarar):
        hoja.row_dimensions[fila].hidden = False
        hoja.cell(row=fila, column=2, value="DA09")
        hoja.cell(row=fila, column=3, value=cuenta)
        hoja.cell(row=fila, column=4,
                  value="EXCLUIDA de los cruces: saldo de naturaleza debito, "
                        "tratada como contrapartida de pago. Sin atestacion "
                        "del auditor (M11).")
        hoja.cell(row=fila, column=5, value="COP")
        acumulado = ctx.acumulados.get(cuenta)
        if acumulado is not None:
            hoja.cell(row=fila, column=10, value=int(acumulado))
        fila += 1

    _recortar(hoja, fila, fin)


def _recortar(hoja, desde: int, hasta: int) -> None:
    """Quita las filas que quedaron sin datos, de abajo hacia arriba."""
    if hasta >= desde:
        hoja.delete_rows(desde, hasta - desde + 1)


def _depositar_check_list(libro, ctx) -> None:
    hoja = libro["Check List"]
    anio, mes = (int(p) for p in ctx.periodo.split("-"))

    hoja["D2"] = ctx.borrador.razon_social
    hoja["D3"] = _nit_con_dv(ctx.nit)
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


_BORRADOR = ("BORRADOR TERLICA", 10, 27)
# Fila libre despues de la liquidacion (B40 es el ultimo texto de la
# plantilla), para avisar de los grupos que no caben sin pisar nada.
_AVISO_SIN_CUPO = 42


def _depositar_borrador_terlica(libro, ctx) -> None:
    """La reconstruccion renglon por renglon, sobre la forma del formulario.

    B1..B8 y sus tarifas son la ESTRUCTURA del formulario municipal, no dato
    nuestro: no se tocan. El motor llena las columnas de datos en la fila
    cuya tarifa corresponde al grupo.

    Si un mes trae mas grupos de una tarifa que filas disponibles para ella
    -- el caso de 3.2 en version Excel -- los que no caben se DECLARAN en la
    hoja. Descartarlos en silencio daria un papel que cuadra de menos sin
    decir por que.
    """
    hoja = libro[_BORRADOR[0]]
    inicio, fin = _BORRADOR[1], _BORRADOR[2]

    # Solo las columnas de DATOS. Esto se limpiaba desde la D y era un error:
    # D, E y F NO son datos del mes, son formulas del formulario --
    # D=+ROUND(Gn,-3), E=+ROUND(Hn,-3) y en dos filas F lleva sumas cruzadas
    # (=+G17+G16, =+G20+G21+G25). Borrarlas dejaba el formulario mutilado:
    # las columnas BASE e IMPTO RTE ICA salian vacias en toda fila que el mes
    # no llenara, y las dos sumas cruzadas desaparecian para siempre.
    #
    # Y solo hasta `fin`: de la fila 28 en adelante vive la LIQUIDACION del
    # formulario (TOTAL PAGO O ABONO, sanciones, saldo a pagar). Borrar ahi
    # destruiria la estructura del papel, no datos del mes.
    _limpiar(hoja, inicio, fin, range(7, 12))
    for columna in (4, 5, 8):
        hoja.cell(row=fin + 1, column=columna).value = None
    hoja.cell(row=_AVISO_SIN_CUPO, column=2).value = None

    # Filas disponibles por tarifa, segun la propia plantilla.
    libres = {}
    for fila in range(inicio, fin + 1):
        por_mil = hoja.cell(row=fila, column=3).value
        if isinstance(por_mil, (int, float)):
            libres.setdefault(float(por_mil), []).append(fila)

    sin_cupo = []
    ultima = inicio - 1
    for grupo in sorted(ctx.reconstruccion.por_grupo.values(),
                        key=lambda g: -g.retencion_contable):
        por_mil = float(grupo.tarifa) * 1000
        disponibles = libres.get(por_mil, [])
        if not disponibles:
            sin_cupo.append(grupo)
            continue
        fila = disponibles.pop(0)
        ultima = max(ultima, fila)

        hoja.cell(row=fila, column=8, value=int(grupo.retencion_contable))
        # D, E y G se recalculan solas a partir de H: el papel esta vivo.
        # D y E ya no se reescriben: la plantilla las trae, son suyas, y
        # escribirlas solo en las filas que el mes usa era lo que dejaba las
        # demas en blanco.
        divisor = por_mil / 10
        hoja.cell(row=fila, column=7,
                  value="=+H%d/%s*100" % (fila, ("%g" % divisor)))

        renglon = (ctx.reconstruccion.mapa or {}).get(grupo.clave)
        conceptos = [l.concepto for l in ctx.lineas if l.nit == grupo.nit]
        hoja.cell(row=fila, column=9, value=conceptos[0] if conceptos else None)
        if renglon:
            hoja.cell(row=fila, column=10, value=int(renglon))
        hoja.cell(row=fila, column=11, value=grupo.nit)

    hoja.cell(row=fin + 1, column=4, value="=SUM(D%d:D%d)" % (inicio, fin))
    hoja.cell(row=fin + 1, column=5, value="=SUM(E%d:E%d)" % (inicio, fin))
    hoja.cell(row=fin + 1, column=8, value="=SUM(H%d:H%d)" % (inicio, fin))

    if sin_cupo:
        detalle = "; ".join(
            "NIT %s al %s por mil por %s"
            % (g.nit, "%g" % (float(g.tarifa) * 1000), int(g.retencion_contable))
            for g in sin_cupo)
        hoja.cell(row=_AVISO_SIN_CUPO, column=2,
                  value="NO CUPO en la estructura del formulario: %s. "
                        "El total de arriba NO los incluye." % detalle)


def _depositar_revision_ica(libro, ctx) -> None:
    """D11 y D12.

    D11: las referencias que cruzan hojas las RESUELVE EL MOTOR y deposita el
    numero. La plantilla traia =+BALANCE!I157, que apunta a una fila concreta
    y miente el mes que el balance trae una cuenta mas. La primera solucion
    fue cambiarlas por VLOOKUP contra el numero de cuenta -- el papel seguia
    vivo -- y costo dos defectos seguidos que no tienen nada que ver con
    ReteICA: el libro se abria sin recalcular y la hoja salia en blanco, y
    cuando por fin recalculo devolvio #N/D porque el motor escribe la cuenta
    como texto y el VLOOKUP buscaba un numero.

    El motor ya hizo esa cuenta. Que Excel la repita solo agrega formas de
    fallar que no son de auditoria, y ninguna prueba puede atraparlas:
    openpyxl no evalua formulas, asi que lo unico verificable era que la
    CADENA de la formula estuviera bien escrita. Por eso la suite entera
    pasaba con el papel en blanco.

    Lo que cruza de una hoja a otra va como VALOR. Se pierde que el papel se
    recomponga solo si alguien edita el balance a mano, y eso es correcto:
    editar la evidencia deberia obligar a volver a correr, no a que el papel
    se rehaga sin que nadie lo note.

    La aritmetica DE LA FIRMA no se toca: D20 =+M21, E20 =+O12+O13, los
    =SUM de la fila 26 y los =ROUND siguen siendo formulas. Ese es su papel,
    y la derivacion tiene que quedar a la vista.

    D12: G28 apuntaba a DECLARACION!J21, que esta vacia, y F28 estaba fija
    en 0. La fila TOTAL A PAGAR mostraba 474.000 de diferencia -- el
    impuesto entero -- dos filas encima de una conclusion que afirma que
    todo es integro. Se corrige.
    """
    hoja = libro["REVISION ICA"]

    # El saldo que el motor ya leyo del balance. Si la cuenta no esta, se
    # DICE; antes el VLOOKUP daba #N/A, que era ruidoso a proposito, y un
    # cero mudo en su lugar seria justo lo que este proyecto no acepta.
    for celda, cuenta in (("N12", "2368010007"), ("N13", "2368010010")):
        saldo = ctx.saldos.get(cuenta)
        hoja[celda] = (int(saldo) if saldo is not None
                       else "NO ESTA EN EL BALANCE: %s" % cuenta)

    # Lo declarado: se suman TODAS las actividades del borrador, no la celda
    # del total de la hoja. Si el borrador trae siete actividades en vez de
    # cinco, la cifra sigue siendo la correcta, que era lo que buscaba D11.
    hoja["F20"] = sum(int(a.base) for a in ctx.borrador.actividades)
    hoja["G20"] = sum(int(a.impuesto) for a in ctx.borrador.actividades)

    # D12: la fila TOTAL A PAGAR compara contra el total declarado, no
    # contra una celda vacia.
    hoja["F28"] = "=+F26"
    hoja["G28"] = "=+G26"


# Celdas donde la plantilla trae conclusiones ESCRITAS A MANO.
_CONCLUSION_FACTURAS = ("Validación de facturas", "B33")
_CONCLUSION_GENERAL = ("REVISION ICA", "A30")


def _conclusion_de_facturas(ctx) -> str:
    """Derivada del estado de C11, nunca copiada de la plantilla.

    La plantilla dice "no se presentan diferencias en las facturas" como
    texto fijo. Dejarlo intacto hace que el papel lo afirme pase lo que pase
    -- que es la queja con la que nacio este proyecto, automatizada.
    """
    c11 = next((r for r in ctx.resultados if r.codigo == "C11"), None)
    if c11 is None:
        return "El cotejo de facturas no forma parte de esta revision."

    if c11.estado is Estado.NO_EJECUTADO:
        return ("El cotejo de facturas NO SE EJECUTO: %s. Esta hoja no "
                "respalda conclusion alguna sobre las facturas."
                % c11.detalle)

    if c11.estado is Estado.OK:
        return ("De acuerdo con el recalculo de retenciones realizado sobre "
                "las facturas fuente, no se presentan diferencias. %s"
                % c11.detalle)

    partes = ["El cotejo de facturas presenta %d excepcion(es):"
              % len(c11.excepciones)]
    for excepcion in c11.excepciones:
        partes.append("  - [%s] %s" % (excepcion.severidad.value,
                                       excepcion.descripcion))
    return "\n".join(partes)


def _depositar_conclusiones(libro, ctx) -> None:
    hoja, celda = _CONCLUSION_FACTURAS
    libro[hoja][celda] = _conclusion_de_facturas(ctx)

    # La conclusion general ya la deriva hallazgos.consolidar() del estado de
    # todos los controles, e incluye la limitacion de alcance. Se usa esa.
    hoja, celda = _CONCLUSION_GENERAL
    libro[hoja][celda] = "Conclusion: %s" % ctx.informe.conclusion


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
    _depositar_borrador_terlica(libro, ctx)
    _depositar_revision_ica(libro, ctx)
    _depositar_conclusiones(libro, ctx)

    return guardar_conservando_formato(libro, plantilla, Path(destino))
