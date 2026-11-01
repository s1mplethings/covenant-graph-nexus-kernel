"""Windows per-socket physical egress; no OS routes, VPN or DNS settings changed.

Resolve through explicitly selected DNS servers on the same interface. Keep the
original HTTP Host and TLS SNI/hostname validation when dialing the returned IP.
"""
from __future__ import annotations

import ipaddress
import os
import secrets
import socket
import struct
import threading
import time
import ssl

import httpx
import httpcore
from httpcore._backends.sync import SyncStream

IP_UNICAST_IF = 31


class PreconnectInterfaceBackend(httpcore.SyncBackend):
    """httpcore 1.0.9 normally applies socket_options *after* connect.

    Physical isolation requires the option before the TCP SYN, not readback only.
    Reuse its tested stream/TLS implementation; override only socket creation.
    """
    def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            for option in socket_options or ():sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            sock.settimeout(timeout)
            if local_address:sock.bind((local_address,0))
            sock.connect((str(ipaddress.IPv4Address(host)),port))
            return SyncStream(sock)
        except socket.timeout:
            sock.close();raise httpcore.ConnectTimeout('DIRECT_CONNECT_TIMEOUT') from None
        except (OSError,ValueError):
            sock.close();raise httpcore.ConnectError('DIRECT_CONNECT_FAILED') from None


def interface_options(index):
    if os.name!='nt': raise ValueError('WINDOWS_INTERFACE_BINDING_REQUIRED')
    if not isinstance(index,int) or index<=0: raise ValueError('INVALID_INTERFACE_INDEX')
    return [(socket.IPPROTO_IP,IP_UNICAST_IF,socket.htonl(index))]


def parse_dns(packet,identity):
    if len(packet)<12: raise ValueError('DNS_SHORT_RESPONSE')
    ident,flags,questions,answers,_,_=struct.unpack('!6H',packet[:12])
    if ident!=identity or not flags&0x8000 or flags&0x020f:
        raise ValueError('DNS_INVALID_OR_TRUNCATED_RESPONSE')
    def skip(offset):
        for _ in range(128):
            size=packet[offset]
            if size&0xc0==0xc0:return offset+2
            if size>63:raise ValueError('DNS_LABEL_LIMIT')
            offset+=1
            if not size:return offset
            offset+=size
        raise ValueError('DNS_LABEL_LIMIT')
    offset=12
    for _ in range(questions):offset=skip(offset)+4
    ips=[];ttl=60
    for _ in range(answers):
        offset=skip(offset)
        kind,cls,lifetime,length=struct.unpack('!HHIH',packet[offset:offset+10]);offset+=10
        data=packet[offset:offset+length];offset+=length
        if kind==1 and cls==1 and len(data)==4:
            ip=ipaddress.IPv4Address(data)
            if not ip.is_global:raise ValueError('DNS_NON_PUBLIC_ANSWER_REFUSED')
            ips.append(str(ip));ttl=min(ttl,max(1,lifetime))
    if not ips:raise ValueError('DNS_NO_PUBLIC_IPV4')
    return ips,ttl


class PhysicalResolver:
    def __init__(self,servers,index,source):
        self.servers=tuple(str(ipaddress.IPv4Address(s)) for s in servers)
        if not self.servers:raise ValueError('EXPLICIT_DNS_SERVERS_REQUIRED')
        self.index,self.source=index,str(ipaddress.IPv4Address(source))
        self.cache={};self.lock=threading.Lock()

    def resolve(self,host,timeout=4):
        with self.lock:
            cached=self.cache.get(host)
            if cached and cached[0]>time.monotonic():return cached[1]
        labels=host.encode('idna').split(b'.')
        if any(not label or len(label)>63 for label in labels):raise ValueError('INVALID_DNS_HOST')
        identity=secrets.randbelow(65536)
        query=struct.pack('!6H',identity,0x100,1,0,0,0)+b''.join(bytes([len(v)])+v for v in labels)+b'\0'+struct.pack('!HH',1,1)
        end=time.monotonic()+timeout
        for server in self.servers:
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                    for level,opt,value in interface_options(self.index):sock.setsockopt(level,opt,value)
                    sock.bind((self.source,0));sock.settimeout(max(.001,(end-time.monotonic())/len(self.servers)))
                    sock.connect((server,53));sock.send(query);packet=sock.recv(8192)
                ips,ttl=parse_dns(packet,identity)
                with self.lock:self.cache[host]=(time.monotonic()+ttl,ips)
                return ips
            except (OSError,ValueError,IndexError,struct.error):pass
        raise httpx.ConnectError('DIRECT_DNS_FAILED')


