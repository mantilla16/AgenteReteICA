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
from decimal import Decimal
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


_COLUMNAS_AUX_FISCAL = (
    # (etiquetas aceptadas, columna destino 1-based)
    (("Cuenta",),                                       2),   # B
    (("Texto breve", "Texto"),                          3),   # C
    (("Asignación", "Asignacion"),                      4),   # D
    (("Tercero",),                                      5),   # E
    (("Fecha doc.",),                                   6),   # F
    (("Fe.contab.",),                                   7),   # G
    (("Referencia",),                                   8),   # H
    (("Importe en ML", "Importe en moneda local"),      9),   # I
    (("Período", "Periodo"),                           10),   # J
    (("Cla",),                                         11),   # K
    (("Nº doc.", "N° doc."),                           12),   # L
    (("Texto largo", "Texto de cabecera de documento"), 13),  # M  (opcional)
    (("Importe valorado ML2",),                        14),   # N
    (("Soc.", "Sociedad"),                             15),   # O
)


def _depositar_aux_fiscal(libro, ctx) -> None:
    """El auxiliar del cliente, alineado a las columnas del papel.

    Antes se copiaba posicion por posicion y las columnas caian corridas:
    Cuenta aterrizaba en D en vez de B, y las ultimas columnas (Texto,
    ML2, Sociedad) se perdian por el limite del rango. Ahora se hace lo
    que el auditor haria a mano: se identifica el encabezado del archivo,
    cada etiqueta conocida se ubica en la columna que la plantilla tiene
    fijada, y las columnas del archivo sin etiqueta reconocida se
    descartan.

    La hoja sigue siendo EVIDENCIA: se pega lo que entrego el cliente,
    solo se corrige la ubicacion.
    """
    hoja = libro[_AUX_FISCAL[0]]
    inicio, fin = _AUX_FISCAL[1], _AUX_FISCAL[2]
    _limpiar(hoja, inicio, fin, range(1, 16))
    _pegar_alineado(hoja, (ctx.rutas or {}).get("auxiliar"),
                    inicio, fin, _COLUMNAS_AUX_FISCAL,
                    marca_encabezado="Cuenta")


def _depositar_cuadro_reteica(libro, ctx) -> None:
    """El reporte del ERP, transcrito completo.

    Antes se escribian solo 4 columnas -- las que usan los cruces -- y el
    resto quedaba en blanco. El papel del auditor pega las 8 que trae el
    export, y una de ellas (Impte.neto 2 MI) es la BASE SUJETA de la
    retencion: sin ella, el que revisa no puede recalcular la tarifa efectiva
    ni confirmar que la retencion practicada corresponde a lo que se le pago
    al tercero.

    Se transcribe la fuente tal cual, con el mismo criterio del BALANCE: es
    evidencia, no una seleccion.
    """
    hoja = libro[_CUADRO[0]]
    inicio, fin = _CUADRO[1], _CUADRO[2]
    _limpiar(hoja, inicio, fin, range(2, 10))

    if _transcribir_erp(hoja, ctx, inicio, fin):
        return

    # Sin ruta al archivo -- CLI vieja, o pruebas antiguas -- se cae al
    # deposito minimo: no rompe, solo escribe menos columnas.
    fila = inicio
    for registro in ctx.filas_erp or []:
        hoja.cell(row=fila, column=2, value=registro.nit)
        hoja.cell(row=fila, column=3, value="IS")
        hoja.cell(row=fila, column=4, value=int(registro.codigo_ret))
        hoja.cell(row=fila, column=7, value=int(registro.base))
        hoja.cell(row=fila, column=8, value=int(registro.retencion))
        fila += 1
    ultima = max(inicio, fila - 1)
    hoja.cell(row=fila, column=7, value="=SUM(G%d:G%d)" % (inicio, ultima))
    hoja.cell(row=fila, column=8, value="=SUM(H%d:H%d)" % (inicio, ultima))


