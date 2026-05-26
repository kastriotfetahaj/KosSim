#!/usr/bin/env python3
from flask import Flask, Response, abort, jsonify, render_template, redirect, request, send_file, session
from werkzeug.exceptions import HTTPException

import argon2
import atexit
import dataclasses
import datetime
import ipaddress
import os
import pathlib
import psycopg
import psycopg_pool
import random
import secrets
import shlex
import string
import time
import tempfile
import urllib.parse

from config import load_config
from manager import create_manager
from manager import models as manager_models

# Some sane defaults
hasher = argon2.PasswordHasher(time_cost=1, memory_cost=4096, parallelism=1)
random = random.SystemRandom()

placeholder_hash = hasher.hash(secrets.token_bytes(64), salt = b'placeholder hash')


# Set up the app
app = Flask(__name__, static_url_path='/static', static_folder='static/', template_folder='html/')
app.secret_key = secrets.token_urlsafe(32)
app.add_template_filter(shlex.quote, 'quote')


# Load the configuration
config_path = pathlib.Path(os.getenv('FRONTEND_CONFIG_FILE', '/etc/firewall/frontend.toml'))
config = load_config(config_path)


# Derive the database connection string once
connection_string = config.database
placeholder = '__PASSWORD__' in connection_string
password = os.getenv('DB_PASSWORD')
password_file = os.getenv('DB_PASSWORD_FILE')
if password_file and password:
    raise RuntimeError('Database password specified both inline and via secrets file')
elif password_file:
    password = pathlib.Path(password_file).read_text().strip()

if password and placeholder:
    connection_string = connection_string.replace('__PASSWORD__', password)
elif password:
    raise RuntimeError('Database password specified separately, but no placeholder found')
elif placeholder:
    raise RuntimeError('Database password is missing (placeholder "__PASSWORD__" found)')

# Work around psycopg #1535
os.environ['PGSSLCERT'] = tempfile.gettempdir() + f'/.frontend.{os.getpid()}.postgresql.cert'


# Open database connection pool
pool = None

def configure_connection(connection: psycopg.Connection):
    connection.autocommit = False

def get_db() -> psycopg.Connection:
    global pool
    if pool is None:
        pool = psycopg_pool.ConnectionPool(
            connection_string,
            check=psycopg_pool.ConnectionPool.check_connection,
            configure=configure_connection,
            # We only need a single DB connection per worker, since those are synchronous.
            min_size=1,
            max_size=1,
            open=True
        )
        atexit.register(pool.close)
    return pool.connection()


# Register the SNMP manager
app.register_blueprint(create_manager(config.manager))


# Log entries
@dataclasses.dataclass
class LogEntry:
    timestamp: datetime.datetime
    packet: bytes


# Session management
def session_is_logged_in() -> bool:
    '''Checks whether the current session is logged in and still valid.'''
    if 'user' not in session:
        return False
    expiry = session.get('expiry', 0)
    if expiry < time.time():
        session.clear()
        return False
    return True


# Routes
@app.route('/')
def main_view():
    '''Main interface of the firewall.'''
    if not session_is_logged_in():
        return render_template('auth.html', error=None)
    else:
        host = urllib.parse.urlparse(request.base_url).hostname or '<this server>'
        ipv4 = session.get('ipv4', '192.0.2.42')
        ipv6 = session.get('ipv6', '2001:db8::ec5c:2a')
        return render_template('main.html', user=session['user'], endpoint='/', host=host, ipv4=ipv4, ipv6=ipv6)


@app.route('/traffic/')
def traffic_view():
    '''Shows a view of dropped traffic.'''
    if not session_is_logged_in():
        return redirect('/', 302)
    else:
        entries = []
        with get_db() as db:
            with db.cursor() as cursor:
                try:
                    cursor.execute('SELECT time, packet FROM fetch_user_log(%s)', (session['user'],))
                    for row in cursor.fetchall():
                        time, packet = tuple(row)
                        if not isinstance(time, datetime.datetime) or not isinstance(packet, bytes):
                            abort(500, 'Invalid log entry in database')
                        entries.append(LogEntry(time, packet))
                except psycopg.errors.UndefinedTable:
                    pass
        return render_template('traffic.html', user=session['user'], entries=entries, endpoint='/traffic/')


