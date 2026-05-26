PGSQL_PROTO_MAJOR = 3
PGSQL_PROTO_MINOR = 0

def pgsql_prefix_length(message: bytes) -> bytes:
    return (len(message) + 4).to_bytes(4) + message

def pgsql_startup(user: str, database: str | None = None, options: str | None = None, **kwargs) -> bytes:
    protocol = PGSQL_PROTO_MAJOR.to_bytes(2) + PGSQL_PROTO_MINOR.to_bytes(2)

    params = {'user': user}
    if database is not None:
        params['database'] = database
    if options is not None:
        params['options'] = options
    params.update(kwargs)

    message = protocol
    for key, value in params.items():
        message += key.encode() + b'\0' + value.encode() + b'\0'
    message += b'\0'
    return pgsql_prefix_length(message)

def pgsql_password(password: str) -> bytes:
    return b'p' + pgsql_prefix_length(password.encode() + b'\0')

def pgsql_query(query: str) -> bytes:
    return b'Q' + pgsql_prefix_length(query.encode() + b'\0')

def pgsql_terminate() -> bytes:
    return b'X' + (4).to_bytes(4)

def pgsql_oneshot_query(query: str, *, user: str, password: str | None, database: str | None = None) -> bytes:
    return b''.join([
        pgsql_startup(user, database),
        pgsql_password(password) if password is not None else b'',
        pgsql_query(query),
        pgsql_terminate(),
    ])

def pgsql_quote_ident(ident: str) -> str:
    # Unlike PostgreSQL's quote_ident, we quote things always since we don't have a full list of SQL keywords.
    return '"' + ident.replace('"', '""') + '"'
