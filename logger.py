import logging
import structlog
from structlog.contextvars import merge_contextvars

_SENSITIVE = frozenset({
    "password", "senha", "token", "secret", "api_key",
    "authorization", "cookie", "spool_api_key", "password_hash",
    "current_password", "new_password", "secret_key",
})


def _mask_sensitive(_, __, event_dict: dict) -> dict:
    for key in list(event_dict):
        if key.lower() in _SENSITIVE:
            event_dict[key] = "***"
    return event_dict


def configure_logging(app=None) -> None:
    # app é opcional: processos fora do Flask (ex.: deploy/backup-cron.py) chamam
    # sem app e ganham os mesmos logs JSON com mascaramento de segredos.
    level = logging.DEBUG if (app is not None and app.debug) else logging.INFO

    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=[logging.StreamHandler()],
        force=True,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            _mask_sensitive,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "spool"):
    return structlog.get_logger(name)
