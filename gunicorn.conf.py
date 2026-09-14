import multiprocessing

bind = "127.0.0.1:8000"
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
accesslog = "/var/log/reteica/access.log"
errorlog = "/var/log/reteica/error.log"
loglevel = "info"
