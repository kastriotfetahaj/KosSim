import fcntl
import socket

def fd_for(interface: str, ip: str = '::'):
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode())
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    flags = fcntl.fcntl(sock.fileno(), fcntl.F_GETFD)
    flags &= ~fcntl.FD_CLOEXEC
    fcntl.fcntl(sock.fileno(), fcntl.F_SETFD, flags)
    sock.bind((ip, 9101))
    sock.setblocking(False)
    return f'fd://{sock.detach()}'

chdir = '/var/www'
workers = 16
preload_app = True
bind = [fd_for('wan0'), fd_for('lo', '::1')]
user = 'www-data'
group = 'www-data'
umask = 0o027
initgroups = True