def _transcribir_erp(hoja, ctx, inicio: int, fin: int) -> bool:
    """Vuelca el reporte del ERP completo, columna por columna.

    Como con el balance: el papel de trabajo ES la evidencia. El auditor
    verifica la retencion practicada comparando importe con base sujeta, y
    ambas viven en columnas que el motor descartaba al leer.
    """
    ruta = (ctx.rutas or {}).get("erp")
    if not ruta:
        return False

    try:
        from motor_reteica.ingesta._io import leer_filas
        from motor_reteica.parametros.columnas import (FIRMA_ERP, ROLES_ERP,
                                                       localizar_columnas)
        filas = leer_filas(ruta)
        encabezado, _ = localizar_columnas(filas, ROLES_ERP, FIRMA_ERP)
    except Exception:
        return False

    datos = [f for f in filas[encabezado + 1:]
             if any(c not in (None, "") for c in f)
             and any(_texto_no_vacio(c) for c in f[1:4])]
    if not datos:
        return False

    _escribir_fila(hoja, inicio - 1, filas[encabezado])

    # Dinamico: la ultima fila (fin) esta reservada para las sumas. Si hay
    # mas terceros que filas disponibles (fin - inicio), se INSERTAN filas
    # antes de la de sumas -- se empuja hacia abajo. openpyxl.insert_rows
    # actualiza los merges; las sumas se reescriben con el rango correcto
    # despues del ajuste.
    disponibles = fin - inicio
    if len(datos) > disponibles:
        extra = len(datos) - disponibles
        hoja.insert_rows(fin, extra)
        fin = fin + extra

    fila = inicio
    for origen in datos:
        hoja.row_dimensions[fila].hidden = False
        _escribir_fila(hoja, fila, origen)
        fila += 1

    # Sumas para las dos columnas que ya venian sumadas en la plantilla.
    ultima = max(inicio, fila - 1)
    hoja.cell(row=fila, column=7,
              value="=SUM(G%d:G%d)" % (inicio, ultima))
    hoja.cell(row=fila, column=8,
              value="=SUM(H%d:H%d)" % (inicio, ultima))
    return True


def _texto_no_vacio(valor) -> bool:
    return valor not in (None, "") and str(valor).strip() != ""


_COLUMNAS_BALANCE = (
    # (etiquetas aceptadas, columna destino 1-based)
    (("Soc.", "Sociedad"),                             2),   # B
    (("Cta.mayor",),                                   3),   # C
    (("Texto breve", "Texto"),                         4),   # D
    (("Mon.", "Moneda"),                               5),   # E
    (("Arrastre de saldos",),                          6),   # F
    (("Saldo per.anteriores",),                        7),   # G
    (("Período de informe debe", "Periodo de informe debe"), 8),   # H
    (("Saldo Haber per.inf.",),                        9),   # I
    (("Saldo acumulado",),                            10),   # J
)


def _depositar_balance(libro, ctx) -> None:
    """El balance del cliente, alineado a las columnas del papel.

    El export de SAP trae columnas separadoras vacias (los 'Div.' y los
    dropdowns intercalados) entre los datos utiles. Copiar posicion por
    posicion metia los saldos en cualquier columna de la hoja y rompia la
    lectura. Aca se hace lo que el auditor haria a mano: se detecta el
    encabezado en el archivo, se identifica de que columna sale cada dato
    por SU ETIQUETA, y se pega en la columna que la plantilla tiene fijada
    para ese dato. Las columnas del archivo que no correspondan a ninguna
    etiqueta conocida se descartan (son separadores del export).

    Ademas, la guia del auditor especifica:
      - Pegar el balance completo (evidencia).
      - Autofiltro en el encabezado, para que el que revisa pueda filtrar
        por 'Cta.mayor que empiece por 2368' y ver solo las cuentas ICA.
      - Fila de subtotal al final con SUBTOTAL(9,...) sobre las columnas de
        movimiento del periodo.
    """
    hoja = libro[_BALANCE[0]]
    inicio, fin = _BALANCE[1], _BALANCE[2]
    _limpiar(hoja, inicio, fin, range(1, 16))
    ultima = _pegar_alineado(hoja, (ctx.rutas or {}).get("balance"),
                             inicio, fin, _COLUMNAS_BALANCE,
                             marca_encabezado="Cta.mayor")
    if ultima is None:
        return
    _sellar_balance_con_subtotales(hoja, encabezado=inicio - 1,
                                   primera_dato=inicio, ultima_dato=ultima)


