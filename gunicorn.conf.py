import multiprocessing

bind = "127.0.0.1:8001"
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)
worker_class = "uvicorn.workers.UvicornWorker"

# Una revision con Revision Inteligente hace DOS llamadas al modelo, y el
# modelo corre en CPU. Con timeout=120 gunicorn mataba al worker a los dos
# minutos y nginx lo traducia a un 502 sin explicacion. Esto no es el tiempo
# esperado sino la red de seguridad: debe quedar por encima de IA_TIMEOUT (600
# por llamada) o el worker muere aunque el modelo siga trabajando bien.
timeout = 1500
graceful_timeout = 60
keepalive = 5
accesslog = "/var/log/reteica/access.log"
errorlog = "/var/log/reteica/error.log"
loglevel = "info"
