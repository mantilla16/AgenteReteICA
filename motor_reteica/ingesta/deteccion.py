"""Detector automatico de formato de reportes contables.

Reemplaza el reconocimiento por FIRMA de etiqueta exacta
(parametros/columnas.py::localizar_columnas) por una deteccion que combina:

  1. VIA RAPIDA por sinonimos: si la etiqueta de una columna esta en el
     diccionario de alias conocidos, se resuelve directo. Cubre los formatos
     ya vistos (SAP GRC/FBL3N, SAP Business One) de forma determinista.

  2. VIA GENERAL por contenido: cuando la etiqueta no basta, se infiere el rol
     por lo que HAY en la columna -- una columna cuyos valores parecen NIT es
     el NIT, una cuyos valores son fechas es una fecha, la columna numerica
     cuya suma cuadra con el totalizador es el importe. Asi absorbe ERPs que
     nadie ha visto sin agregar codigo.

REGLA DE ORO (ver feedback del proyecto): esto SOLO propone un mapeo. NO
calcula nada del papel. La confianza del mapeo la decide la bateria de cuadres
deterministicos (ingesta/cuadres.py), no este modulo ni un humano. Un mapeo
que no cuadra se rechaza; nunca se produce un papel sobre columnas dudosas.

El resultado (Deteccion) tiene la MISMA forma que devolvia localizar_columnas
-- (fila_encabezado, {rol: indice_columna}) -- mas metadata que los formatos
nuevos necesitan (cuenta_raiz, filtro de jerarquia, convencion de signo), de
modo que los lectores downstream cambian minimo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# La cuenta de ReteICA es 2368 en el PUC colombiano -- es un invariante del
# dominio (Decreto 2650), no configuracion por cliente. Las sub-cuentas
# (2368010007, 23680503, 2368050301...) varian, pero todas cuelgan de 2368.
_PUC_RETEICA = "2368"

# --------------------------------------------------------------------------
# Sinonimos por rol: la via rapida. El primer match gana. Comparacion sin
# acentos, sin espacios extra y sin distinguir mayusculas (ver _norm).
# --------------------------------------------------------------------------
_SINONIMOS = {
    "cuenta": (
        "cuenta contable", "cta.mayor", "cta mayor", "cuenta", "no. cuenta",
        "nro cuenta", "codigo cuenta", "cuenta mayor",
    ),
    "nombre_cuenta": (
        "nombre cuenta contable", "texto breve", "nombre cuenta",
        "descripcion cuenta", "nombre de la cuenta",
    ),
    "nit": (
        "nit", "identificacion", "no. identificacion", "cedula/nit",
        "asignacion", "documento tercero", "id tercero",
    ),
    "nombre": (
        "nombre sn", "tercero", "razon social", "nombre tercero",
        "nombre proveedor", "beneficiario", "proveedor",
    ),
    "fecha_documento": (
        "fecha doc.", "fecha de documento", "fecha documento", "fecha factura",
    ),
    "fecha_contabilizacion": (
        "fe.contab.", "fecha contabilizacion", "fecha de contabilizacion",
        "fecha contable", "fecha registro",
    ),
    "referencia": (
        "referencia", "referencia 1", "no. origen (doc. marketing)",
        "no factura", "num factura",
    ),
    "documento": (
        "n. doc.", "no. doc.", "n doc.", "n. documento", "no documento",
        "no. transaccion (asiento)", "no. transaccion", "documento",
        "asiento",
    ),
    "concepto": (
        "texto", "comentarios (lineas)", "comentarios", "detalle",
        "concepto", "glosa", "observaciones",
    ),
    # Importe: columna UNICA con signo (SAP GRC). El credito es la retencion.
    "importe": (
        "importe en ml", "importe en moneda local", "importe",
    ),
    # Movimiento separado en dos columnas (SAP Business One y balances).
    "debito": (
        "debito moneda local", "debito", "periodo de informe debe",
        "debe", "movimiento debito",
    ),
    "credito": (
        "credito moneda local", "credito", "saldo haber per.inf.",
        "haber", "retencion", "movimiento credito",
    ),
    # Solo balances.
    "saldo_inicial": (
        "saldo inicial (moneda local)", "saldo inicial", "arrastre de saldos",
        "saldo anterior",
    ),
    "saldo_final": (
        "saldo final (moneda local)", "saldo final", "saldo acumulado",
        "saldo actual",
    ),
    # Marca de fila-transaccion en reportes jerarquicos (SAP B1: "AstCont").
    "serie": ("serie",),
}

# Roles que, por su semantica, llevan un IMPORTE monetario. Se usan tanto en
# la via de contenido como en los cuadres.
_ROLES_MONETARIOS = ("importe", "debito", "credito", "saldo_inicial",
                     "saldo_final")


@dataclass(frozen=True)
class Deteccion:
    """Mapeo propuesto para un archivo. Lo valida la bateria de cuadres."""

    tipo: str                       # "auxiliar" | "balance" | "erp" | "desconocido"
    fila_encabezado: int            # indice 0-based de la fila de encabezado
    columnas: dict                  # {rol: indice_columna}
    cuenta_raiz: str                # prefijo PUC para FILTRAR cuentas ICA ("2368")
    convencion_signo: str           # "columna_unica" | "columnas_separadas"
    filtro_transaccion: tuple | None = None   # (indice_col, valor) o None
    # Sub-cuentas ICA concretas del archivo y su prefijo comun -- para MOSTRAR
    # en el wizard ("las cuentas ICA de este cliente son 2368010xxx"), nunca
    # para excluir: filtrar por el prefijo comun podria dejar fuera una cuenta
    # nueva que aparezca un mes.
    prefijo_subcuentas: str = ""
    subcuentas: tuple = ()
    etiquetas: tuple = ()           # encabezados crudos, para diagnostico
    origen: dict = field(default_factory=dict)  # {rol: "sinonimo"|"contenido"}

    def tiene(self, *roles) -> bool:
        return all(r in self.columnas for r in roles)


# --------------------------------------------------------------------------
# Normalizacion y predicados de contenido
# --------------------------------------------------------------------------

def _norm(valor) -> str:
    if valor is None:
        return ""
    s = str(valor).strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


_RE_NIT = re.compile(r"^(pn|nit|cc)?\s*\d{5,12}(-\d)?$", re.IGNORECASE)
_RE_CUENTA = re.compile(r"^\d{4,}$")
_FORMATOS_FECHA = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d",
                   "%d-%m-%Y")


def _es_nit(valor) -> bool:
    if isinstance(valor, (int, float)):
        return 10_000 <= abs(valor) <= 9_999_999_999_99
    return bool(_RE_NIT.match(str(valor).strip())) if valor else False


def _es_cuenta(valor) -> bool:
    s = re.sub(r"\D", "", str(valor)) if valor is not None else ""
    return bool(_RE_CUENTA.match(s))


def _es_fecha(valor) -> bool:
    if isinstance(valor, (datetime, date)):
        return True
    if not valor:
        return False
    s = str(valor).strip().split(" ")[0]
    for f in _FORMATOS_FECHA:
        try:
            datetime.strptime(s, f)
            return True
        except ValueError:
            pass
    return False


def _a_decimal(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor))
    s = str(valor).strip()
    # SAP escribe el signo al final ("1.028.425-") y usa punto de miles.
    negativo = s.endswith("-")
    s = s.rstrip("-").replace(".", "").replace(",", ".").replace(" ", "")
    if not s or not re.match(r"^-?\d+(\.\d+)?$", s):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if negativo else d


def _es_numero(valor) -> bool:
    return _a_decimal(valor) is not None


def _texto_largo(valor) -> bool:
    return isinstance(valor, str) and len(valor.strip()) >= 8 and \
        not _es_numero(valor) and not _es_fecha(valor)


# --------------------------------------------------------------------------
# Deteccion de la fila de encabezado
# --------------------------------------------------------------------------

def _puntua_encabezado(fila) -> int:
    """Cuantos roles distintos reconoce esta fila por sinonimo."""
    reconocidos = set()
    for celda in fila:
        etiqueta = _norm(celda)
        for rol, alias in _SINONIMOS.items():
            if etiqueta in alias:
                reconocidos.add(rol)
    return len(reconocidos)


def _detectar_encabezado(filas) -> int:
    """La fila que reconoce mas roles por etiqueta. Empate: la primera.

    Si ninguna fila reconoce >=2 roles (archivo con encabezados totalmente
    ajenos), devuelve la primera fila con >=3 celdas de texto no numerico,
    que la via de contenido usara como base.
    """
    mejor_idx, mejor_puntaje = -1, 0
    for idx, fila in enumerate(filas[:40]):
        p = _puntua_encabezado(fila)
        if p > mejor_puntaje:
            mejor_idx, mejor_puntaje = idx, p
    if mejor_puntaje >= 2:
        return mejor_idx

    for idx, fila in enumerate(filas[:40]):
        textos = sum(1 for c in fila if isinstance(c, str) and c.strip()
                     and not _es_numero(c))
        if textos >= 3:
            return idx
    return 0


# --------------------------------------------------------------------------
# Mapeo de roles: sinonimo primero, contenido despues
# --------------------------------------------------------------------------

def _mapear_por_sinonimo(encabezado):
    columnas, origen = {}, {}
    for idx, celda in enumerate(encabezado):
        etiqueta = _norm(celda)
        if not etiqueta:
            continue
        for rol, alias in _SINONIMOS.items():
            if rol in columnas:
                continue
            if etiqueta in alias:
                columnas[rol] = idx
                origen[rol] = "sinonimo"
                break
    return columnas, origen


def _perfil_columna(filas, idx, inicio):
    """Que porcentaje de las celdas con dato de la columna cumple cada test."""
    muestra = [fila[idx] for fila in filas[inicio + 1:inicio + 200]
               if idx < len(fila) and fila[idx] not in (None, "")]
    if not muestra:
        return None
    n = len(muestra)
    return {
        "n": n,
        "nit": sum(1 for v in muestra if _es_nit(v)) / n,
        "cuenta": sum(1 for v in muestra if _es_cuenta(v)) / n,
        "fecha": sum(1 for v in muestra if _es_fecha(v)) / n,
        "numero": sum(1 for v in muestra if _es_numero(v)) / n,
        "texto": sum(1 for v in muestra if _texto_largo(v)) / n,
    }


# Roles que el fallback de contenido intenta inferir, SEGUN el tipo de
# documento. Un balance no tiene NIT ni tercero por linea: buscarlos ahi solo
# produce falsos positivos (una columna numerica de saldos "parece" NIT). Por
# eso el fallback se limita a lo que ese tipo realmente necesita.
_ROLES_CONTENIDO = {
    "auxiliar": (("cuenta", "cuenta", 0.7), ("nit", "nit", 0.6),
                 ("fecha_documento", "fecha", 0.6), ("nombre", "texto", 0.5),
                 ("concepto", "texto", 0.4)),
    "balance": (("cuenta", "cuenta", 0.7),),
    "erp": (("cuenta", "cuenta", 0.7), ("nit", "nit", 0.6)),
    None: (("cuenta", "cuenta", 0.7),),
}


def _mapear_por_contenido(filas, inicio, columnas, origen, tipo):
    """Rellena los roles que el sinonimo no resolvio, mirando el contenido.

    Solo intenta los roles relevantes para `tipo` (ver _ROLES_CONTENIDO): en un
    balance no se infiere NIT/tercero porque ahi no existen y el heuristico los
    confundiria con columnas de saldos.
    """
    ancho = max((len(f) for f in filas[inicio:inicio + 5]), default=0)
    usadas = set(columnas.values())
    perfiles = {i: _perfil_columna(filas, i, inicio) for i in range(ancho)}

    def elegir(test, umbral):
        mejor, mejor_score = None, umbral
        for i, p in perfiles.items():
            if p is None or i in usadas:
                continue
            if p[test] > mejor_score:
                mejor, mejor_score = i, p[test]
        return mejor

    for rol, test, umbral in _ROLES_CONTENIDO.get(tipo, _ROLES_CONTENIDO[None]):
        if rol in columnas:
            continue
        idx = elegir(test, umbral)
        if idx is not None:
            columnas[rol] = idx
            origen[rol] = "contenido"
            usadas.add(idx)
    return columnas, origen


# --------------------------------------------------------------------------
# Metadata: cuenta raiz, convencion de signo, filtro de jerarquia
# --------------------------------------------------------------------------

def _subcuentas_ica(filas, inicio, col_cuenta):
    """Las sub-cuentas ICA distintas del archivo y su prefijo comun.

    El prefijo es SOLO informativo (para el wizard). El filtro operativo usa
    siempre "2368" (invariante PUC): narrar por prefijo comun podria excluir
    una sub-cuenta que aparezca un mes nuevo, justo el error que este rediseno
    evita.
    """
    if col_cuenta is None:
        return "", ()
    vistas = []
    for fila in filas[inicio + 1:]:
        if col_cuenta >= len(fila):
            continue
        s = re.sub(r"\D", "", str(fila[col_cuenta] or ""))
        # Una cuenta ICA de detalle, no la fila padre "2368" ni "23680503"
        # sin sufijo: al menos 9 digitos tras el prefijo PUC. Aun asi se
        # recogen todas las 2368* para calcular el prefijo comun con fidelidad.
        if s.startswith(_PUC_RETEICA) and s not in vistas:
            vistas.append(s)
    if not vistas:
        return "", ()
    prefijo = vistas[0]
    for c in vistas[1:]:
        while not c.startswith(prefijo):
            prefijo = prefijo[:-1]
    return prefijo, tuple(vistas)


def _detectar_filtro_jerarquia(filas, inicio, columnas):
    """Si hay columna 'serie' con un valor marca de transaccion, devolverlo.

    En SAP B1 las filas de detalle traen Serie='AstCont' y las de subtotal la
    dejan vacia. El filtro deja pasar solo las transacciones reales.
    """
    col = columnas.get("serie")
    if col is None:
        return None
    valores = {}
    for fila in filas[inicio + 1:]:
        if col < len(fila) and fila[col] not in (None, ""):
            v = str(fila[col]).strip()
            valores[v] = valores.get(v, 0) + 1
    if not valores:
        return None
    marca = max(valores, key=valores.get)
    return (col, marca)


def _convencion_signo(columnas):
    if "debito" in columnas and "credito" in columnas:
        return "columnas_separadas"
    return "columna_unica"


def _clasificar_tipo(columnas):
    """auxiliar vs balance por los roles presentes.

    Balance: trae saldos (inicial/final o acumulado) por cuenta y NO trae
    detalle por tercero-transaccion. Auxiliar: trae movimiento por linea.
    Como en SAP B1 el mismo layout sirve para ambos (cambia el rango), el
    llamador puede forzar el tipo; esto es solo la mejor apuesta.
    """
    if "saldo_inicial" in columnas or "saldo_final" in columnas:
        if "importe" not in columnas and "credito" not in columnas:
            return "balance"
    if "importe" in columnas or "credito" in columnas or "debito" in columnas:
        return "auxiliar"
    return "desconocido"


# --------------------------------------------------------------------------
# API publica
# --------------------------------------------------------------------------

def detectar(filas, tipo_esperado=None) -> Deteccion:
    """Analiza las filas crudas y propone un mapeo.

    `tipo_esperado` ("auxiliar"|"balance"|"erp") fuerza la clasificacion
    cuando el llamador ya sabe que rol cumple el archivo (lo sabe por el
    manifiesto/wizard). Si es None, se infiere.
    """
    # OJO: NO se filtran las filas vacias. Antes se filtraban y se reindexaba,
    # pero los lectores (adaptador, cuadres) usan la lista ORIGINAL con
    # d.fila_encabezado: si el archivo trae filas vacias antes del encabezado
    # (SAP suele dejar 5), los indices quedaban corridos y se leian 0 lineas.
    # _detectar_encabezado ya ignora las vacias (puntuan 0), asi que operar
    # sobre la lista original es correcto y mantiene los indices validos.
    filas = filas or [[]]
    inicio = _detectar_encabezado(filas)
    encabezado = filas[inicio] if inicio < len(filas) else []

    columnas, origen = _mapear_por_sinonimo(encabezado)
    # La clasificacion preliminar (para saber que roles inferir) usa lo que el
    # sinonimo ya resolvio; el tipo_esperado del llamador manda si viene.
    tipo = tipo_esperado or _clasificar_tipo(columnas)
    columnas, origen = _mapear_por_contenido(filas, inicio, columnas, origen,
                                             tipo)

    prefijo, subcuentas = _subcuentas_ica(filas, inicio, columnas.get("cuenta"))
    filtro = _detectar_filtro_jerarquia(filas, inicio, columnas)
    signo = _convencion_signo(columnas)
    tipo = tipo_esperado or _clasificar_tipo(columnas)

    return Deteccion(
        tipo=tipo,
        fila_encabezado=inicio,
        columnas=columnas,
        cuenta_raiz=_PUC_RETEICA,
        convencion_signo=signo,
        filtro_transaccion=filtro,
        prefijo_subcuentas=prefijo,
        subcuentas=subcuentas,
        etiquetas=tuple(str(c).strip() if c is not None else "" for c in encabezado),
        origen=origen,
    )