def _pegar_alineado(hoja, ruta, inicio: int, fin: int,
                    columnas_destino, marca_encabezado: str):
    """Pega la fuente con las columnas alineadas al layout de la plantilla.

    `columnas_destino`: tupla de (etiquetas_alias, columna_destino_1based).
    `marca_encabezado`: etiqueta que identifica la fila de encabezado del
      archivo (ej. 'Cta.mayor' para balance, 'Cuenta' para auxiliar).

    Devuelve el numero de la ultima fila escrita, o None si no hubo datos.
    """
    if not ruta:
        hoja.cell(row=inicio, column=2,
                  value="NO SE APORTO EL ARCHIVO DEL CLIENTE")
        _recortar(hoja, inicio + 1, fin)
        return None

    try:
        from motor_reteica.ingesta._io import leer_filas
        filas = leer_filas(ruta)
    except Exception as error:
        hoja.cell(row=inicio, column=2,
                  value="NO SE PUDO LEER EL ARCHIVO: %s" % error)
        _recortar(hoja, inicio + 1, fin)
        return None

    while filas and not any(c not in (None, "") for c in filas[-1]):
        filas.pop()
    if not filas:
        _recortar(hoja, inicio, fin)
        return None

    idx_encabezado, mapa = _mapear_columnas(filas, columnas_destino,
                                            marca_encabezado)
    if mapa is None:
        # Sin encabezado reconocible: se cae al comportamiento anterior para
        # no dejar la hoja vacia. La suite de tests exige al menos que se
        # pegue algo.
        return _pegar_fuente_completa(hoja, ruta, inicio, fin)

    _escribir_encabezado_alineado(hoja, inicio - 1, mapa, filas[idx_encabezado])

    datos = filas[idx_encabezado + 1:]
    while datos and _es_subtotal_del_final(datos[-1]):
        datos.pop()
    datos = [d for d in datos if any(c not in (None, "") for c in d)]

    # Dinamico: si el archivo trae mas filas de las que la plantilla tenia
    # reservadas, se INSERTAN antes de recortar. El auditor exigio que no
    # se omita informacion nunca; truncar era una decision del motor, no
    # una limitacion real de Excel. openpyxl.insert_rows corre para abajo
    # cualquier contenido que hubiera despues; no hay formulas de la
    # plantilla que apunten a AUX FISCAL/BALANCE/CUADRO, verificado.
    necesarias = len(datos)
    disponibles = fin - inicio + 1
    if necesarias > disponibles:
        extra = necesarias - disponibles
        hoja.insert_rows(fin + 1, extra)
        fin = fin + extra

    fila = inicio
    for origen in datos:
        hoja.row_dimensions[fila].hidden = False
        for col_origen, col_destino in mapa.items():
            if col_origen >= len(origen):
                continue
            celda = hoja.cell(row=fila, column=col_destino)
            if _escribible(celda):
                celda.value = origen[col_origen]
        fila += 1

    _recortar(hoja, fila, fin)
    ultima = fila - 1
    return ultima if ultima >= inicio else None


