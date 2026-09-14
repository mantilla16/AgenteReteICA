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

# 6. Instalar servicio systemd
echo "Instalando servicio systemd..."
sudo cp $APP_DIR/reteica.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $APP_NAME

# 7. Configurar Nginx
echo "Configurando Nginx..."
sudo cp $APP_DIR/reteica_nginx.conf /etc/nginx/sites-available/$APP_NAME
sudo ln -sf /etc/nginx/sites-available/$APP_NAME /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 8. Iniciar servicio
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
