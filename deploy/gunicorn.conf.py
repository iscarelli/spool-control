bind = "0.0.0.0:8001"
workers = 2
timeout = 30
worker_tmp_dir = "/dev/shm"
preload_app = True

accesslog = "-"
errorlog = "-"
loglevel = "warning"

# Structured JSON access log — captured by journald, parseable by Loki/ELK.
access_log_format = (
    '{"type":"access","ip":"%(h)s","method":"%(m)s","path":"%(U)s",'
    '"qs":"%(q)s","status":%(s)s,"bytes":%(b)s,"duration_us":%(D)s}'
)