def _mapear_columnas(filas, columnas_destino, marca: str) -> tuple:
    """Devuelve (indice_de_fila_encabezado, {col_origen: col_destino}).

    Recorre las primeras 15 filas buscando la que contenga `marca` como
    encabezado. Dentro de ella, cada etiqueta conocida se resuelve a la
    columna destino que la plantilla tiene fijada. Etiquetas no
    reconocidas se descartan (son separadores u otras columnas del
    export que la plantilla no reserva).
    """
    for indice, fila in enumerate(filas[:15]):
        etiquetas = {}
        for pos, celda in enumerate(fila):
            texto = str(celda).strip() if celda is not None else ""
            if texto:
                etiquetas[texto] = pos
        if marca not in etiquetas:
            continue
        mapa = {}
        for alias, destino in columnas_destino:
            for etiqueta in alias:
                if etiqueta in etiquetas:
                    mapa[etiquetas[etiqueta]] = destino
                    break
        return indice, mapa
    return 0, None


def _escribir_encabezado_alineado(hoja, fila: int, mapa: dict,
                                  encabezados) -> None:
    for col_origen, col_destino in mapa.items():
        if col_origen >= len(encabezados):
            continue
        celda = hoja.cell(row=fila, column=col_destino)
        if _escribible(celda):
            celda.value = encabezados[col_origen]


def _sellar_balance_con_subtotales(hoja, encabezado: int,
                                   primera_dato: int, ultima_dato: int) -> None:
    """Agrega autofiltro y subtotales al final del balance pegado.

    Columnas convencionales del export de SAP 'Saldos de cuentas de mayor':
      B Sociedad · C Cta.mayor · D Texto · E Moneda
      F Arrastre · G Saldo per.anteriores
      H Periodo de informe DEBE · I Saldo Haber per.inf. · J Saldo acumulado

    El rango del subtotal se acota al BLOQUE DE RETENCIONES (cuentas que
    empiezan por 236), no todo el balance. Motivo: el balance suele traer
    una fila de TOTAL GENERAL de SAP al final; incluirla en un SUM sin
    filtro daria el doble del total real. SUBTOTAL(9,...) respeta el filtro
    del auditor por 2368, pero acotar el rango sirve por si nadie filtra.
    """
    if ultima_dato < primera_dato:
        return

    inicio_ret, fin_ret = _rango_de_retenciones(hoja, primera_dato, ultima_dato)
    if inicio_ret is None:
        # No hay cuentas 236 en el balance -- muy raro para un papel de
        # ReteICA, pero se cubre el rango entero para no dejar la fila
        # de subtotal apuntando a nada.
        inicio_ret, fin_ret = primera_dato, ultima_dato

    fila_sub = ultima_dato + 1
    for columna in ("H", "I"):
        hoja["%s%d" % (columna, fila_sub)] = (
            "=SUBTOTAL(9,%s%d:%s%d)"
            % (columna, inicio_ret, columna, fin_ret))
    hoja["J%d" % fila_sub] = "=I%d-H%d" % (fila_sub, fila_sub)

    # Autofiltro: cubre el encabezado y todas las filas de datos, no la de
    # subtotal (SUBTOTAL respeta el filtro; incluir la fila del subtotal
    # dentro del rango filtrable la ocultaria al filtrar).
    hoja.auto_filter.ref = "B%d:J%d" % (encabezado, ultima_dato)


def _rango_de_retenciones(hoja, desde: int, hasta: int) -> tuple:
    """Primera y ultima fila cuya Cta.mayor (col C) empiece por '236'.

    236x cubre TODAS las cuentas de retenciones: 2365 fuente, 2367 IVA,
    2368 ICA. El subtotal cubre el bloque completo y el filtro del auditor
    lo acota al 2368 cuando quiere solo ICA.
    """
    primera = ultima = None
    for f in range(desde, hasta + 1):
        cuenta = hoja.cell(row=f, column=3).value
        if cuenta and str(cuenta).startswith("236"):
            if primera is None:
                primera = f
            ultima = f
    return primera, ultima


