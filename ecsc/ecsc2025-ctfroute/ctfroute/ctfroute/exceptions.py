class CtfRouteException(Exception):
    def __init__(self, msg, *args):
        self.msg = msg
        super().__init__(*args)

    def __str__(self):
        return f"{self.__class__.__name__} {self.msg}"


class BadConfiguration(CtfRouteException): ...
