"""
Envio del codigo de acceso por correo.

Modos soportados:
  - SMTP: envia via servidor SMTP (requiere host, usuario, clave)
  - RELAY: envia directo al servidor de destino (solo dominio propio)
  - CONSOLA: escribe el codigo en el log (para pruebas)

Variables de entorno:
  AUDITORIA_CORREO_MODO      SMTP | RELAY | CONSOLA
  AUDITORIA_SMTP_HOST        smtp.office365.com
  AUDITORIA_SMTP_PUERTO      587
  AUDITORIA_SMTP_USUARIO     buzon que autentica
  AUDITORIA_SMTP_CLAVE       su contrasena o contrasena de aplicacion
  AUDITORIA_CORREO_DE        remitente que ve la gente
  AUDITORIA_CORREO_NOMBRE    nombre del remitente
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

from . import auth

log = logging.getLogger("reteica.correo")

ASUNTO = "Su codigo de acceso · Motor ReteICA"


class CorreoNoConfigurado(RuntimeError):
    pass


def _cfg(nombre: str, defecto: str = "") -> str:
    return os.getenv(nombre, defecto).strip()


def modo() -> str:
    return (_cfg("AUDITORIA_CORREO_MODO", "CONSOLA") or "CONSOLA").upper()


def remitente() -> tuple[str, str]:
    de = _cfg("AUDITORIA_CORREO_DE") or _cfg("AUDITORIA_SMTP_USUARIO")
    return _cfg("AUDITORIA_CORREO_NOMBRE", "Motor ReteICA"), de


def configurado() -> tuple[bool, str | None]:
    if modo() == "CONSOLA":
        return True, None
    necesarias = ["AUDITORIA_SMTP_HOST"]
    if modo() != "RELAY":
        necesarias += ["AUDITORIA_SMTP_USUARIO", "AUDITORIA_SMTP_CLAVE"]
    faltan = [n for n in necesarias if not _cfg(n)]
    if faltan:
        return False, "Falta configurar " + ", ".join(faltan)
    if not remitente()[1]:
        return False, "Falta configurar AUDITORIA_CORREO_DE"
    return True, None


def _cuerpo(codigo: str, minutos: int) -> tuple[str, str]:
    texto = (
        f"Su codigo de acceso es {codigo}\n\n"
        f"Vence en {minutos} minutos y sirve una sola vez.\n\n"
        "Si no fue usted quien lo pidio, ignore este mensaje.\n"
    )
    html = f"""<!doctype html>
<html><body style="font-family:system-ui,sans-serif;background:#f6f7f9;margin:0;padding:32px">
  <div style="max-width:440px;margin:0 auto;background:#fff;border:1px solid #e4e6ea;
              border-radius:12px;padding:28px">
    <p style="margin:0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;
              color:#6b7280">Motor ReteICA</p>
    <p style="margin:18px 0 6px;font-size:14px;color:#374151">Su codigo de acceso</p>
    <p style="margin:0;font-family:monospace;font-size:34px;letter-spacing:.22em;
              font-weight:600;color:#111827">{codigo}</p>
    <p style="margin:18px 0 0;font-size:13px;color:#6b7280">
      Vence en {minutos} minutos y sirve una sola vez.</p>
  </div>
</body></html>"""
    return texto, html


def enviar_codigo(correo: str, codigo: str, minutos: int) -> str:
    if modo() == "CONSOLA":
        log.warning("MODO CONSOLA -- codigo para %s: %s", correo, codigo)
        return "CONSOLA"

    sirve, falta = configurado()
    if not sirve:
        raise CorreoNoConfigurado(falta or "Envio de correo sin configurar")

    nombre_de, direccion_de = remitente()
    texto, html = _cuerpo(codigo, minutos)

    msg = EmailMessage()
    msg["Subject"] = ASUNTO
    msg["From"] = f"{nombre_de} <{direccion_de}>"
    msg["To"] = correo
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")

    relay = modo() == "RELAY"
    host = _cfg("AUDITORIA_SMTP_HOST")
    puerto = int(_cfg("AUDITORIA_SMTP_PUERTO", "25" if relay else "587") or 25)
    with smtplib.SMTP(host, puerto, timeout=30) as s:
        s.ehlo()
        if relay:
            if s.has_extn("starttls"):
                s.starttls()
                s.ehlo()
        else:
            s.starttls()
            s.ehlo()
            s.login(_cfg("AUDITORIA_SMTP_USUARIO"), _cfg("AUDITORIA_SMTP_CLAVE"))
        s.send_message(msg)
    return f"{'RELAY' if relay else 'SMTP'} {host}:{puerto}"