def _pegar_fuente_completa(hoja, ruta, inicio: int, fin: int) -> None:
    """Copia el archivo del cliente TAL CUAL en la hoja del papel.

    - Cada fila se copia posicion por posicion (A -> A, B -> B, ...), sin
      reordenar ni interpretar. Es lo que hace el auditor a mano.
    - El encabezado va en la fila anterior a `inicio`, para respetar la
      forma de la plantilla (banner en la parte superior).
    - Las filas que sobren se BORRAN, no se ocultan: la hoja termina donde
      termina la evidencia. Ninguna formula del papel apunta a esta hoja.

    Si no hay ruta o no se puede leer, la hoja queda con el area limpia y un
    aviso de que faltaba el archivo -- el papel no se cae por la evidencia.
    """
    if not ruta:
        hoja.cell(row=inicio, column=2,
                  value="NO SE APORTO EL ARCHIVO DEL CLIENTE")
        _recortar(hoja, inicio + 1, fin)
        return None

    try:
        from motor_reteica.ingesta._io import leer_filas
        filas = leer_filas(ruta)
    except Exception as error:
        hoja.cell(row=inicio, column=2,
                  value="NO SE PUDO LEER EL ARCHIVO: %s" % error)
        _recortar(hoja, inicio + 1, fin)
        return None

    # Descarta filas totalmente vacias al final (algunos exports dejan
    # muchas). Las intermedias vacias se conservan porque el auditor las
    # espera para leer bien la estructura.
    while filas and not any(c not in (None, "") for c in filas[-1]):
        filas.pop()
    if not filas:
        _recortar(hoja, inicio, fin)
        return None

    # El encabezado (primera fila con etiquetas) va justo arriba del area.
    # Se detecta por heuristica: primera fila que tenga varias celdas no
    # vacias en las primeras columnas.
    encabezado = _detectar_encabezado(filas)

    if encabezado > 0:
        _escribir_fila(hoja, inicio - 1, filas[encabezado])

    # Las filas totalmente vacias del origen se saltan: SAP y otros ERP dejan
    # filas en blanco entre metadatos y detalle. Contarlas contra el rango
    # deja los ultimos movimientos por fuera de la hoja, que es peor que
    # perder la disposicion exacta -- la evidencia debe estar completa.
    # Al final del archivo se descartan filas que sean "solo numeros al
    # final" -- tipicamente subtotales calculados por el auditor que se
    # colaron. Los detecto por: no tienen ni sociedad (col B) ni cuenta (col
    # C) pero si numeros en columnas del medio. No se filtran en el interior:
    # ahi un vacio puntual es del cliente, y descartar seria alterar la
    # evidencia.
    filas_de_datos = filas[encabezado + 1:]
    while filas_de_datos and _es_subtotal_del_final(filas_de_datos[-1]):
        filas_de_datos.pop()
    filas_de_datos = [f for f in filas_de_datos
                      if any(c not in (None, "") for c in f)]

    # Dinamico: mismo criterio que en _pegar_alineado. Nunca truncar.
    necesarias = len(filas_de_datos)
    disponibles = fin - inicio + 1
    if necesarias > disponibles:
        extra = necesarias - disponibles
        hoja.insert_rows(fin + 1, extra)
        fin = fin + extra

    fila = inicio
    for origen in filas_de_datos:
        hoja.row_dimensions[fila].hidden = False
        _escribir_fila(hoja, fila, origen)
        fila += 1

    _recortar(hoja, fila, fin)
    # Devuelve el numero de la ultima fila escrita (o None si no hubo datos).
    # El llamador puede usarla para agregar totales o autofiltros que
    # dependen del rango real, no del limite duro del rango de la plantilla.
    ultima = fila - 1
    return ultima if ultima >= inicio else None


def _es_subtotal_del_final(fila) -> bool:
    """Fila que trae numeros pero ni sociedad ni cuenta identificable.

    En un balance de SAP las columnas B y C llevan Sociedad y Cta.mayor;
    una fila sin ninguna de esas dos pero con numeros mas adelante es un
    subtotal calculado a mano en el papel del que salio el archivo. No es
    un dato: es residuo del papel anterior.
    """
    if not fila or len(fila) < 3:
        return False
    b = fila[1] if len(fila) > 1 else None
    c = fila[2] if len(fila) > 2 else None
    if (b not in (None, "")) or (c not in (None, "")):
        return False
    return any(isinstance(v, (int, float)) for v in fila)


