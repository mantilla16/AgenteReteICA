"""Parser del borrador de la declaracion mensual de ReteICA (PDF).

El borrador es OBJETO DE PRUEBA. Este modulo solo lo lee; ningun parametro
del motor puede originarse aqui.

Trampas del formulario de Santa Marta, verificadas contra el PDF real:
  - Las 3 paginas son copias (contribuyente / alcaldia / banco). Se lee solo
    la primera; leerlas todas triplicaria renglones y actividades.
  - La descripcion de la actividad se parte en dos lineas. La expresion
    regular ancla en la linea que trae los tres numeros al final, asi que la
    continuacion se ignora sola.
  - El renglon 26 emite un '0' suelto y el 29 arrastra 'DESCUENTO SANCION 0'.
    Exigir un caracter no numerico tras el numero de renglon descarta ambos.
  - El formulario imprime en el renglon 31 la formula '(renglon 27+28+29)',
    que NO se cumple: el 28 reexpresa el 27, no lo suma. C1 debe verificar
    31 = 27 + 29 + 30.

M12 -- RIESGO NO ELIMINADO, PERO CON RED DE SEGURIDAD: si algun mes el cuadro
C tuviera mas actividades de las que caben en una pagina y se desbordara a una
pagina REAL de continuacion (distinta de las 3 copias identicas ya conocidas),
`pdf.pages[0]` no la leeria y esas actividades se perderian en silencio... si
nada mas las verificara. Pero C1 ya suma el impuesto y la base de
`borrador.actividades` y los compara contra los renglones 23/24 del propio
PDF: una actividad truncada hace que esa suma deje de cuadrar, y C1 falla con
el impacto en pesos de lo que falto, ANTES de tocar la contabilidad. No se
escribio codigo de paginacion especulativo para un layout que nunca se ha
visto: se verifico (test_c1_cierra_el_riesgo_m12...) que la red de seguridad
que ya existia de verdad ataja este caso.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

_RE_ACTIVIDAD = re.compile(r"^(\d{4}) - (.+?) (\d+) ([\d.]+) ([\d.]+)$")
_RE_RENGLON = re.compile(r"^(\d{2}) \D.*?([\d.]+)$")
_RE_FECHA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_MARCA = "☒"
_VACIA = "☐"


@dataclass(frozen=True)
class ActividadDeclarada:
    codigo: str
    descripcion: str
    tarifa: Decimal
    base: Decimal
    impuesto: Decimal


@dataclass(frozen=True)
class Borrador:
    nit: str
    razon_social: str
    municipio: str
    anio: int
    periodo: str
    numero_formulario: str
    renglones: dict
    actividades: list
    firma_revisor_fiscal: bool
    # Fecha maxima de presentacion/pago que trae impresa el propio formulario.
    # Es la fuente correcta -- cada declaracion la trae -- en vez de un
    # calendario cableado por municipio que habria que actualizar cada mes.
    fecha_maxima: date = None


def _a_decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").strip())


def _periodo(lineas: list) -> tuple:
    anio = next(int(l.split()[-1]) for l in lineas if l.startswith("AÑO GRAVABLE 2"))

    # La fila de PERIODO trae una casilla por mes. Antes se exigia == 7 casillas
    # (el formulario de julio de TERLICA, ENE-JUL). El de agosto de ZFT trae 8
    # (ENE-AGO), y en general cada mes puede traer un numero distinto: el que
    # exigia 7 hacia fallar todo el lector con StopIteration y el papel salia
    # vacio. Ahora se toma la fila con MAS casillas que ademas trae la marcada.
    candidatas = [l for l in lineas
                  if _MARCA in l and (l.count(_VACIA) + l.count(_MARCA)) >= 2]
    fila = max(candidatas, key=lambda l: l.count(_VACIA) + l.count(_MARCA))

    # El mes = cuantas casillas hay hasta la marcada, inclusive. Se cuentan solo
    # los tokens de casilla (la fila puede traer basura del codigo de barras
    # despues de las casillas, que index() no debe confundir).
    mes = 0
    for token in fila.split():
        if token in (_VACIA, _MARCA):
            mes += 1
            if token == _MARCA:
                break
    return anio, "%d-%02d" % (anio, mes)


def _valor_siguiente(lineas: list, etiqueta: str) -> str:
    return lineas[lineas.index(etiqueta) + 1]


def _fecha_maxima(lineas: list):
    """La fecha maxima de presentacion/pago impresa en el formulario.

    Aparece como una linea dd/mm/aaaa justo despues del rotulo 'FECHA MAXIMA
    DE PRESENTACION Y/O PAGO'. None si el PDF no la trae legible.
    """
    for i, linea in enumerate(lineas):
        u = linea.upper()
        if "FECHA" in u and ("MAXIMA" in u or "MÁXIMA" in u):
            for siguiente in lineas[i + 1:i + 4]:
                m = _RE_FECHA.match(siguiente.strip())
                if m:
                    dia, mes, anio = (int(x) for x in m.groups())
                    try:
                        return date(anio, mes, dia)
                    except ValueError:
                        return None
    return None


def leer_borrador(ruta: Path) -> Borrador:
    with pdfplumber.open(ruta) as pdf:
        lineas = [l.strip() for l in pdf.pages[0].extract_text().split("\n")]

    anio, periodo = _periodo(lineas)

    actividades = []
    for linea in lineas:
        encontrado = _RE_ACTIVIDAD.match(linea)
        if encontrado:
            codigo, descripcion, por_mil, base, impuesto = encontrado.groups()
            actividades.append(ActividadDeclarada(
                codigo=codigo,
                descripcion=descripcion.strip(),
                tarifa=Decimal(por_mil) / Decimal("1000"),
                base=_a_decimal(base),
                impuesto=_a_decimal(impuesto),
            ))

    renglones = {}
    for linea in lineas:
        encontrado = _RE_RENGLON.match(linea)
        if encontrado and 11 <= int(encontrado.group(1)) <= 32:
            renglones[encontrado.group(1)] = _a_decimal(encontrado.group(2))

    inicio_nit = next(i for i, l in enumerate(lineas) if l.startswith("2. NÚMERO"))
    nit = next(l for l in lineas[inicio_nit:] if l.isdigit())

    municipio_y_depto = _valor_siguiente(
        lineas, "MUNICIPIO O DISTRITO DE LA DIRECCION DEPARTAMENTO")

    return Borrador(
        nit=nit,
        razon_social=_valor_siguiente(lineas, "1. APELLIDOS Y NOMBRES O RAZÓN SOCIAL"),
        municipio=municipio_y_depto.rsplit(" ", 1)[0],
        anio=anio,
        periodo=periodo,
        numero_formulario=next(
            l.split()[-1] for l in lineas if "NÚMERO DE FORMULARIO" in l),
        renglones=renglones,
        actividades=actividades,
        firma_revisor_fiscal=any("FRMA_RVSR_FSCL" in l for l in lineas),
        fecha_maxima=_fecha_maxima(lineas),
    )