class PhysicalDirectTransport(httpx.BaseTransport):
    def __init__(self,*,interface_index,local_address,dns_servers,allowed_hosts,log=None,interface_guid=None):
        self.index,self.source=interface_index,local_address
        self.interface_guid=interface_guid
        self.allowed=frozenset(allowed_hosts)
        if not self.allowed:raise ValueError('DIRECT_HOST_ALLOWLIST_REQUIRED')
        self.resolver=PhysicalResolver(dns_servers,interface_index,local_address)
        self.log=log or (lambda row:None)
        self.transport=httpx.HTTPTransport(proxy=None,trust_env=False,verify=True,retries=0,
            local_address=local_address,socket_options=interface_options(interface_index))
        # Narrow compatibility adapter, pinned in requirements-network.txt.
        if httpx.__version__!='0.28.1' or httpcore.__version__!='1.0.9':
            raise ValueError('DIRECT_TRANSPORT_COMPATIBILITY_CHECK_REQUIRED')
        self.transport._pool.close()
        self.transport._pool=httpcore.ConnectionPool(ssl_context=ssl.create_default_context(),retries=0,
            local_address=local_address,socket_options=interface_options(interface_index),network_backend=PreconnectInterfaceBackend())

    def handle_request(self,request):
        self.log(dict(phase='direct_interface_validation_started',interface_guid=self.interface_guid))
        if self.interface_guid:
            from .windows_interface import resolve_interface
            try:current=resolve_interface(self.interface_guid)
            except ValueError:raise httpx.ConnectError('DIRECT_ADAPTER_REVALIDATION_FAILED') from None
            if (current['index'],current['source'])!=(self.index,self.source):
                raise httpx.ConnectError('DIRECT_BINDING_CHANGED_RESTART_GATEWAY')
        self.log(dict(phase='direct_interface_validated',interface_index=self.index,local_address=self.source))
        host=request.url.host
        if host not in self.allowed or request.url.scheme!='https' or request.url.port not in (None,443):
            raise httpx.ConnectError('DIRECT_ENDPOINT_NOT_ALLOWED')
        timeout=request.extensions.get('timeout',{}).get('connect') or 4
        started=time.monotonic()
        self.log(dict(phase='direct_dns_started',endpoint_host=host,interface_index=self.index,
            local_address=self.source,dns_servers=list(self.resolver.servers)))
        ips=self.resolver.resolve(host,min(4,timeout))
        self.log(dict(phase='direct_dns',endpoint_host=host,addresses=ips,interface_index=self.index,local_address=self.source))
        extensions=dict(request.extensions)
        extensions['sni_hostname']=host
        limits=dict(extensions.get('timeout',{}));limits['connect']=max(.001,timeout-(time.monotonic()-started));extensions['timeout']=limits
        original_trace=extensions.get('trace')
        def trace(name,info):
            if name.endswith('connect_tcp.complete'):
                sock=info['return_value'].get_extra_info('socket')
                if sock:
                    actual=sock.getsockopt(socket.IPPROTO_IP,IP_UNICAST_IF)
                    if actual!=self.index or sock.getsockname()[0]!=self.source:
                        sock.close();raise httpx.ConnectError('DIRECT_INTERFACE_MISMATCH')
                    self.log(dict(phase='direct_socket',endpoint_host=host,interface_index=actual,
                        local_address=sock.getsockname()[0],local_port=sock.getsockname()[1],peer_ip=sock.getpeername()[0],peer_port=sock.getpeername()[1]))
            if original_trace:original_trace(name,info)
        extensions['trace']=trace
        headers=request.headers.copy();headers['Host']=request.headers.get('Host',host)
        translated=httpx.Request(request.method,request.url.copy_with(host=ips[0]),headers=headers,
            stream=request.stream,extensions=extensions)
        return self.transport.handle_request(translated)

    def close(self):self.transport.close()
