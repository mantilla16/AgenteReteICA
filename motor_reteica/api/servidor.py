"""API del motor de revision de ReteICA.

El auditor sube los archivos del cliente y recibe el papel de trabajo. Esta
capa NO reimplementa el motor: llama a las MISMAS funciones que la CLI
(motor_reteica.pipeline.revisar, motor_reteica.papel_excel.generar_papel) y
traduce el resultado a JSON. Nunca muestra una traza de Python al frontend.

El unico trabajo propio de este modulo es RESOLVER EL MANIFIESTO por el
auditor: detecta que rol tiene cada archivo subido -- por ESTRUCTURA, nunca
por nombre de archivo ni por adivinanza -- y escribe manifiesto.json. Es el
"asistente interactivo" que el backlog del proyecto (1.1, D2) preveia desde
el principio: "puede venir DESPUES, encima, cuya unica funcion sea escribir
el manifiesto". La disciplina de fondo no cambia: un archivo cuyo rol no se
puede determinar por su estructura queda SIN CLASIFICAR y se lo dice al
auditor, nunca se le asigna un rol a adivinar.

Levantar en desarrollo:  uvicorn motor_reteica.api.servidor:app --reload
"""

import json
import shutil
import tempfile
import threading
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from ..atestacion import AtestacionInvalida
from ..identidad import IdentidadIncompatible
from ..ia.cliente import ClienteIA
from ..ingesta._io import leer_filas
from ..ingesta.borrador_pdf import leer_borrador
from ..ingesta.formato_historico import normalizar_periodo
from ..manifiesto import NOMBRE_ARCHIVO, ManifiestoIncompleto
from ..papel_excel import generar_papel
from ..parametros.columnas import ColumnaNoIdentificada, detectar_tipo_documento
from ..parametros.municipios.santa_marta import MUNICIPIO
from ..pipeline import revisar
from ..recursos import ruta_recurso
from ..semaforo import evaluar
from ..tipos import etiqueta_estado
from .. import __version__

app = FastAPI(title="Motor de Revision de ReteICA", version=__version__)

MUNICIPIOS = {"santa_marta": MUNICIPIO}

_RAIZ = Path(tempfile.gettempdir()) / "motor_reteica_web"
_RAIZ.mkdir(exist_ok=True)
_WEB = ruta_recurso("web")
_PAPELES: dict[str, Path] = {}


# --------------------------------------------------------------------------
# Deteccion de roles por ESTRUCTURA (nunca por nombre de archivo)
# --------------------------------------------------------------------------

def _es_borrador_pdf(ruta: Path) -> bool:
    try:
        leer_borrador(ruta)
        return True
    except Exception:
        return False


_MARCAS_DE_FACTURA = ("FACTURA", "FACTURA ELECTRONICA", "FACTURA DE VENTA")


def _es_factura_pdf(ruta: Path) -> bool:
    """Un PDF es factura si se identifica COMO factura.

    V5: antes se tomaba como factura TODO PDF que no fuera el borrador, y el
    extracto de saldos de SAP (S_ALR_...) entraba a la muestra documental.
    C11 lo reportaba como HALLAZGO -- "la factura no aparece en el auxiliar"
    -- y el papel le imputaba al cliente una factura sin contabilizar que no
    existe.

    Si el PDF no trae capa de texto no se puede determinar, y entonces NO se
    adivina: queda sin clasificar y el auditor decide. Es la misma regla que
    1.5 aplica a las fuentes contables -- se verifica que el documento sea
    del tipo que se dice.
    """
    try:
        import pdfplumber
        with pdfplumber.open(ruta) as pdf:
            texto = " ".join((p.extract_text() or "") for p in pdf.pages[:2])
    except Exception:
        return False
    sin_tildes = (texto.upper().replace("Ó", "O").replace("Í", "I")
                  .replace("É", "E").replace("Á", "A").replace("Ú", "U"))
    return any(marca in sin_tildes for marca in _MARCAS_DE_FACTURA)


def _rol_xlsx(ruta: Path):
    """auxiliar/balance/erp por firma de columnas; formato_historico por
    tener 2+ hojas cuyo nombre normaliza a un periodo AAAA-MM. None si no
    se reconoce ninguna de las dos formas."""
    try:
        filas = leer_filas(ruta)
    except Exception:
        return None
    tipo = detectar_tipo_documento(filas)
    if tipo:
        return tipo
    try:
        libro = openpyxl.load_workbook(ruta, read_only=True)
        periodos = [normalizar_periodo(n) for n in libro.sheetnames]
        libro.close()
    except Exception:
        return None
    return "formato_historico" if sum(1 for p in periodos if p) >= 2 else None


def _clasificar(rutas: list[Path]):
    """Devuelve (archivos_por_rol, facturas, sin_clasificar, conflictos)."""
    archivos = {"borrador": None, "auxiliar": None, "balance": None,
               "erp": None, "formato_historico": None}
    facturas, sin_clasificar, conflictos = [], [], []

    for ruta in rutas:
        extension = ruta.suffix.lower()
        if extension == ".pdf":
            if _es_borrador_pdf(ruta):
                if archivos["borrador"]:
                    conflictos.append(
                        "dos archivos parecen ser el borrador de la "
                        "declaracion: %r y %r" % (archivos["borrador"], ruta.name))
                else:
                    archivos["borrador"] = ruta.name
            elif _es_factura_pdf(ruta):
                facturas.append(ruta.name)
            else:
                # No es el borrador y tampoco se identifica como factura:
                # no se adivina. V5.
                sin_clasificar.append(ruta.name)
        elif extension in (".xlsx", ".xls"):
            rol = _rol_xlsx(ruta)
            if rol is None:
                sin_clasificar.append(ruta.name)
            elif archivos[rol]:
                conflictos.append(
                    "dos archivos parecen ser %s: %r y %r"
                    % (rol, archivos[rol], ruta.name))
            else:
                archivos[rol] = ruta.name
        else:
            sin_clasificar.append(ruta.name)

    return archivos, facturas, sin_clasificar, conflictos


