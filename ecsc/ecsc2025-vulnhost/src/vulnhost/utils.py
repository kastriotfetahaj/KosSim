import logging
import os

COMPONENT_NAME: str = "vulnhost"


class DefaultAttributesFilter(logging.Filter):
    def __init__(self, attributes: dict) -> None:
        super().__init__()
        self._default_attrs = attributes

    def filter(self, record: logging.LogRecord) -> bool:
        for k, v in self._default_attrs.items():
            if not hasattr(record, k):
                setattr(record, k, v)
        return True


def setup_logging() -> None:
    format: str = "%(asctime)s [%(levelname)s]  %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=format)
    logging.root.addFilter(DefaultAttributesFilter({"event.source": COMPONENT_NAME}))
    # add logfile
    fh = logging.FileHandler("vulnhost.log")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(format))
    logging.root.addHandler(fh)

    # ecs logging format
    ecs_logfile = os.environ.get("ECS_LOGFILE", None)
    if ecs_logfile:
        import ecs_logging

        fh = logging.FileHandler(ecs_logfile)
        fh.setLevel(logging.INFO)
        fh.setFormatter(ecs_logging.StdlibFormatter())
        logging.root.addHandler(fh)
