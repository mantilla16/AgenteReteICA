"""Sinonimos de columna por tipo de documento contable (1.2/1.3/1.4).

D3: los sinonimos son GLOBALES por ERP/tipo de documento, no por cliente.
'Saldo Haber per.inf.' es una etiqueta de SAP, no de Terlica.

D4: esto aplica SOLO a fuentes CONTABLES (auxiliar, balance, reporte del
ERP). NUNCA al borrador: ahi la posicion de los renglones ES el objeto de
prueba, y ese archivo se procesa con patrones fijos en ingesta/borrador_pdf.py.
Garantia mecanica: este modulo no importa nada de ingesta/borrador_pdf.py, y
hay una prueba que lo verifica (ver tests/test_parametros.py).

D5: se senala la ETIQUETA de la columna, no la letra/indice. Los lectores
sobreviven a que el ERP mueva una columna de lugar.

1.4 - tres condiciones no negociables de esta parametrizacion:
  a) se resuelve UNA vez al cargar, antes de correr los controles - nunca
     despues de ver fallar un control (eso seria elegir la columna que pone
     el control en verde, el mismo defecto circular del motor viejo).
  b) queda escrito: en el manifiesto y en la hoja Parametros del papel.
  c) un rol sin mapear = NO EJECUTADO, igual que un archivo faltante. Nunca
     se adivina la columna "mas parecida": localizar_columnas exige
     coincidencia EXACTA de etiqueta contra la lista de sinonimos.
"""

from dataclasses import dataclass


class ColumnaNoIdentificada(Exception):
    """1.3: error tipado, no un ValueError generico.

    Lleva el rol semantico que falto, su explicacion EN TERMINOS DE
    AUDITORIA (no de nombre de columna), y los encabezados que si estaban
    disponibles en el archivo, para que el auditor pueda corregir sin leer
    el codigo.
    """

    def __init__(self, rol: str, explicacion: str, encabezados_disponibles):
        self.rol = rol
        self.explicacion = explicacion
        self.encabezados_disponibles = tuple(sorted(
            e for e in encabezados_disponibles if e))
        super().__init__(
            "no se identifico la columna del rol '%s' (%s). Encabezados "
            "disponibles en el archivo: %s"
            % (rol, explicacion,
               ", ".join(self.encabezados_disponibles) or "(ninguno)"))


@dataclass(frozen=True)
class Rol:
    nombre: str
    explicacion: str
    sinonimos: tuple


# --------------------------------------------------------------------------
# Firmas: las etiquetas que identifican el TIPO de documento (1.5). Deben
# coexistir en una misma fila para reconocerlo.
# --------------------------------------------------------------------------

FIRMA_AUXILIAR = ("Cuenta", "Importe en ML")
FIRMA_BALANCE = ("Cta.mayor", "Saldo Haber per.inf.")
FIRMA_ERP = ("Acreedor", "Importe qst en MI")

# Firmas alternativas por tipo. Cada cliente puede exportar con la
# transaccion que quiera; se acepta la primera que coincida. El primer
# elemento es la firma "rica" (con cuenta contable por linea, que habilita
# los cruces por renglon); las demas son formatos AGREGADOS: solo permiten
# el cruce universal del total, no los cruces por cuenta.
FIRMAS_ALTERNATIVAS = {
    "auxiliar": [
        FIRMA_AUXILIAR,                              # TERLICA (FBL3N SAP)
        ("Asignación", "Importe en moneda local"),   # Agroingenium (FAGLL03H)
        ("Asignacion", "Importe en moneda local"),   # sin tilde
    ],
    "balance": [FIRMA_BALANCE],
    "erp": [FIRMA_ERP],
}

FIRMAS_POR_TIPO = {tipo: firmas[0]
                   for tipo, firmas in FIRMAS_ALTERNATIVAS.items()}

# --------------------------------------------------------------------------
# Roles semanticos por documento. El primer sinonimo es el que ya se
# conocia; los siguientes son alias aprendidos, y cada uno anota en el
# comentario donde se origino (D3).
# --------------------------------------------------------------------------

