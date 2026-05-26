from functools import cache
from logging import Filter, LogRecord
from typing import Callable

from django.http import HttpRequest


class AddRequestContext(Filter):
    @cache
    def _get_session_check(self) -> Callable[[HttpRequest], bool]:
        # Needs django to be set up
        from loginas.utils import is_impersonated_session

        return is_impersonated_session

    def safely_try_set_impersonate(self, record: LogRecord):
        try:
            setattr(
                record, "user.impersonated", self._get_session_check()(record.request)
            )  # type: ignore
        except Exception:
            ...

    def filter(self, record: LogRecord):
        if hasattr(record, "request"):
            self.safely_try_set_impersonate(record)
            if hasattr(record.request, "user"):
                setattr(
                    record, "user.name", getattr(record.request.user, "username", None)
                )
                setattr(record, "user.id", getattr(record.request.user, "id", None))
        return True
