import os
import multiprocessing

worker_class = "uvicorn.workers.UvicornWorker"
workers = multiprocessing.cpu_count() if "LOCAL" not in os.environ else 4
bind = "0.0.0.0:8500"
timeout = 90
keepalive = 3600
preload_app = True


def on_starting(srv):
    srv._id_list = set()


def nworkers_changed(srv, new, _old):
    srv._cur_worker_id = new


def _next(srv):
    if srv._id_list:
        return srv._id_list.pop()
    used = set([x._id for x in tuple(srv.WORKERS.values()) if x.alive])
    free = set(range(0, srv._cur_worker_id)) - used
    return free.pop()


def on_load(srv):
    srv._id_list = set(range(0, srv.cfg.workers))


def pre_fork(srv, worker):
    worker._id = _next(srv)


def post_fork(srv, worker):
    os.environ["WORKER_ID"] = str(worker._id)
