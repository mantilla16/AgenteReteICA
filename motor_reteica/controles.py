"""Bateria de controles C1..C14.

Regla comun: la ausencia de un insumo produce NO_EJECUTADO, nunca OK.
Ningun control lee parametros del borrador: el borrador es objeto de prueba.
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from motor_reteica.parametros.tolerancias import TOLERANCIAS
from motor_reteica.tipos import Estado, Excepcion, ResultadoControl, Severidad

_CRUCE = TOLERANCIAS["diferencia_maxima_cruce_pesos"]
_RECALCULO = TOLERANCIAS["diferencia_maxima_recalculo_pesos"]
_CERO = Decimal("0")


def _no_ejecutado(codigo: str, nombre: str, insumo: str) -> ResultadoControl:
    return ResultadoControl(codigo=codigo, nombre=nombre,
                            estado=Estado.NO_EJECUTADO,
                            detalle="no se ejecuto: falta %s" % insumo)


def _resolver(codigo, nombre, excepciones, detalle_ok):
    """M14: el detalle sobrevive a la falla.

    Antes, si habia excepciones el detalle pasaba a ser "%d excepcion(es)" y
    se tiraba el que decia QUE se verifico y sobre cuantos elementos. Justo
    cuando un control falla es cuando mas hace falta saber el alcance de lo
    que si se miro.
    """
    if excepciones:
        return ResultadoControl(
            codigo=codigo, nombre=nombre, estado=Estado.FALLA,
            detalle="%d excepcion(es); %s" % (len(excepciones), detalle_ok),
            excepciones=tuple(excepciones))
    return ResultadoControl(codigo=codigo, nombre=nombre, estado=Estado.OK,
                            detalle=detalle_ok)


# --------------------------------------------------------------------------
# Amarre contable
# --------------------------------------------------------------------------

def c2_balance_vs_auxiliar(saldos, lineas) -> ResultadoControl:
    nombre = "Balance de prueba vs auxiliar 2368 (por cuenta)"
    if saldos is None:
        return _no_ejecutado("C2", nombre, "el balance de prueba")


    por_cuenta = defaultdict(lambda: _CERO)
    for linea in lineas:
        por_cuenta[linea.cuenta] += linea.retencion

    excepciones = []
    for cuenta in sorted(set(saldos) | set(por_cuenta)):
        diferencia = saldos.get(cuenta, _CERO) - por_cuenta.get(cuenta, _CERO)
        if abs(diferencia) > _CRUCE:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C2",
                descripcion="cuenta %s: balance %s vs auxiliar %s"
                            % (cuenta, saldos.get(cuenta, _CERO),
                               por_cuenta.get(cuenta, _CERO)),
                renglon=cuenta, impacto_pesos=abs(diferencia)))

    return _resolver("C2", nombre, excepciones,
                     "%d cuenta(s) cuadradas" % len(por_cuenta))


def c3_auxiliar_vs_erp(lineas, filas_erp) -> ResultadoControl:
    nombre = "Auxiliar 2368 vs reporte de retenciones del ERP (por tercero)"
    if filas_erp is None:
        return _no_ejecutado("C3", nombre, "el reporte de retenciones del ERP")


    auxiliar = defaultdict(lambda: _CERO)
    for linea in lineas:
        auxiliar[linea.nit] += linea.retencion

    # 3.3: SUMAR las filas del ERP por NIT, no sobrescribirlas. Antes
    # `{f.nit: f.retencion for f in filas_erp}` dejaba solo la ultima fila:
    # un proveedor con dos codigos de retencion se comparaba incompleto y C3
    # fallaba por un defecto del motor, no del cliente.
    erp = defaultdict(lambda: _CERO)
    for fila in filas_erp:
        erp[fila.nit] += fila.retencion

    excepciones = []
    for nit in sorted(set(auxiliar) | set(erp)):
        diferencia = auxiliar.get(nit, _CERO) - erp.get(nit, _CERO)
        if abs(diferencia) > _CRUCE:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C3",
                descripcion="NIT %s: auxiliar %s vs ERP %s"
                            % (nit, auxiliar.get(nit, _CERO), erp.get(nit, _CERO)),
                renglon=nit, impacto_pesos=abs(diferencia)))

    return _resolver("C3", nombre, excepciones,
                     "%d tercero(s) cuadrados" % len(auxiliar))


def c5_coherencia_cuenta_codigo(lineas, filas_erp, municipio) -> ResultadoControl:
    nombre = "Coherencia tarifa de la cuenta contable vs codigo de retencion del ERP"
    if filas_erp is None:
        return _no_ejecutado("C5", nombre, "el reporte de retenciones del ERP")

    # 3.3: un NIT puede traer VARIOS codigos de retencion en el ERP (compras
    # al 10 por mil y servicios al 7). Antes `{f.nit: f.codigo_ret}` dejaba uno
    # solo y evaluaba todas las lineas del tercero contra el codigo de otra.
    codigos_por_nit = defaultdict(set)
    for fila in filas_erp:
        codigos_por_nit[fila.nit].add(fila.codigo_ret)

    excepciones = []
    for linea in lineas:
        tarifa_cuenta = municipio.tarifa_por_cuenta.get(linea.cuenta)
        codigos = codigos_por_nit.get(linea.nit)
        if not codigos:
            continue
        tarifas_erp = {municipio.tarifa_por_codigo_ret.get(c) for c in codigos}
        # Basta con que ALGUN codigo del tercero respalde la tarifa de la
        # cuenta. Si ninguno lo hace, la linea no tiene respaldo en el ERP.
        if tarifa_cuenta not in tarifas_erp:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C5",
                descripcion="%s (NIT %s): cuenta %s implica %s pero el ERP solo "
                            "trae para ese tercero los codigos %s, que implican %s"
                            % (linea.referencia, linea.nit, linea.cuenta,
                               tarifa_cuenta, ", ".join(sorted(codigos)),
                               ", ".join(str(t) for t in sorted(
                                   t for t in tarifas_erp if t is not None))),
                renglon=linea.cuenta))

    return _resolver("C5", nombre, excepciones,
                     "%d linea(s) verificadas" % len(lineas))


# --------------------------------------------------------------------------
# Formulario y exactitud
# --------------------------------------------------------------------------

def c1_formulario_cuadra(borrador, municipio) -> ResultadoControl:
    """El borrador debe cerrar consigo mismo, antes de mirar la contabilidad.

    No se usa la formula impresa en el renglon 31 ('27+28+29'): es incorrecta,
    porque el renglon 28 reexpresa el 27 en vez de sumarlo.
    """
    nombre = "El formulario cuadra consigo mismo"
    r = borrador.renglones
    suma_impuesto = sum((a.impuesto for a in borrador.actividades), _CERO)
    suma_bases = sum((a.base for a in borrador.actividades), _CERO)

    ecuaciones = [
        ("suma de impuestos por actividad = renglon 24", suma_impuesto, r["24"]),
        ("suma de bases por actividad = renglon 23", suma_bases, r["23"]),
        ("renglon 27 = 24 - 25 + 26", r["24"] - r["25"] + r["26"], r["27"]),
        ("renglon 31 = 27 + 29 + 30", r["27"] + r["29"] + r["30"], r["31"]),
        ("renglon 32 = 31", r["31"], r["32"]),
    ]

    excepciones = []
    for descripcion, esperado, declarado in ecuaciones:
        if esperado != declarado:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C1",
                descripcion="%s: %s vs %s" % (descripcion, esperado, declarado),
                impacto_pesos=abs(esperado - declarado)))

    return _resolver("C1", nombre, excepciones,
                     "%d ecuacion(es) del formulario verificadas" % len(ecuaciones))


def c4_recalculo(reconstruccion) -> ResultadoControl:
    """Recalculo aritmetico por tercero contra la base del ERP.

    Si la base fuese derivada de la retencion, base x tarifa devolveria la
    retencion por construccion y el control pasaria siempre. Por eso, sin
    reporte del ERP, esto es NO_EJECUTADO y no OK.
    """
    nombre = "Recalculo base x tarifa (por tercero, base del ERP)"
    if reconstruccion.base_es_derivada:
        return _no_ejecutado(
            "C4", nombre,
            "el reporte del ERP; sin el, la base se deriva de la retencion y "
            "el recalculo seria circular")

    excepciones = []
    for tercero in reconstruccion.por_tercero.values():
        if abs(tercero.diferencia) > _RECALCULO:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C4",
                descripcion="NIT %s: base %s x %s = %s vs %s contabilizado"
                            % (tercero.nit, tercero.base, tercero.tarifa,
                               tercero.retencion_recalculada,
                               tercero.retencion_contable),
                renglon=tercero.nit, impacto_pesos=abs(tercero.diferencia)))

    return _resolver("C4", nombre, excepciones,
                     "%d tercero(s) recalculados sobre la base del ERP"
                     % len(reconstruccion.por_tercero))


def c7_tarifas_vs_estatuto(borrador, municipio, atestacion=None) -> ResultadoControl:
    """Tarifas contra el Acuerdo municipal, jamas contra el borrador.

    X1: mientras no se cargue el Acuerdo del municipio, el auditor puede
    entrar como TESTIGO y declarar la tarifa con su procedencia. Eso NO
    produce OK: produce ATESTADO, que es un estado propio. El papel debe poder
    decir si hubo recalculo contra el estatuto o solo testimonio.
    """
    nombre = "Tarifa aplicada vs tabla de tarifas del municipio"
    atestadas = atestacion.tarifas if atestacion else {}

    if municipio.estado_tarifas == "PENDIENTE_VALIDACION_ESTATUTO" and not atestadas:
        return ResultadoControl(
            codigo="C7", nombre=nombre, estado=Estado.NO_EJECUTADO,
            detalle="no se ejecuto: la tabla de tarifas de %s esta en estado "
                    "PENDIENTE_VALIDACION_ESTATUTO y nadie atesto las tarifas; "
                    "sin el Acuerdo municipal vigente el cruce solo probaria "
                    "consistencia interna" % municipio.nombre)

    if atestadas:
        return _c7_contra_atestacion(borrador, atestacion, nombre)

    excepciones = []
    for actividad in borrador.actividades:
        vigente = municipio.tarifas_actividad.get(actividad.codigo)
        if vigente is None:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C7",
                descripcion="la actividad %s no figura en el estatuto de %s"
                            % (actividad.codigo, municipio.nombre),
                renglon=actividad.codigo))
        elif vigente != actividad.tarifa:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C7",
                descripcion="actividad %s: declarada %s, estatuto %s"
                            % (actividad.codigo, actividad.tarifa, vigente),
                renglon=actividad.codigo,
                impacto_pesos=abs(actividad.base * (vigente - actividad.tarifa))))

    return _resolver("C7", nombre, excepciones,
                     "%d actividad(es) contra %s"
                     % (len(borrador.actividades), municipio.estado_tarifas))


def _c7_contra_atestacion(borrador, atestacion, nombre) -> ResultadoControl:
    """Confronta el borrador contra lo que el auditor atesto, no contra el
    propio borrador. Si el auditor no atesto una actividad que el borrador
    declara, eso es una excepcion: quedo sin respaldo."""
    excepciones = []
    for actividad in borrador.actividades:
        atestada = atestacion.tarifas.get(actividad.codigo)
        if atestada is None:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C7",
                descripcion="la actividad %s aparece en el borrador y nadie "
                            "atesto su tarifa: queda sin respaldo"
                            % actividad.codigo,
                renglon=actividad.codigo))
        elif atestada.tarifa != actividad.tarifa:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C7",
                descripcion="actividad %s: el borrador aplica %s y el auditor "
                            "atesto %s (%s)"
                            % (actividad.codigo, actividad.tarifa,
                               atestada.tarifa, atestada.descripcion()),
                renglon=actividad.codigo,
                impacto_pesos=abs(actividad.base
                                  * (atestada.tarifa - actividad.tarifa))))

    detalle = ("%d actividad(es) contra la atestacion de %s. LIMITE: esto NO "
               "es un recalculo independiente contra el estatuto; es el "
               "testimonio del auditor, y es mas debil que cargar el Acuerdo."
               % (len(borrador.actividades), atestacion.firma()))

    if excepciones:
        return ResultadoControl(
            codigo="C7", nombre=nombre, estado=Estado.FALLA,
            detalle="%d excepcion(es); %s" % (len(excepciones), detalle),
            excepciones=tuple(excepciones))
    return ResultadoControl(codigo="C7", nombre=nombre,
                            estado=Estado.ATESTADO, detalle=detalle)


def c10_redondeo(borrador, reconstruccion) -> ResultadoControl:
    """Cada renglon declarado debe ser el redondeo al mil del contable."""
    nombre = "Redondeo al mil por renglon"

    # M3: este control YA NO repite la comparacion renglon por renglon contra
    # el borrador. Ese bucle era literalmente la segunda verificacion de C9 y
    # duplicaba el mismo hallazgo en el informe, inflando el conteo de
    # excepciones. C10 se queda con lo suyo: explicar la diferencia entre el
    # impuesto exacto y el declarable como efecto del redondeo al mil.
    excepciones = []

    diferencia = (reconstruccion.total_impuesto_contable
                  - reconstruccion.total_impuesto_declarable)
    return _resolver(
        "C10", nombre, excepciones,
        "impuesto contable %s, declarable %s; la diferencia de %s pesos es efecto "
        "del redondeo al mil por renglon, no una diferencia de impuesto"
        % (reconstruccion.total_impuesto_contable,
           reconstruccion.total_impuesto_declarable, diferencia))


# --------------------------------------------------------------------------
# Clasificacion, corte, documental y formales
# --------------------------------------------------------------------------

_PALABRAS_COMERCIO = ("COMPRA", "SUMINISTRO", "ADQUISICION", "VENTA")
_PALABRAS_SERVICIO = ("REPARACION", "SERVICIO", "ESTUDIO", "MANTENIMIENTO",
                      "FORTALECIMIENTO", "ASESORIA", "CONSULTORIA", "INSTALACION")
_ACTIVIDADES_COMERCIO = ("46", "47")

_INSUMOS = {
    "borrador": "el borrador de la declaracion",
    "auxiliar": "el libro auxiliar 2368",
    "balance": "el balance de prueba",
    "erp": "el reporte de retenciones del ERP",
    "facturas": "las facturas fuente",
    "pago_anterior": "la declaracion y el pago del mes anterior",
}


AMBIGUO = "AMBIGUO"
DESCONOCIDO = "DESCONOCIDO"


def _naturaleza(concepto):
    """Naturaleza del concepto, sin resolver los empates por orden.

    Antes, "SUMINISTRO E INSTALACION DE VALVULA" devolvia SERVICIO unicamente
    porque la lista de servicios se chequeaba primero. Eso no es juicio, es
    orden de lineas de codigo: ahora el empate se declara AMBIGUO y el que
    no cae en ninguna lista se declara DESCONOCIDO, en vez de None silencioso.
    """
    texto = concepto.upper()
    servicio = any(palabra in texto for palabra in _PALABRAS_SERVICIO)
    comercio = any(palabra in texto for palabra in _PALABRAS_COMERCIO)
    if servicio and comercio:
        return AMBIGUO
    if servicio:
        return "SERVICIO"
    if comercio:
        return "COMERCIO"
    return DESCONOCIDO


def c6_clasificacion_por_linea(reconstruccion, facturas, mapa_actividad,
                               municipio) -> ResultadoControl:
    """Clasificacion linea a linea: aqui si la linea es la unidad atomica.

    Agregar por tercero oculta el caso CDEM, donde dos tercios del renglon
    4669 de comercio al por mayor son en realidad una reparacion.
    """
    nombre = "Clasificacion de la actividad por linea"
    por_nit = {f.nit: f for f in (facturas or []) if f.nit}
    excepciones = []

    def _renglon_de(nit, tarifa=None):
        """3.3/3.4: el mapa se llavea por grupo (NIT, tarifa).

        Se acepta tambien la llave por NIT para no romper llamadas antiguas.
        Cuando solo se conoce el NIT -- el cotejo contra la factura -- se
        resuelve si el tercero tiene un unico renglon asignado.
        """
        if tarifa is not None:
            directo = mapa_actividad.get((nit, tarifa))
            if directo is not None:
                return directo
        simple = mapa_actividad.get(nit)
        if simple is not None:
            return simple
        suyos = {codigo for clave, codigo in mapa_actividad.items()
                 if isinstance(clave, tuple) and clave[0] == nit}
        return suyos.pop() if len(suyos) == 1 else None

    for valorada in reconstruccion.lineas_valoradas:
        linea = valorada.linea
        codigo = _renglon_de(linea.nit, valorada.tarifa)
        if codigo is None:
            continue
        naturaleza = _naturaleza(linea.concepto)
        es_renglon_comercio = codigo.startswith(_ACTIVIDADES_COMERCIO)

        if naturaleza == "SERVICIO" and es_renglon_comercio:
            excepciones.append(Excepcion(
                severidad=Severidad.OBSERVACION, control="C6",
                descripcion="%s (NIT %s): el concepto [%s] es un servicio pero "
                            "esta clasificado en el renglon %s de comercio al "
                            "por mayor"
                            % (linea.referencia, linea.nit, linea.concepto, codigo),
                renglon=codigo, impacto_pesos=_CERO))
        # El lado que faltaba: un control asimetrico deja media poblacion sin
        # cubrir y no lo dice.
        elif naturaleza == "COMERCIO" and not es_renglon_comercio:
            excepciones.append(Excepcion(
                severidad=Severidad.OBSERVACION, control="C6",
                descripcion="%s (NIT %s): el concepto [%s] es una compra de "
                            "mercancia (comercio) pero esta clasificado en el "
                            "renglon %s, que no es de comercio"
                            % (linea.referencia, linea.nit, linea.concepto, codigo),
                renglon=codigo, impacto_pesos=_CERO))
        elif naturaleza == AMBIGUO:
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C6",
                descripcion="%s (NIT %s): el concepto [%s] es ambiguo -- menciona "
                            "compra y servicio a la vez -- y no se puede "
                            "clasificar sin criterio humano"
                            % (linea.referencia, linea.nit, linea.concepto),
                renglon=codigo))
        elif naturaleza == DESCONOCIDO:
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C6",
                descripcion="%s (NIT %s): el concepto [%s] no se pudo clasificar "
                            "como compra ni como servicio; queda sin cubrir"
                            % (linea.referencia, linea.nit, linea.concepto),
                renglon=codigo))

    for nit, factura in sorted(por_nit.items()):
        declarada = _renglon_de(nit)
        en_factura = factura.actividad_declarada
        if not en_factura or not declarada or en_factura == declarada:
            continue
        tarifa_declarada = municipio.tarifas_actividad.get(declarada)
        tarifa_factura = municipio.tarifas_actividad.get(en_factura)
        misma_tarifa = (tarifa_factura is not None
                        and tarifa_declarada == tarifa_factura)
        if misma_tarifa or tarifa_factura is None:
            severidad, impacto = Severidad.OBSERVACION, _CERO
        else:
            severidad = Severidad.HALLAZGO
            impacto = abs(factura.base * (tarifa_factura - tarifa_declarada))
        excepciones.append(Excepcion(
            severidad=severidad, control="C6",
            descripcion="%s (NIT %s): el proveedor declara la actividad %s en "
                        "su factura pero el borrador la clasifica en %s"
                        % (factura.numero, nit, en_factura, declarada),
            renglon=declarada, impacto_pesos=impacto))

    return _resolver("C6", nombre, excepciones,
                     "%d linea(s) clasificadas sin contradiccion"
                     % len(reconstruccion.lineas_valoradas))


def c8_corte(lineas, periodo) -> ResultadoControl:
    """Corte sobre el auxiliar.

    M1: el corte real es la FECHA DE CONTABILIZACION -- es la que define en
    que periodo entra el registro. Antes se miraba fecha_documento, que es
    otra cosa. M2: una linea contabilizada fuera del periodo ya NO aborta la
    corrida (eso lo hacia C0); es una excepcion de corte, que es lo de aqui.

    El desfase entre la factura fisica y el registro contable NO es visible
    aqui: lo detecta C11 contra el PDF.
    """
    nombre = "Corte: contabilizacion dentro del periodo"
    anio, mes = (int(parte) for parte in periodo.split("-"))

    excepciones = []
    for linea in lineas:
        contabilizacion = linea.fecha_contabilizacion
        if (contabilizacion.year, contabilizacion.month) != (anio, mes):
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C8",
                descripcion="%s: contabilizada el %s, fuera del periodo %s"
                            % (linea.referencia, contabilizacion, periodo),
                renglon=linea.cuenta, impacto_pesos=linea.retencion))
        elif (linea.fecha_documento.year,
              linea.fecha_documento.month) != (anio, mes):
            excepciones.append(Excepcion(
                severidad=Severidad.OBSERVACION, control="C8",
                descripcion="%s: fecha de documento %s, de un periodo anterior "
                            "a %s; valida si la retencion se causo en el abono "
                            "en cuenta, pero debe quedar escrito"
                            % (linea.referencia, linea.fecha_documento, periodo),
                renglon=linea.cuenta))

    return _resolver("C8", nombre, excepciones,
                     "%d linea(s) contabilizadas dentro del periodo %s"
                     % (len(lineas), periodo))


def c11_cotejo_facturas(lineas, facturas, municipio) -> ResultadoControl:
    """Cotejo del documento fuente contra el registro contable.

    Es el UNICO control que va de la factura al auxiliar sin pasar por el ERP
    ni por el borrador. La tarifa se toma de la cuenta contable -- que esta en
    el auxiliar -- y jamas del borrador: por eso el amarre es independiente
    del objeto de prueba.

        base_del_PDF x tarifa_de_la_cuenta == retencion_del_auxiliar

    Cada campo se verifica POR SEPARADO. Antes, una factura sin NIT legible se
    descartaba entera y su base -- que si se habia podido leer -- no se
    cotejaba nunca. FE338057 es justo ese caso: sin NIT en la capa de texto,
    pero con base 1.196.993 que cuadra al peso contra los 11.970
    contabilizados.
    """
    nombre = "Cotejo de la factura fuente contra el auxiliar"
    if not facturas:
        return _no_ejecutado("C11", nombre, "las facturas fuente")

    por_referencia = {l.referencia: l for l in lineas}
    excepciones = []
    con_base_verificada = 0
    sin_nit = 0
    sin_base = 0

    for factura in facturas:
        linea = por_referencia.get(factura.numero)
        if linea is None:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C11",
                descripcion="%s: la factura no aparece en el auxiliar"
                            % factura.numero))
            continue

        # --- NIT -----------------------------------------------------------
        if not factura.nit:
            sin_nit += 1
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C11",
                descripcion="%s: no se pudo leer el NIT del proveedor en el "
                            "PDF; ese campo queda a cotejo manual"
                            % factura.numero))
        elif factura.nit != linea.nit:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C11",
                descripcion="%s: NIT en el PDF %s vs auxiliar %s"
                            % (factura.numero, factura.nit, linea.nit)))

        # --- base contra retencion contabilizada -----------------------------
        tarifa = municipio.tarifa_por_cuenta.get(linea.cuenta)
        if factura.base is None:
            sin_base += 1
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C11",
                descripcion="%s: no se pudo leer la base gravable en el PDF; "
                            "la retencion contabilizada no se pudo verificar "
                            "contra el documento fuente" % factura.numero))
        elif tarifa is None:
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C11",
                descripcion="%s: la cuenta %s no tiene tarifa parametrizada; "
                            "no se puede recalcular la retencion"
                            % (factura.numero, linea.cuenta),
                renglon=linea.cuenta))
        else:
            esperada = (factura.base * tarifa).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            diferencia = esperada - linea.retencion
            if abs(diferencia) > _RECALCULO:
                excepciones.append(Excepcion(
                    severidad=Severidad.HALLAZGO, control="C11",
                    descripcion="%s: base %s del PDF x %s = %s, pero el "
                                "auxiliar contabiliza %s"
                                % (factura.numero, factura.base, tarifa,
                                   esperada, linea.retencion),
                    renglon=linea.cuenta,
                    impacto_pesos=abs(diferencia)))
            else:
                con_base_verificada += 1

        # --- fecha -----------------------------------------------------------
        if factura.fecha and factura.fecha != linea.fecha_documento:
            excepciones.append(Excepcion(
                severidad=Severidad.OBSERVACION, control="C11",
                descripcion="%s: la fecha de la factura es %s y el auxiliar la "
                            "registra con fecha de documento %s"
                            % (factura.numero, factura.fecha,
                               linea.fecha_documento),
                renglon=linea.cuenta))

    # M8: el detalle dice QUE se coteja y QUE quedo sin cotejar. Decir
    # "N facturas cotejadas" a secas sobreafirma el alcance del control.
    # No se usa _resolver porque este descarta el detalle cuando hay
    # excepciones, y la cobertura hay que declararla sobre todo cuando el
    # control falla.
    detalle = ("%d factura(s): %d con la base verificada contra la retencion "
               "del auxiliar" % (len(facturas), con_base_verificada))
    if sin_base:
        detalle += "; %d sin base legible" % sin_base
    if sin_nit:
        detalle += "; %d sin NIT legible" % sin_nit
    if excepciones:
        detalle += "; %d excepcion(es)" % len(excepciones)

    return ResultadoControl(
        codigo="C11", nombre=nombre,
        estado=Estado.FALLA if excepciones else Estado.OK,
        detalle=detalle, excepciones=tuple(excepciones))


def c12_continuidad(saldo_mes_anterior, pago_mes_anterior) -> ResultadoControl:
    nombre = "Continuidad: saldo del mes anterior vs pago"
    if saldo_mes_anterior is None or pago_mes_anterior is None:
        return _no_ejecutado("C12", nombre,
                             "la declaracion y el pago del mes anterior")

    diferencia = saldo_mes_anterior - pago_mes_anterior
    excepciones = []
    if abs(diferencia) > _CRUCE:
        excepciones.append(Excepcion(
            severidad=Severidad.HALLAZGO, control="C12",
            descripcion="saldo del mes anterior %s vs pago %s"
                        % (saldo_mes_anterior, pago_mes_anterior),
            impacto_pesos=abs(diferencia)))

    return _resolver("C12", nombre, excepciones, "saldo y pago coinciden")


def c13_formales(borrador, municipio, insumos_obtenidos,
                 candidatas_sin_declarar=()) -> ResultadoControl:
    nombre = "Requisitos formales y trazabilidad de insumos"
    excepciones = []

    for clave, descripcion in sorted(_INSUMOS.items()):
        if clave not in insumos_obtenidos:
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C13",
                descripcion="insumo no obtenido: %s" % descripcion))

    # M11: la cuenta se excluyo por su NATURALEZA detectada en el balance, no
    # por una lista fija. Esa determinacion se toma de los datos, pero la
    # decision es del auditor: mientras no la declare, queda dicho en el papel.
    for cuenta in sorted(candidatas_sin_declarar):
        excepciones.append(Excepcion(
            severidad=Severidad.AVISO, control="C13",
            descripcion="la cuenta %s tiene naturaleza debito y se trato como "
                        "contrapartida de pago (excluida de los cruces) por su "
                        "saldo, no por declaracion del auditor; conviene "
                        "atestarla" % cuenta,
            renglon=cuenta))

    # M10: se quito el chequeo de firma de revisor fiscal. El objeto de prueba
    # es un BORRADOR que la firma todavia no ha firmado, asi que verificar ahi
    # su propia firma no tiene sentido en esta etapa. Ademas el chequeo era
    # silencioso: buscaba "FRMA_RVSR_FSCL", que es una ETIQUETA IMPRESA del
    # formulario en blanco, y devolvia True siempre.
    # Si algun dia se quiere verificar la firma, corresponde al momento de la
    # PRESENTACION de la declaracion, no a la revision del borrador.

    try:
        vencimiento = municipio.vencimiento(borrador.periodo)
        detalle = "insumos completos; vencimiento %s" % vencimiento
    except KeyError:
        excepciones.append(Excepcion(
            severidad=Severidad.AVISO, control="C13",
            descripcion="no hay fecha de vencimiento parametrizada para %s"
                        % borrador.periodo))
        detalle = "insumos completos; sin vencimiento parametrizado"

    return _resolver("C13", nombre, excepciones, detalle)


def c14_compras_vs_servicios(reconstruccion, municipio) -> ResultadoControl:
    nombre = "Discriminacion de base de compras vs servicios"
    if not municipio.exige_discriminar_compras_servicios:
        return ResultadoControl(
            codigo="C14", nombre=nombre, estado=Estado.NO_EJECUTADO,
            detalle="no aplica: %s no exige discriminar compras y servicios"
                    % municipio.nombre,
            aplica=False)

    excepciones = []
    for valorada in reconstruccion.lineas_valoradas:
        if _naturaleza(valorada.linea.concepto) in (AMBIGUO, DESCONOCIDO):
            excepciones.append(Excepcion(
                severidad=Severidad.AVISO, control="C14",
                descripcion="%s: no se pudo clasificar el concepto [%s] como "
                            "compra o servicio"
                            % (valorada.linea.referencia, valorada.linea.concepto)))

    return _resolver("C14", nombre, excepciones, "todas las lineas clasificadas")


# --------------------------------------------------------------------------
# Control terminal
# --------------------------------------------------------------------------

def c9_reconstruccion_vs_borrador(reconstruccion, borrador,
                                  mapa_asignado=None) -> ResultadoControl:
    """Confronta la reconstruccion independiente contra el borrador.

    Es el control terminal: todos los demas existen para que este signifique
    algo. Compara renglon por renglon en base e impuesto declarables.
    """
    nombre = "Recalculo de auditoria vs borrador de la declaracion"
    declarado = {a.codigo: a for a in borrador.actividades}
    reconstruido = reconstruccion.por_actividad
    excepciones = []

    # ---- CAPA 1: coherencia entre la cuenta contable y la clase de tarifa ---
    # La tarifa del grupo sale de la CUENTA, que esta en el auxiliar. La clase
    # de cada renglon sale del borrador. Si el borrador no declara ningun
    # renglon de la clase que exige la contabilidad, la contradiccion es real
    # y mueve pesos. Es el unico filo independiente que tiene la clasificacion.
    # El reparto viaja en la reconstruccion; el parametro solo existe para
    # sobreescribirlo en pruebas.
    if mapa_asignado is None:
        mapa_asignado = getattr(reconstruccion, 'mapa', {}) or {}
    clases_declaradas = {a.tarifa for a in borrador.actividades}
    sin_asignar = []
    for clave, grupo in sorted(reconstruccion.por_grupo.items()):
        if clave in mapa_asignado or grupo.nit in mapa_asignado:
            continue
        if grupo.tarifa not in clases_declaradas:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C9",
                descripcion="NIT %s: la cuenta contable implica una tarifa de "
                            "%s y el borrador no declara ningun renglon a esa "
                            "tarifa (declara %s)"
                            % (grupo.nit, grupo.tarifa,
                               ", ".join(str(t) for t in sorted(
                                   clases_declaradas))),
                renglon=grupo.nit,
                impacto_pesos=grupo.retencion_contable))
        else:
            sin_asignar.append(grupo)

    # 3.2: un grupo que no se pudo repartir NO es un hallazgo. Es la ausencia
    # de un reparto reproducible, y se declara como tal.
    for grupo in sin_asignar:
        excepciones.append(Excepcion(
            severidad=Severidad.AVISO, control="C9",
            descripcion="NIT %s (%s): el borrador declara varios renglones a "
                        "esa tarifa y ninguno cuadra con su base; el reparto "
                        "de este tercero no se pudo reproducir"
                        % (grupo.nit, grupo.tarifa),
            renglon=grupo.nit))

    # ---- montos por renglon --------------------------------------------------
    for codigo in sorted(set(declarado) | set(reconstruido)):
        actividad = declarado.get(codigo)
        renglon = reconstruido.get(codigo)

        if renglon is None:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C9",
                descripcion="la actividad %s aparece en el borrador pero no en "
                            "la reconstruccion" % codigo,
                renglon=codigo, impacto_pesos=actividad.impuesto))
            continue

        if actividad is None:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C9",
                descripcion="la actividad %s se reconstruyo pero no aparece en "
                            "el borrador" % codigo,
                renglon=codigo, impacto_pesos=renglon.impuesto_declarable))
            continue

        if renglon.base_declarable != actividad.base:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C9",
                descripcion="actividad %s: base de auditoria %s vs declarada %s"
                            % (codigo, renglon.base_declarable, actividad.base),
                renglon=codigo,
                impacto_pesos=abs(renglon.base_declarable - actividad.base)))

        if renglon.impuesto_declarable != actividad.impuesto:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C9",
                descripcion="actividad %s: impuesto de auditoria %s vs "
                            "declarado %s"
                            % (codigo, renglon.impuesto_declarable,
                               actividad.impuesto),
                renglon=codigo,
                impacto_pesos=abs(renglon.impuesto_declarable
                                  - actividad.impuesto)))

    # ---- CAPA 3: el limite se declara, no se esconde -----------------------
    limite = ("montos verificados renglon por renglon; el REPARTO de terceros "
              "por renglon se tomo del borrador y NO se verifico de forma "
              "independiente (el auxiliar trae el concepto, no el codigo CIIU)")
    detalle = "%d renglon(es) sin diferencia en montos; %s" % (
        len(reconstruido), limite)
    if excepciones:
        detalle = "%d excepcion(es); %s" % (len(excepciones), limite)

    return ResultadoControl(
        codigo="C9", nombre=nombre,
        estado=Estado.FALLA if excepciones else Estado.OK,
        detalle=detalle, excepciones=tuple(excepciones))


def c15_formato_historico(borrador, historico, periodo) -> ResultadoControl:
    """C15: el borrador contra el registro historico del propio cliente.

    Se separo de C12 a proposito. C12 verifica el PAGO del mes anterior y sin
    el comprobante no se puede ejecutar; si las dos cosas vivieran en un mismo
    control, la parte ejecutable pondria el control en OK y taparia que el
    pago nunca se miro. Un control no puede lavar a otro.

    Que prueba: que el borrador que nos entregaron coincida con lo que la
    compania registro en su propio formato para ese mismo periodo. Si difieren,
    hay dos versiones de la declaracion y eso es hallazgo antes de mirar la
    contabilidad.
    """
    nombre = "Borrador vs formato historico del cliente"
    if not historico:
        return _no_ejecutado("C15", nombre, "el formato historico del cliente")

    del_periodo = historico.get(periodo)
    if del_periodo is None:
        return ResultadoControl(
            codigo="C15", nombre=nombre, estado=Estado.NO_EJECUTADO,
            detalle="no se ejecuto: el formato historico no trae hoja para %s "
                    "(trae %s)" % (periodo, ", ".join(sorted(historico))))

    excepciones = []
    comparaciones = (
        ("base gravable", del_periodo.base_declarada, borrador.renglones["23"]),
        ("valor de retenciones", del_periodo.retenciones_declaradas,
         borrador.renglones["24"]),
    )
    for etiqueta, en_formato, en_borrador in comparaciones:
        if en_formato != en_borrador:
            excepciones.append(Excepcion(
                severidad=Severidad.HALLAZGO, control="C15",
                descripcion="%s: el formato historico (hoja %r) dice %s y el "
                            "borrador dice %s"
                            % (etiqueta, del_periodo.hoja, en_formato,
                               en_borrador),
                impacto_pesos=abs(en_formato - en_borrador)))

    return _resolver(
        "C15", nombre, excepciones,
        "el borrador coincide con la hoja %r del formato del cliente en base "
        "y retenciones" % del_periodo.hoja)
