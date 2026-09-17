#!/bin/bash
# Script de despliegue para Motor de Revision de ReteICA
# Ejecutar como root en el servidor

set -e

APP_NAME="reteica"
APP_DIR="/opt/reteica"
APP_USER="reteica"
LOG_DIR="/var/log/reteica"

echo "=== Despliegue del Motor de Revision de ReteICA ==="

# 1. Crear usuario del sistema
if ! id "$APP_USER" &>/dev/null; then
    echo "Creando usuario $APP_USER..."
    sudo useradd -r -s /bin/false $APP_USER
fi

# 2. Crear directorios
echo "Creando directorios..."
sudo mkdir -p $APP_DIR
sudo mkdir -p $LOG_DIR
# Los papeles de trabajo. NO en /tmp: el sistema lo limpia solo y lo borra al
# reiniciar, y el historial quedaria apuntando a archivos que ya no estan.
sudo mkdir -p /var/lib/reteica/papeles

# 3. Copiar archivos del proyecto
echo "Copiando archivos del proyecto..."
sudo cp -r . $APP_DIR/

# 4. Crear entorno virtual e instalar dependencias
echo "Configurando entorno virtual..."
sudo python3 -m venv $APP_DIR/venv
sudo $APP_DIR/venv/bin/pip install --upgrade pip
sudo $APP_DIR/venv/bin/pip install -r $APP_DIR/requirements.txt

# 5. Configurar permisos
echo "Configurando permisos..."
sudo chown -R $APP_USER:$APP_USER $APP_DIR
sudo chown -R $APP_USER:$APP_USER $LOG_DIR
sudo chown -R $APP_USER:$APP_USER /var/lib/reteica

# 6. Archivo de credenciales (fuera del repo: nunca se versiona)
if [ ! -f /etc/reteica.env ]; then
    echo "Creando plantilla /etc/reteica.env..."
    sudo tee /etc/reteica.env >/dev/null <<'EOF'
# Credenciales del Motor de ReteICA. NO versionar.
# Debe apuntar a la misma base de analitica-puc.
AUDITORIA_DSN=postgresql://USUARIO:CLAVE@localhost:5432/auditoria_puc

# Envio del codigo de acceso. Sin esto el codigo solo se escribe en el log.
AUDITORIA_CORREO_MODO=CONSOLA

# Revision Inteligente con el modelo local de Ollama. Con esto definido no se
# pide ninguna llave de API: el motor deduce que el proveedor es local.
OLLAMA_MODELO=qwen2.5:3b-instruct
OLLAMA_URL=http://127.0.0.1:11434
IA_TIMEOUT=600
#AUDITORIA_SMTP_HOST=smtp.office365.com
#AUDITORIA_SMTP_PUERTO=587
#AUDITORIA_SMTP_USUARIO=
#AUDITORIA_SMTP_CLAVE=
#AUDITORIA_CORREO_DE=
EOF
    sudo chown root:root /etc/reteica.env
    sudo chmod 600 /etc/reteica.env
    echo "  !! Edite /etc/reteica.env con las credenciales reales antes de usar."
fi

# 7. Esquema de autenticacion (idempotente: CREATE ... IF NOT EXISTS)
echo "Aplicando schema_auth.sql..."
# shellcheck disable=SC1091
set +e
. /etc/reteica.env 2>/dev/null
if [ -n "$AUDITORIA_DSN" ] && command -v psql >/dev/null 2>&1; then
    sudo -u postgres psql "$AUDITORIA_DSN" -f $APP_DIR/schema_auth.sql \
        && sudo -u postgres psql "$AUDITORIA_DSN" -f $APP_DIR/schema_revisiones.sql \
        && echo "  schemas aplicados." \
        || echo "  !! No se pudo aplicar el schema. Revise AUDITORIA_DSN en /etc/reteica.env"
else
    echo "  !! Omitido (falta psql o AUDITORIA_DSN). Aplicar a mano:"
    echo "     psql \"\$AUDITORIA_DSN\" -f $APP_DIR/schema_auth.sql"
    echo "     psql \"\$AUDITORIA_DSN\" -f $APP_DIR/schema_revisiones.sql"
fi
set -e

# 8. Instalar servicio systemd
echo "Instalando servicio systemd..."
sudo cp $APP_DIR/reteica.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $APP_NAME

# 9. Configurar Nginx
echo "Configurando Nginx..."
sudo cp $APP_DIR/reteica_nginx.conf /etc/nginx/sites-available/$APP_NAME
sudo ln -sf /etc/nginx/sites-available/$APP_NAME /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 10. Iniciar servicio
echo "Iniciando servicio..."
sudo systemctl start $APP_NAME

echo ""
echo "=== Despliegue completado ==="
echo "La aplicacion esta corriendo en http://tu_dominio.com"
echo ""
echo "Comandos utiles:"
echo "  sudo systemctl status $APP_NAME    # Ver estado"
echo "  sudo systemctl restart $APP_NAME   # Reiniciar"
echo "  sudo journalctl -u $APP_NAME -f    # Ver logs en tiempo real"
