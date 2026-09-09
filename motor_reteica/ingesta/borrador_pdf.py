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
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pdfplumber

_RE_ACTIVIDAD = re.compile(r"^(\d{4}) - (.+?) (\d+) ([\d.]+) ([\d.]+)$")
_RE_RENGLON = re.compile(r"^(\d{2}) \D.*?([\d.]+)$")
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


def _a_decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").strip())


def _periodo(lineas: list) -> tuple:
    anio = next(int(l.split()[-1]) for l in lineas if l.startswith("AÑO GRAVABLE 2"))
    fila = next(l for l in lineas if l.count(_VACIA) + l.count(_MARCA) == 7)
    mes = fila.split().index(_MARCA) + 1
    return anio, "%d-%02d" % (anio, mes)


def _valor_siguiente(lineas: list, etiqueta: str) -> str:
    return lineas[lineas.index(etiqueta) + 1]


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
    )