def _detectar_encabezado(filas) -> int:
    """La primera fila que trae >= 3 celdas con texto de encabezado.

    En SAP la fila del encabezado va precedida de un banner (titulo, sociedad,
    periodo). Sin buscar el encabezado esas 4 filas de banner se pierden al
    escribir a partir de `inicio - 1`. Con la heuristica se respeta la forma.
    """
    for i, fila in enumerate(filas[:15]):
        con_texto = sum(1 for c in fila
                        if isinstance(c, str) and c.strip())
        if con_texto >= 3:
            return i
    return 0


def _escribir_fila(hoja, fila: int, valores) -> None:
    """Copia una fila del origen columna por columna, sin reordenar."""
    for desplazamiento, valor in enumerate(valores):
        columna = 1 + desplazamiento
        if columna > 15:          # la hoja de la plantilla llega hasta O
            break
        celda = hoja.cell(row=fila, column=columna)
        if _escribible(celda):
            celda.value = valor


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

    # Mismo resolver que usa C11 -- match tolerante a prefijos, ceros a la
    # izquierda y sufijos de sucursal. Si aca se hiciera match exacto, la
    # hoja saldria sin proveedor ni concepto para toda factura cuyo PDF
    # se guardo con nombre distinto de la referencia SAP -- que es lo
    # tipico cuando el PDF se descarga con nombre humano
    # ('Factura electronica OP portuaria 250530.pdf').
    from motor_reteica.controles import _resolver_linea_de_factura
    por_referencia = {l.referencia: l for l in ctx.lineas}
    fila = inicio
    for factura in ctx.facturas or []:
        linea = _resolver_linea_de_factura(factura.numero, por_referencia)
        tarifa = (ctx.municipio.tarifa_por_cuenta.get(linea.cuenta)
                  if linea else None)
        hoja.cell(row=fila, column=2, value=linea.documento if linea else None)
        # Cuando hay linea, se usa SU referencia (limpia) en vez del nombre
        # completo del PDF. Robinson leia '250530' en su papel manual, no
        # 'Factura electronica OP portuaria 250530.pdf'. Si no hay linea,
        # se cae al nombre del archivo como pista para el auditor.
        hoja.cell(row=fila, column=3,
                  value=linea.referencia if linea else factura.numero)
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
    # N12 y N13 son celdas NUMERICAS: O12 hace =ROUND(+N12-M12,-3) y N14 las
    # suma. Escribir texto ahi --por bienintencionado que sea-- produce
    # #!VALOR! y el error se propaga por toda la hoja. La falta se DICE, pero
    # en P, que es columna libre y nadie calcula sobre ella; la celda numerica
    # queda VACIA, que en Excel no afirma un saldo de cero.
    faltantes = []
    for celda, cuenta in (("N12", "2368010007"), ("N13", "2368010010")):
        saldo = None if ctx.saldos is None else ctx.saldos.get(cuenta)
        if saldo is None:
            hoja[celda] = None
            faltantes.append(cuenta)
        else:
            hoja[celda] = int(saldo)

    if faltantes:
        hoja["P12"] = ("SIN BALANCE DE PRUEBA: no se pudo tomar el saldo"
                       if ctx.saldos is None else
                       "NO ESTA EN EL BALANCE: %s" % ", ".join(faltantes))

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