# --------------------------------------------------------------------------
# Traduccion del resultado a JSON
# --------------------------------------------------------------------------

def _f(valor) -> float:
    return float(valor) if isinstance(valor, Decimal) else valor


def _resumen(ctx) -> dict:
    luz = evaluar(ctx.informe)
    return {
        "controles": [{
            "codigo": r.codigo, "nombre": r.nombre, "estado": etiqueta_estado(r),
            "detalle": r.detalle, "excepciones": len(r.excepciones),
            "aplica": r.aplica,
        } for r in ctx.resultados],
        "cifras": {
            "auxiliar": _f(ctx.total_auxiliar), "erp": _f(ctx.total_erp),
            "base_gravable": _f(ctx.reconstruccion.total_base),
            "impuesto_contable": _f(ctx.reconstruccion.total_impuesto_contable),
            "impuesto_declarable": _f(ctx.reconstruccion.total_impuesto_declarable),
            "declarado": _f(ctx.borrador.renglones.get("24", Decimal("0"))),
        },
        "excepciones": [{
            "severidad": e.severidad.value, "control": e.control,
            "descripcion": e.descripcion, "tipo_referencia": e.tipo_referencia,
            "renglon": e.renglon, "impacto": _f(e.impacto_pesos),
        } for e in ctx.informe.excepciones_ordenadas],
        "impacto_total": _f(ctx.informe.impacto_total),
        "puede_concluir_limpio": ctx.informe.puede_concluir_limpio,
        "conclusion": ctx.informe.conclusion,
        "semaforo": {"color": luz.color, "motivo": luz.motivo,
                    "simbolo": luz.simbolo},
        "insumos_obtenidos": sorted(ctx.insumos_obtenidos),
        "razon_social": ctx.borrador.razon_social,
    }


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def inicio() -> str:
    idx = _WEB / "index.html"
    return idx.read_text(encoding="utf-8") if idx.exists() else "<h1>Motor de Revision de ReteICA</h1>"


@app.post("/analizar")
async def analizar(
    archivos: list[UploadFile] = File(...),
    nit: str = Form(...), periodo: str = Form(...),
    municipio: str = Form("santa_marta"),
    declarado_por: str = Form(""), api_key: str = Form(""),
):
    if municipio not in MUNICIPIOS:
        raise HTTPException(400, "Municipio no soportado: %s" % municipio)

    corr = uuid.uuid4().hex[:12]
    carpeta = _RAIZ / corr
    carpeta.mkdir(exist_ok=True)

    rutas = []
    for subida in archivos:
        destino = carpeta / (subida.filename or "archivo_%d" % len(rutas))
        destino.write_bytes(await subida.read())
        rutas.append(destino)

    archivos_por_rol, facturas, sin_clasificar, conflictos = _clasificar(rutas)
    if conflictos:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise HTTPException(400, "; ".join(conflictos))

    manifiesto = {
        "nit": nit, "periodo": periodo, "municipio": MUNICIPIOS[municipio].nombre,
        "declarado_por": declarado_por or "sin declarar",
        "fecha": date.today().isoformat(),
        "archivos": {**archivos_por_rol, "facturas": facturas or None,
                    "pago_anterior": None},
    }
    (carpeta / NOMBRE_ARCHIVO).write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")

    cliente_ia = ClienteIA(api_key=api_key) if api_key else None

    try:
        ctx = revisar(carpeta, nit=nit, periodo=periodo,
                      municipio=MUNICIPIOS[municipio], cliente_ia=cliente_ia)
    except (ManifiestoIncompleto, IdentidadIncompatible, ColumnaNoIdentificada,
            AtestacionInvalida, FileNotFoundError) as error:
        raise HTTPException(400, str(error))

    salida = carpeta / ("PT_ReteICA_%s.xlsx" % corr)
    generar_papel(salida, ctx)
    _PAPELES[corr] = salida

    resumen = _resumen(ctx)
    resumen["sin_clasificar"] = sin_clasificar
    return {"corrida": corr, "descarga": "/descargar/%s" % corr, "resumen": resumen}


@app.get("/salir", response_class=HTMLResponse)
def salir() -> str:
    """Apaga la aplicacion. Es como el usuario cierra un .exe sin consola."""
    import os

    threading.Timer(0.4, lambda: os._exit(0)).start()
    return ("<html><body style='font-family:Segoe UI,sans-serif;text-align:center;"
            "margin-top:80px;color:#001871'><h2>Motor de Revision de ReteICA cerrado</h2>"
            "<p>Ya puede cerrar esta pestaña.</p></body></html>")


@app.get("/descargar/{corr}")
def descargar(corr: str):
    ruta = _PAPELES.get(corr)
    if not ruta or not ruta.exists():
        raise HTTPException(404, "Papel no encontrado o expirado.")
    return FileResponse(str(ruta), filename=ruta.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
