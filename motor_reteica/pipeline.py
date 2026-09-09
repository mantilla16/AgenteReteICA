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

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from motor_reteica import controles
from motor_reteica.hallazgos import consolidar
from motor_reteica.identidad import (IdentidadIncompatible, huella,
                                     verificar_identidad, verificar_tipo_documento)
from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.balance import leer_balance
from motor_reteica.ingesta.borrador_pdf import leer_borrador
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

_ROLES_ARCHIVO_UNICO = ("borrador", "auxiliar", "balance", "erp", "pago_anterior")
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


def _mapa_actividad(borrador, filas_erp, lineas, municipio):
    """Asigna cada tercero a un renglon del borrador.

    Se toma del borrador SOLO para agrupar. La tarifa y la base nunca salen
    de aqui: vienen de la cuenta contable y del reporte del ERP.
    """
    base_por_nit = {f.nit: f.base for f in (filas_erp or [])}
    # Sin reporte del ERP la base se deriva de la retencion: es imprecisa
    # (hasta 91 pesos por tercero) pero basta para emparejar renglones, que
    # es lo unico que este mapa hace.
    derivadas = {}
    for linea in lineas:
        tarifa = municipio.tarifa_por_cuenta[linea.cuenta]
        derivadas[linea.nit] = derivadas.get(linea.nit, Decimal("0")) + (
            linea.retencion / tarifa).quantize(Decimal("1"))

    mapa = {}
    disponibles = list(borrador.actividades)

    for nit in sorted({l.nit for l in lineas}):
        base = base_por_nit.get(nit, derivadas.get(nit))
        elegida = None
        if base is not None:
            for actividad in disponibles:
                if actividad.base == base or abs(actividad.base - base) < 1000:
                    elegida = actividad
                    break
        if elegida is not None:
            mapa[nit] = elegida.codigo
            disponibles.remove(elegida)
    return mapa


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


def revisar(carpeta, nit, periodo, municipio) -> ContextoRevision:
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

    borrador = leer_borrador(rutas["borrador"])
    lineas = leer_auxiliar(rutas["auxiliar"])
    saldos = leer_balance(rutas["balance"]) if "balance" in presentes else None
    filas_erp = leer_sap_retenciones(rutas["erp"]) if "erp" in presentes else None

    facturas = [leer_factura(p, nit_cliente=nit) for p in rutas_facturas]
    if facturas:
        presentes.add("facturas")

    c0 = verificar_identidad(borrador, lineas, nit, periodo)

    mapa = _mapa_actividad(borrador, filas_erp, lineas, municipio)
    recon = reconstruir(lineas, filas_erp, municipio, mapa)

    resultados = [
        c0,
        controles.c1_formulario_cuadra(borrador, municipio),
        controles.c2_balance_vs_auxiliar(saldos, lineas),
        controles.c3_auxiliar_vs_erp(lineas, filas_erp),
        controles.c4_recalculo(recon),
        controles.c5_coherencia_cuenta_codigo(lineas, filas_erp, municipio),
        controles.c6_clasificacion_por_linea(recon, facturas, mapa, municipio),
        controles.c7_tarifas_vs_estatuto(borrador, municipio),
        controles.c8_corte(lineas, periodo),
        controles.c9_reconstruccion_vs_borrador(recon, borrador),
        controles.c10_redondeo(borrador, recon),
        controles.c11_cotejo_facturas(lineas, facturas, municipio),
        controles.c12_continuidad(None, None),
        controles.c13_formales(borrador, municipio, presentes),
        controles.c14_compras_vs_servicios(recon, municipio),
    ]

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
        informe=consolidar(resultados),
        huellas={clave: huella(rutas[clave]) for clave in sorted(presentes)
                 if clave in rutas},
        insumos_obtenidos=presentes,
        total_auxiliar=sum((l.retencion for l in lineas), Decimal("0")),
        total_erp=sum((f.retencion for f in (filas_erp or [])), Decimal("0")),
        manifiesto=manifiesto,
    )