def depositar(ctx, destino, plantilla: Path = None,
              total_declarado_confirmado=None) -> Path:
    """Escribe el papel final a partir de la plantilla de la firma.

    `total_declarado_confirmado` es lo que el auditor confirmo del borrador
    en el tablero. Si viene, el papel trae un bloque de CRUCE UNIVERSAL --
    declarado vs auxiliar, con la diferencia-- que funciona en cualquier
    municipio porque solo depende de dos numeros: el que el auditor confirmo
    y la suma de la cuenta 2368 en el auxiliar del cliente.
    """
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
    # BORRADOR TERLICA: Robinson lo dijo en la reunion, no la usa. Se OCULTA
    # -- no se elimina -- porque fidelidad.py restaura las hojas desde el
    # paquete original (asi conserva logo y config de impresion), y borrar
    # una hoja con `del libro[nombre]` no solo la resucita: desordena los
    # ids de las demas hojas y aterrizan contenidos cambiados.
    if "BORRADOR TERLICA" in libro.sheetnames:
        libro["BORRADOR TERLICA"].sheet_state = "hidden"
    # 'Pago' tampoco se usa (auditor lo confirmo en la revision). Mismo
    # criterio que con BORRADOR TERLICA: se oculta, no se elimina --
    # fidelidad.py restaura las hojas desde el paquete original.
    if "Pago" in libro.sheetnames:
        libro["Pago"].sheet_state = "hidden"
    _depositar_revision_ica(libro, ctx)
    _depositar_cruce_universal(libro, ctx, total_declarado_confirmado)
    _depositar_conclusiones(libro, ctx)

    return guardar_conservando_formato(libro, plantilla, Path(destino))


def _depositar_cruce_universal(libro, ctx, total_confirmado) -> None:
    """El unico cruce que corre en cualquier municipio: declarado vs auxiliar.

    Es lo que Robinson hace a mano al final -- confirmar que la suma de la
    2368 en el auxiliar del cliente iguala lo que el borrador declaro. Si la
    estructura del formulario cambia (San Alberto, Barranquilla, cualquier
    municipio nuevo), este cruce sigue funcionando porque solo depende de
    dos numeros. Se escribe abajo de REVISION ICA, en una fila libre.

    Sin total confirmado no hay cruce: no vamos a inventarlo desde el PDF a
    ciegas. D9 pide que la cifra la ponga el auditor.
    """
    if total_confirmado is None:
        return

    hoja = libro["REVISION ICA"]
    fila = _fila_libre(hoja, desde=32)

    # Total del auxiliar: la suma que ya calcula el pipeline. Se toma en
    # valor absoluto porque las retenciones se registran como credito
    # (negativas en Agroingenium, positivas en TERLICA).
    total_auxiliar = abs(ctx.total_auxiliar or Decimal("0"))
    total_conf = Decimal(str(total_confirmado))
    diferencia = total_conf - total_auxiliar

    hoja.cell(row=fila, column=2, value="CRUCE UNIVERSAL")
    hoja.cell(row=fila, column=3,
              value="Declarado (auditor confirmo) vs auxiliar 2368")

    hoja.cell(row=fila + 1, column=2, value="Declarado")
    hoja.cell(row=fila + 1, column=4, value=int(total_conf))

    hoja.cell(row=fila + 2, column=2, value="Auxiliar 2368")
    hoja.cell(row=fila + 2, column=4, value=int(total_auxiliar))

    hoja.cell(row=fila + 3, column=2, value="Diferencia")
    hoja.cell(row=fila + 3, column=4, value=int(diferencia))
    # El estado se DICE, no se usa un semaforo: los redondeos a miles del
    # formulario producen diferencias legitimas de hasta unos cientos.
    if abs(diferencia) <= 1000:
        veredicto = "CUADRA (diferencia dentro del redondeo del formulario)"
    else:
        veredicto = "NO CUADRA -- revisar por que"
    hoja.cell(row=fila + 3, column=5, value=veredicto)


def _fila_libre(hoja, desde: int) -> int:
    """La primera fila totalmente vacia desde `desde`, dentro del rango util."""
    for fila in range(desde, hoja.max_row + 10):
        if all(hoja.cell(row=fila, column=c).value in (None, "")
               for c in range(2, 11)):
            return fila
    return desde
