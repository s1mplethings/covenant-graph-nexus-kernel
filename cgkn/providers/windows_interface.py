"""Read-only GUID-based adapter selection; never changes Windows networking."""
from __future__ import annotations
import ipaddress
import json
import os
import subprocess
import uuid


def validate_snapshot(guid,snapshot):
    wanted=str(uuid.UUID(guid.strip('{}')))
    if str(uuid.UUID(str(snapshot['guid']).strip('{}')))!=wanted:raise ValueError('DIRECT_ADAPTER_IDENTITY_MISMATCH')
    if snapshot.get('status')!='Up' or snapshot.get('hardware') is not True:raise ValueError('DIRECT_PHYSICAL_ADAPTER_UNAVAILABLE')
    addresses=[str(ipaddress.IPv4Address(v)) for v in snapshot.get('addresses',[])
               if not ipaddress.IPv4Address(v).is_loopback and not ipaddress.IPv4Address(v).is_link_local]
    if len(addresses)!=1 or int(snapshot['index'])<=0:raise ValueError('DIRECT_ADAPTER_ADDRESS_AMBIGUOUS')
    return dict(guid=wanted,index=int(snapshot['index']),source=addresses[0],name=str(snapshot.get('name','')))


def resolve_interface(guid):
    if os.name!='nt':raise ValueError('WINDOWS_INTERFACE_BINDING_REQUIRED')
    wanted=str(uuid.UUID(guid.strip('{}')))
    script="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $a=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetAdapter -Filter \"InterfaceGuid = '{"+wanted+"}'\"); if($a.Count -ne 1){throw 'adapter identity missing or ambiguous'}; $a=$a[0]; $ips=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetIPAddress -Filter \"InterfaceIndex = $($a.InterfaceIndex) AND AddressFamily = 2 AND AddressState = 4\" | ForEach-Object {$_.IPAddress}); $status=if($a.InterfaceOperationalStatus -eq 1){'Up'}else{'Unavailable'}; [pscustomobject]@{guid=$a.InterfaceGuid.ToString();index=[int]$a.InterfaceIndex;name=$a.Name;status=$status;hardware=[bool]$a.HardwareInterface;addresses=$ips} | ConvertTo-Json -Compress"
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=8)
        if result.returncode:raise ValueError('DIRECT_ADAPTER_QUERY_FAILED')
        return validate_snapshot(wanted,json.loads(result.stdout))
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError,KeyError,TypeError):
        raise ValueError('DIRECT_ADAPTER_QUERY_FAILED') from None
