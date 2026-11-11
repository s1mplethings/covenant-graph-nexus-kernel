"""Interruptible reads for CGKN's pinned synchronous httpcore transport.

The pool and TLS socket stay owned by httpcore. A request-local check is sampled
while waiting for bytes, including partial TLS records and reused connections.
No timeout retry occurs and no broken buffered reader is resumed.
"""
import contextvars
import select
import socket
import ssl
import time
import httpcore

READ_CHECK = contextvars.ContextVar('cgkn_stream_read_check', default=None)


class ProgressStream:
    def __init__(self, stream):self.stream=stream
    def read(self, max_bytes, timeout=None):
        check=READ_CHECK.get()
        sock=self.stream.get_extra_info('socket')
        if check is None or sock is None:return self.stream.read(max_bytes,timeout)
        read_started=time.monotonic()
        previous=sock.gettimeout()
        sock.setblocking(False)
        try:
            while True:
                check()
                if timeout is not None and time.monotonic()-read_started>=timeout:
                    raise httpcore.ReadTimeout()
                try:return sock.recv(max_bytes)
                except (ssl.SSLWantReadError,BlockingIOError):
                    select.select([sock],[],[],.025)
                except ssl.SSLWantWriteError:
                    select.select([],[sock],[],.025)
                except ssl.SSLZeroReturnError:return b''
                except socket.timeout:raise httpcore.ReadTimeout() from None
                except OSError as exc:
                    check()
                    raise httpcore.ReadError(type(exc).__name__) from None
        finally:
            try:sock.settimeout(previous)
            except OSError:pass
    def write(self,buffer,timeout=None):return self.stream.write(buffer,timeout)
    def close(self):return self.stream.close()
    def start_tls(self,ssl_context,server_hostname=None,timeout=None):
        return ProgressStream(self.stream.start_tls(ssl_context,server_hostname,timeout))
    def get_extra_info(self,info):return self.stream.get_extra_info(info)


class ProgressBackend:
    def __init__(self,backend):self.backend=backend
    def connect_tcp(self,*args,**kwargs):return ProgressStream(self.backend.connect_tcp(*args,**kwargs))
    def connect_unix_socket(self,*args,**kwargs):return ProgressStream(self.backend.connect_unix_socket(*args,**kwargs))
    def sleep(self,seconds):return self.backend.sleep(seconds)


def install(transport):
    # PhysicalDirectTransport deliberately exposes its pinned inner transport.
    inner=getattr(transport,'transport',transport)
    pool=getattr(inner,'_pool',None)
    if pool is not None and not isinstance(pool._network_backend,ProgressBackend):
        pool._network_backend=ProgressBackend(pool._network_backend)