ROLES_AUXILIAR = {
    "cuenta": Rol("cuenta", "la cuenta contable de cada linea", ("Cuenta",)),
    "nit": Rol("nit", "el NIT del tercero (OJO: no es la columna 'Tercero', "
                      "esa trae el nombre)", ("Asignación", "Asignacion")),
    "nombre": Rol("nombre", "el nombre o razon social del tercero",
                 ("Tercero",)),
    "fecha_documento": Rol("fecha_documento", "la fecha del documento fuente "
                          "(factura); NO el corte real",
                          ("Fecha doc.",)),
    "fecha_contabilizacion": Rol(
        "fecha_contabilizacion",
        "la fecha en que se contabilizo: es el corte real que usa C8, "
        "distinto de la fecha del documento", ("Fe.contab.",)),
    "referencia": Rol("referencia", "la referencia o numero de factura",
                      ("Referencia",)),
    "documento": Rol("documento", "el numero de documento contable",
                     ("Nº doc.", "N° doc.")),
    "concepto": Rol("concepto", "el texto o concepto de la linea, usado "
                    "para clasificar la naturaleza compra/servicio (C6)",
                    ("Texto",)),
    "importe": Rol(
        "importe",
        "el importe de la retencion practicada. Viene en negativo "
        "(naturaleza credito) y se normaliza a positivo al leerlo",
        ("Importe en ML",)),
}

ROLES_BALANCE = {
    "cuenta": Rol("cuenta", "la cuenta contable", ("Cta.mayor",)),
    "movimiento_periodo": Rol(
        "movimiento_periodo",
        "el movimiento DEL PERIODO, no el saldo acumulado; el acumulado "
        "incluye el arrastre de meses anteriores y haria fallar C2 todos "
        "los meses", ("Saldo Haber per.inf.",)),
}

ROLES_ERP = {
    "nit": Rol("nit", "el NIT del acreedor/tercero", ("Acreedor",)),
    "codigo_ret": Rol("codigo_ret", "el codigo de retencion del ERP, usado "
                      "por C5 para verificar coherencia con la cuenta "
                      "contable", ("Ret",)),
    "base": Rol(
        "base",
        "la base sujeta a retencion. NO es 'Importe en MD': esa columna "
        "viene con IVA incluido y descuadra C4", ("Impte.base Qst en MI",)),
    "retencion": Rol("retencion", "el valor de la retencion practicada",
                     ("Importe qst en MI",)),
}


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def _fila_a_etiquetas(fila):
    return {_texto(celda): columna for columna, celda in enumerate(fila)}


def localizar_columnas(filas, roles: dict, firma: tuple):
    """Resuelve cada rol a su indice de columna por ETIQUETA (D5).

    Busca la fila cuyo encabezado contenga TODAS las etiquetas de la firma
    (1.5: asi se reconoce el tipo de documento). Dentro de esa fila, cada
    rol semantico se resuelve contra su lista de sinonimos, en orden: el
    primer sinonimo presente en el encabezado gana (1.4.c: nunca se adivina
    "la columna mas parecida", solo coincidencias exactas de etiqueta).

    Devuelve (indice_de_fila, {clave_de_rol: indice_de_columna}).
    Lanza ColumnaNoIdentificada si no hay fila con la firma, o si dentro de
    esa fila algun rol no tiene ningun sinonimo presente.
    """
    for indice, fila in enumerate(filas):
        etiquetas = _fila_a_etiquetas(fila)
        if all(marca in etiquetas for marca in firma):
            resueltas = {}
            for clave, rol in roles.items():
                columna = next(
                    (etiquetas[s] for s in rol.sinonimos if s in etiquetas),
                    None)
                if columna is None:
                    raise ColumnaNoIdentificada(
                        rol.nombre, rol.explicacion, etiquetas.keys())
                resueltas[clave] = columna
            return indice, resueltas

    raise ColumnaNoIdentificada(
        "encabezado",
        "no se encontro ninguna fila que tenga, a la vez, las columnas %s"
        % ", ".join(firma),
        ())


def detectar_tipo_documento(filas):
    """1.5: identifica que tipo de documento es un archivo por su firma.

    Devuelve 'auxiliar', 'balance', 'erp' o None. Cada tipo puede tener
    varias firmas -- clientes distintos exportan con transacciones distintas
    de SAP -- y la primera que coincida gana. Ese orden importa: la firma
    rica (con cuenta por linea) va primero para preferir el auxiliar que
    permite cruces por renglon sobre el que solo permite el cruce del total.
    """
    for indice, fila in enumerate(filas):
        etiquetas = _fila_a_etiquetas(fila)
        for tipo, firmas in FIRMAS_ALTERNATIVAS.items():
            for firma in firmas:
                if all(marca in etiquetas for marca in firma):
                    return tipo
    return None
