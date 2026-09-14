# Guia de Despliegue - Motor de Revision de ReteICA

## Prerequisitos en el servidor

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python 3.10+, pip, venv, Nginx
sudo apt install -y python3 python3-pip python3-venv nginx git
```

## Paso 1: Subir el proyecto al servidor

Desde tu maquina local:
```bash
# Opcion A: SCP (recomendado)
scp -r "Agente_ReteICA/" usuario@tu_ip:/tmp/reteica

# Opcion B: Git (si el repo es privado)
# Sube el repo a GitHub primero y luego clona en el servidor
```

## Paso 2: Ejecutar el script de despliegue

```bash
# Conectar al servidor
ssh usuario@tu_ip

# Ir a la carpeta del proyecto
cd /tmp/reteica

# Dar permisos y ejecutar
chmod +x deploy.sh
sudo ./deploy.sh
```

## Paso 3: Configurar el dominio/IP

1. Editar la configuracion de Nginx:
```bash
sudo nano /etc/nginx/sites-available/reteica
```

2. Cambiar `tu_dominio.com` por tu dominio o IP publica

3. Probar y recargar Nginx:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Paso 4: SSL con Let's Encrypt (opcional pero recomendado)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu_dominio.com
```

## Comandos de administracion

| Comando | Descripcion |
|---------|-------------|
| `sudo systemctl status reteica` | Ver estado del servicio |
| `sudo systemctl restart reteica` | Reiniciar la aplicacion |
| `sudo systemctl stop reteica` | Detener la aplicacion |
| `sudo journalctl -u reteica -f` | Ver logs en tiempo real |
| `sudo tail -f /var/log/reteica/error.log` | Ver errores |

## Actualizaciones

Para actualizar el codigo en el servidor:
```bash
cd /opt/reteica
sudo systemctl stop reteica
sudo cp -r /tmp/reteica/* .
sudo chown -R reteica:reteica .
sudo systemctl start reteica
```

## Troubleshooting

**Problema: "502 Bad Gateway"**
- Verificar que el servicio esta corriendo: `sudo systemctl status reteica`
- Verificar logs: `sudo journalctl -u reteica -n 50`

**Problema: "Permission denied"**
- Verificar permisos: `ls -la /opt/reteica`
- Corregir: `sudo chown -R reteica:reteica /opt/reteica`

**Problema: No se generan los Excel**
- Verificar que openpyxl funciona: `sudo /opt/reteica/venv/bin/python -c "import openpyxl; print('OK')"`