@app.route('/register', methods=['POST'])
def register():
    '''Handles new user registrations.'''
    if session_is_logged_in():
        return redirect('/', 302)

    username = request.form.get('username', None)
    password = request.form.get('password', None)
    if not username or not password:
        abort(400, 'Missing credentials')
    if len(username) > 64 or len(password) > 128:
        abort(400, 'Credentials too long')
    if not all(char in string.ascii_letters + string.digits + '-_' for char in username):
        abort(400, 'Invalid username')

    hashed = hasher.hash(password.encode('utf-8'))

    with get_db() as db:
        with db.cursor() as cursor:
            # Create the actual user.
            try:
                cursor.execute('INSERT INTO users (name, password) VALUES (%s, %s) RETURNING id, identifier, created', (
                    username,
                    hashed
                ))
            except psycopg.errors.UniqueViolation:
                db.rollback()
                abort(400, 'User already exists')
            row = cursor.fetchone()

            if row is None:
                db.rollback()
                abort(500, 'Database did not return inserted user')
            else:
                # NB: This means the user will survive even if we cannot give it an IP or a log.
                # Unfortunately, there is little we can do about this if we need to rollback later,
                # but we want to make the identifier visible (and unlock the lock) ASAP.
                db.commit()

            user_id, identifier, created = row
            if not isinstance(user_id, int) or not isinstance(identifier, int) or not isinstance(created, datetime.datetime):
                db.rollback()
                abort(500, 'Database returned invalid user information')

            # Create the user log
            try:
                cursor.execute('SELECT create_user_log(%s)', (username,))
            except psycopg.errors.Error:
                db.rollback()
                abort(500, 'Failed to create user log')

            # Allocate IP addresses for this user.
            cursor.execute('SELECT ip_allocate_for(%s, %s, %s), ip_allocate_for(%s, %s, %s)', (
                user_id, *config.ipv4,
                user_id, *config.ipv6,
            ))
            row = cursor.fetchone()
            if row is None:
                db.rollback()
                abort(500, 'Database did not return allocated IP addresses')

            # Done with that part. If we're still missing IP addresses, we need to retry with locking.
            # This needs us to open a new transaction to avoid deadlocks.
            db.commit()

            ipv4, ipv6 = row
            if ipv4 is None or ipv6 is None:
                cursor.execute('LOCK TABLE ip_ranges IN ACCESS EXCLUSIVE MODE')
                if ipv4 is None:
                    cursor.execute('SELECT ip_allocate_for(%s, %s, %s)', (user_id, *config.ipv4))
                    row = cursor.fetchone()
                    if row is None:
                        db.rollback()
                        abort(500, 'Database did not return allocated IP address')
                    ipv4, *_ = row
                    if ipv4 is None:
                        db.rollback()
                        abort(500, 'Database failed to allocate IPv4 address for user')
                if ipv6 is None:
                    cursor.execute('SELECT ip_allocate_for(%s, %s, %s)', (user_id, *config.ipv6))
                    row = cursor.fetchone()
                    if row is None:
                        db.rollback()
                        abort(500, 'Database did not return allocated IP address')
                    ipv6, *_ = row
                    if ipv6 is None:
                        db.rollback()
                        abort(500, 'Database failed to allocate IPv6 address for user')
                db.commit()

    session['user'] = username
    session['identifier'] = identifier
    session['ipv4'] = str(ipv4)
    session['ipv6'] = str(ipv6)
    session['expiry'] = created.timestamp() + config.account_lifetime
    return redirect('/', 302)


def check_credentials(db: psycopg.Connection, username: str, password: str) -> bool:
    '''Checks credentials against the database.'''
    with db.cursor() as cursor:
        cursor.execute('SELECT password FROM users WHERE name = %s', (username,))
        row = cursor.fetchone()
        hashed = row[0] if row is not None else placeholder_hash

    try:
        hasher.verify(hashed, password)
        return hashed != placeholder_hash
    except argon2.exceptions.VerifyMismatchError:
        return False


@app.route('/login', methods=['POST'])
def login():
    '''Handles login requests.'''
    if session_is_logged_in():
        return redirect('/', 302)

    username = request.form.get('username', None)
    password = request.form.get('password', None)
    if not username or not password:
        abort(400, 'Missing credentials')
    if len(username) > 63 or len(password) > 127:
        abort(400, 'Credentials too long')

    with get_db() as db:
        if not check_credentials(db, username, password):
            abort(403, 'Incorrect username or password')

        with db.cursor() as cursor:
            cursor.execute('SELECT identifier, created FROM users WHERE name = %s', (username,))
            row = cursor.fetchone()
            if row is None:
                abort(500, 'Invalid response from database')
            identifier, created = row

    if not isinstance(identifier, int):
        abort(500, 'Database returned invalid user identifier')
    if not isinstance(created, datetime.datetime):
        abort(500, 'Database returned invalid creation timestamp')

    session['user'] = username
    session['identifier'] = identifier
    session['expiry'] = created.timestamp() + config.account_lifetime
    return redirect('/', 302)


@app.route('/api/login', methods=['POST'])
def api_login():
    '''Handles login requests.'''
    if session_is_logged_in():
        return redirect('/', 302)

    json = request.json
    if json is None:
        abort(400, 'Bad authentication request')

    username = json.get('username', None)
    password = json.get('password', None)
    if not username or not password:
        abort(400, 'Missing credentials')
    if len(username) > 63 or len(password) > 127:
        abort(400, 'Credentials too long')

    with get_db() as db:
        if not check_credentials(db, username, password):
            abort(403, 'Incorrect username or password')

        with db.cursor() as cursor:
            cursor.execute('SELECT i.ip FROM ips i INNER JOIN users u ON u.id = i.user_id WHERE u.name = %s', (username,))
            ips = [str(row[0]) for row in cursor]

    return jsonify({ 'ips': ips }), 200


@app.route('/logout', methods=['POST'])
def logout():
    '''Handles logout requests by dropping the session.'''
    session.clear()
    return redirect('/', 302)


@app.route('/static/ca.crt')
def ca_certificate():
    '''Returns the internal CA certificate'''
    return send_file('/state/firewall/tls/ca.crt')


@app.errorhandler(Exception)
def handle_error(error: Exception):
    if (
        isinstance(error, HTTPException)
        or isinstance(error, manager_models.ValidationError)
        or isinstance(error, manager_models.PydanticValidationError)
    ):
        code = error.code or 500
        name = error.name
        message = error.args[0] if error.args else error.description
    else:
        code = 500
        name = 'Internal Server Error'
        message = 'An internal error has occurred, please contact IT support.'

    if request.path.startswith('/api/') or request.path.startswith('/manager/api/'):
        response = jsonify({ 'code': code, 'name': name, 'description': message })
    elif 'user' in session:
        response = render_template('error.html', endpoint=request.path, name=name, message=message)
    else:
        response = render_template('auth.html', error=message)
    return response, code


if __name__ == '__main__':
    app.run()
