"""Orquestacion de la revision.

Descubre los insumos en una carpeta, ejecuta C0 (que puede detener todo),
corre la bateria de controles y consolida. Un insumo ausente produce un
control NO_EJECUTADO, nunca una excepcion de Python.

1.1: si la carpeta trae manifiesto.json, los roles se resuelven contra el
(nombres de archivo reales del cliente, ver manifiesto.py). Si NO trae
manifiesto, se usa la convencion literal original (ARCHIVOS mas abajo).
Ese modo legado se conserva a proposito: las fixtures de prueba
(tests/fixtures/**) son datos reales del cliente y no se tocan para
agregarles un manifiesto, y gran parte de la bateria de pruebas del motor
corre directo contra esas fixtures sin pasar por manifiesto.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from motor_reteica import controles
from motor_reteica.atestacion import leer_atestacion
from motor_reteica.hallazgos import consolidar
from motor_reteica.ia import controles_ia
from motor_reteica.identidad import (IdentidadIncompatible, huella,
                                     verificar_identidad, verificar_tipo_documento)
from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.balance import (DEBITO, leer_acumulados,
                                            leer_balance, leer_naturalezas)
from motor_reteica.ingesta.borrador_pdf import leer_borrador
from motor_reteica.ingesta.formato_historico import (leer_formato_historico,
                                                     periodo_anterior)
from motor_reteica.ingesta.facturas_pdf import leer_factura
from motor_reteica.ingesta.sap_retenciones import leer_sap_retenciones
from motor_reteica.manifiesto import NOMBRE_ARCHIVO, leer_manifiesto
from motor_reteica.reconstruccion import reconstruir

ARCHIVOS = {
    "borrador": "borrador.pdf",
    "auxiliar": "auxiliar_2368.xlsx",
    "balance": "balance.xlsx",
    "erp": "sap_retenciones.xlsx",
}

_ROLES_ARCHIVO_UNICO = ("borrador", "auxiliar", "balance", "erp",
                        "pago_anterior", "formato_historico")
_ROLES_CON_FIRMA_TABULAR = ("auxiliar", "balance", "erp")


@dataclass(frozen=True)
class ContextoRevision:
    nit: str
    periodo: str
    municipio: object
    borrador: object
    lineas: list
    saldos: dict
    filas_erp: list
    facturas: list
    reconstruccion: object
    resultados: list
    informe: object
    huellas: dict
    insumos_obtenidos: set
    total_auxiliar: Decimal
    total_erp: Decimal
    manifiesto: object = None
    atestacion: object = None
    # Cuentas que el motor detecto como candidatas a contrapartida y que
    # nadie declaro. El llamador las usa para armar la plantilla (D2).
    candidatas_sin_declarar: frozenset = frozenset()
    # Saldo acumulado de cada cuenta 2368, SOLO para mostrarlo en el papel.
    # No entra en ningun cruce: arrastra los periodos anteriores.
    acumulados: dict = field(default_factory=dict)
    # Donde quedo cada documento que se uso. El papel de trabajo ES la
    # evidencia, asi que las hojas de insumo transcriben la fuente COMPLETA;
    # para eso hay que poder volver a leerla al depositar. Nada de esto entra
    # en un cruce: los cruces ya se hicieron con lo que leyo la ingesta.
    rutas: dict = field(default_factory=dict)


_TOLERANCIA_REDONDEO = Decimal("1000")


def _bases_por_grupo(filas_erp, lineas, municipio):
    """Base de cada grupo (NIT, tarifa). Del ERP si esta; derivada si no."""
    del_erp = {}
    for fila in (filas_erp or []):
        tarifa = municipio.tarifa_por_codigo_ret.get(fila.codigo_ret)
        if tarifa is None:
            continue
        clave = (fila.nit, tarifa)
        del_erp[clave] = del_erp.get(clave, Decimal("0")) + fila.base

    # Sin reporte del ERP la base se deriva de la retencion: es imprecisa
    # (hasta 91 pesos por tercero) pero basta para emparejar renglones, que
    # es lo unico que este mapa hace.
    derivadas = {}
    for linea in lineas:
        tarifa = municipio.tarifa_por_cuenta[linea.cuenta]
        clave = (linea.nit, tarifa)
        derivadas[clave] = derivadas.get(clave, Decimal("0")) + (
            linea.retencion / tarifa).quantize(Decimal("1"))

    return {clave: del_erp.get(clave, derivada)
            for clave, derivada in derivadas.items()}


def mapa_actividad(borrador, filas_erp, lineas, municipio):
    """Asigna cada grupo (NIT, tarifa) a un renglon del borrador.

    LIMITE, declarado en 3.1.bis y en C9: esto NO reconstruye la
    clasificacion. El auxiliar trae el concepto, no el codigo CIIU, asi que el
    reparto se toma del borrador. Lo que este mapa si garantiza es que un
    grupo NUNCA se asigne a un renglon de otra CLASE DE TARIFA: la tarifa del
    grupo viene de la cuenta contable, que esta en el auxiliar y no en el
    borrador. Esa restriccion es la CAPA 1 y es lo que hace que la
    contradiccion aflore en vez de quedar tapada por un emparejamiento de
    montos.

    3.2: varios grupos pueden caer en el mismo renglon. Antes el renglon se
    consumia con disponibles.remove() y el segundo grupo quedaba sin codigo,
    lo que producia un HALLAZGO FALSO en C9.
    """
    bases = _bases_por_grupo(filas_erp, lineas, municipio)
    mapa = {}

    por_clase = {}
    for actividad in borrador.actividades:
        por_clase.setdefault(actividad.tarifa, []).append(actividad)

    for clave in sorted(bases):
        _, tarifa = clave
        candidatos = por_clase.get(tarifa, [])
        if not candidatos:
            # Sin renglon de esa clase de tarifa: lo detecta C9 (capa 1).
            continue

        if len(candidatos) == 1:
            mapa[clave] = candidatos[0].codigo
            continue

        base = bases[clave]
        coinciden = [a for a in candidatos
                     if abs(a.base - base) < _TOLERANCIA_REDONDEO]
        if len(coinciden) == 1:
            mapa[clave] = coinciden[0].codigo
        # Si ninguno o varios coinciden, el grupo queda sin asignar y C9 lo
        # avisa. Elegir "el mas parecido" seria inventar el reparto.

    return mapa


# Nombre anterior, conservado para compatibilidad interna.
_mapa_actividad = mapa_actividad


def _resolver_via_manifiesto(carpeta, manifiesto):
    """1.1: rutas a partir del manifiesto, con los nombres reales del cliente."""
    rutas = {}
    presentes = set()
    for rol in _ROLES_ARCHIVO_UNICO:
        nombre = manifiesto.archivos.get(rol)
        if nombre:
            rutas[rol] = carpeta / nombre
            presentes.add(rol)

    # El rol 'facturas' admite dos formas: nombre de una subcarpeta (se
    # globea *.pdf dentro), o una lista de nombres de archivo explicitos
    # cuando las facturas vienen sueltas junto con los demas insumos, como
    # en la carpeta real del cliente.
    rutas_facturas = []
    valor_facturas = manifiesto.archivos.get("facturas")
    if isinstance(valor_facturas, list):
        rutas_facturas = [carpeta / nombre for nombre in valor_facturas]
    elif valor_facturas:
        carpeta_facturas = carpeta / valor_facturas
        if carpeta_facturas.is_dir():
            rutas_facturas = sorted(carpeta_facturas.glob("*.pdf"))

    return rutas, presentes, rutas_facturas


def _resolver_legado(carpeta):
    """Convencion original de nombres literales. Se conserva para las
    fixtures de prueba (ver docstring del modulo)."""
    rutas = {clave: carpeta / nombre for clave, nombre in ARCHIVOS.items()}
    presentes = {clave for clave, ruta in rutas.items() if ruta.exists()}

    carpeta_facturas = carpeta / "facturas"
    rutas_facturas = (sorted(carpeta_facturas.glob("*.pdf"))
                      if carpeta_facturas.is_dir() else [])

    return rutas, presentes, rutas_facturas


def revisar(carpeta, nit, periodo, municipio,
            cliente_ia=None) -> ContextoRevision:
    carpeta = Path(carpeta)
    manifiesto = None

    if (carpeta / NOMBRE_ARCHIVO).exists():
        manifiesto = leer_manifiesto(carpeta)  # ManifiestoIncompleto si falta algo
        if manifiesto.nit != nit or manifiesto.periodo != periodo:
            raise IdentidadIncompatible(
                "el manifiesto declara NIT %s / periodo %s, y se invoco con "
                "NIT %s / periodo %s"
                % (manifiesto.nit, manifiesto.periodo, nit, periodo))
        if manifiesto.municipio.strip().lower() != municipio.nombre.strip().lower():
            raise IdentidadIncompatible(
                "el manifiesto declara el municipio %s, y se invoco con %s"
                % (manifiesto.municipio, municipio.nombre))
        rutas, presentes, rutas_facturas = _resolver_via_manifiesto(carpeta, manifiesto)
    else:
        rutas, presentes, rutas_facturas = _resolver_legado(carpeta)

    if "borrador" not in presentes:
        raise FileNotFoundError("falta el borrador de la declaracion")
    if "auxiliar" not in presentes:
        raise FileNotFoundError("falta el libro auxiliar 2368")

    # 1.5: confirmar la naturaleza del documento antes de leerlo en serio.
    for rol in _ROLES_CON_FIRMA_TABULAR:
        if rol in presentes:
            verificar_tipo_documento(rol, rutas[rol])

    # X1 y M11: lo que el motor no puede decidir solo y el auditor declara.
    # Vacia no significa "todo bien": significa que nadie atesto nada.
    atestacion = leer_atestacion(carpeta)

    # M11: el motor detecta las candidatas por la naturaleza del saldo; el
    # auditor decide. Una candidata sin declarar bloquea C2 y C3.
    naturalezas = (leer_naturalezas(rutas["balance"])
                   if "balance" in presentes else {})
    acumulados = (leer_acumulados(rutas["balance"])
                  if "balance" in presentes else {})
    candidatas = {cuenta for cuenta, naturaleza in naturalezas.items()
                  if naturaleza == DEBITO}
    candidatas_sin_declarar = candidatas - set(atestacion.cuentas)
    # Lo atestado manda; lo detectado como debito y no declarado se excluye
    # igual -- excluir por naturaleza es una determinacion sobre los datos, no
    # una adivinanza -- y C13 lo deja escrito.
    excluidas_efectivas = atestacion.cuentas_excluidas() | candidatas_sin_declarar

    borrador = leer_borrador(rutas["borrador"])
    lineas = leer_auxiliar(rutas["auxiliar"])
    saldos = (leer_balance(rutas["balance"], excluidas_efectivas)
              if "balance" in presentes else None)
    filas_erp = leer_sap_retenciones(rutas["erp"]) if "erp" in presentes else None

    # C15 y la mitad legible de C12. El formato historico del cliente trae una
    # hoja por periodo con lo que declaro cada mes.
    historico = (leer_formato_historico(rutas["formato_historico"])
                 if "formato_historico" in presentes else {})
    anterior = historico.get(periodo_anterior(periodo))
    saldo_anterior = anterior.retenciones_declaradas if anterior else None
    # El PAGO no esta en el formato historico: exige el comprobante, que el
    # cliente no entrega. Sin el, C12 es NO EJECUTADO -- nunca OK.
    pago_anterior = None



    facturas = [leer_factura(p, nit_cliente=nit) for p in rutas_facturas]
    if facturas:
        presentes.add("facturas")

    c0 = verificar_identidad(borrador, lineas, nit, periodo)

    mapa = _mapa_actividad(borrador, filas_erp, lineas, municipio)
    recon = reconstruir(lineas, filas_erp, municipio, mapa)

    # V8: la poblacion sobre la que se juzga clasificacion son las lineas
    # del auxiliar con documento identificable. Sirve para decir "3 de 3" en
    # vez de dejar tres observaciones sueltas.
    documentos_revisados = len({l.referencia for l in lineas if l.referencia})

    resultados = [
        c0,
        controles.c1_formulario_cuadra(borrador, municipio),
        controles.c2_balance_vs_auxiliar(saldos, lineas),
        controles.c3_auxiliar_vs_erp(lineas, filas_erp),
        controles.c4_recalculo(recon),
        controles.c5_coherencia_cuenta_codigo(lineas, filas_erp, municipio),
        controles.c6_clasificacion_por_linea(recon, facturas, mapa, municipio),
        controles.c7_tarifas_vs_estatuto(borrador, municipio, atestacion),
        controles.c8_corte(lineas, periodo),
        controles.c9_reconstruccion_vs_borrador(recon, borrador, mapa),
        controles.c10_redondeo(borrador, recon),
        controles.c11_cotejo_facturas(lineas, facturas, municipio),
        controles.c12_continuidad(saldo_anterior, pago_anterior),
        controles.c13_formales(borrador, municipio, presentes,
                               candidatas_sin_declarar),
        controles.c14_compras_vs_servicios(recon, municipio),
        controles.c15_formato_historico(borrador, historico, periodo),
    ]

    # D7: la IA tiene CARRIL PROPIO. No modifica C0..C15; sus salidas entran
    # como controles con los mismos estados, de modo que un hallazgo suyo
    # bloquee la conclusion limpia igual que uno de C9. Si el modelo no se
    # puede llamar, salen NO_EJECUTADO -- nunca OK.
    if cliente_ia is not None:
        resultados.append(
            controles_ia.ia1_plausibilidad(recon, borrador, municipio,
                                           cliente=cliente_ia))
        informe_previo = consolidar(resultados)
        resultados.append(
            controles_ia.ia3_consistencia(resultados, informe_previo,
                                          cliente=cliente_ia))

    return ContextoRevision(
        nit=nit,
        periodo=periodo,
        municipio=municipio,
        borrador=borrador,
        lineas=lineas,
        saldos=saldos,
        filas_erp=filas_erp,
        facturas=facturas,
        reconstruccion=recon,
        resultados=resultados,
        informe=consolidar(resultados,
                            documentos_revisados=documentos_revisados),
        huellas={clave: huella(rutas[clave]) for clave in sorted(presentes)
                 if clave in rutas},
        insumos_obtenidos=presentes,
        total_auxiliar=sum((l.retencion for l in lineas), Decimal("0")),
        total_erp=sum((f.retencion for f in (filas_erp or [])), Decimal("0")),
        manifiesto=manifiesto,
        atestacion=atestacion,
        candidatas_sin_declarar=frozenset(candidatas_sin_declarar),
        acumulados=acumulados,
        rutas=dict(rutas),
    )
