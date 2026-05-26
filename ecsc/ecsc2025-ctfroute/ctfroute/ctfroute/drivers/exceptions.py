__all__ = ["BadState", "InsufficientState", "SoftFail"]
from ctfroute.exceptions import CtfRouteException


class BadState(CtfRouteException):
    """
    State passed to a driver doesn't make sense.

    Raise this from a driver to indicate conflicting / bad state. If the passed state
    lacks data raise InsufficientState instead.
    """


class InsufficientState(CtfRouteException):
    """
    State passed to a driver lacks crucial information.

    Raised by drivers when state that was passed lacks information necessary to perform
    the requested action. If the state is bad / conflicting rather than incomplete,
    raise BadState instead.
    """


class SoftFail(CtfRouteException):
    """
    Some external issue is preventing a driver from performing a request.

    This should be used for errors that are likely temporary, e.g. DNS resolution
    errors.
    """
