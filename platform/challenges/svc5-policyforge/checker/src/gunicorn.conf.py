import multiprocessing
import os

worker_class = "uvicorn.workers.UvicornWorker"
workers = multiprocessing.cpu_count() if "LOCAL" not in os.environ else 4
bind = "0.0.0.0:8500"
timeout = 90
keepalive = 3600
preload_app = True
