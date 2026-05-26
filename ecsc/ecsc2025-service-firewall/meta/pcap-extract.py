#!/usr/bin/env python3
import argparse
import dataclasses
import enum
import ipaddress
import pathlib
import pyshark
import scapy.utils
import scapy.layers.dns
import scapy.layers.inet
import scapy.layers.l2
import typing
import warnings

parser = argparse.ArgumentParser(description='Extracts VPN traffic from a packet capture')
parser.add_argument('input', help='Input pcap file', type=pathlib.Path)
parser.add_argument('output', help='Output pcap file', type=pathlib.Path)
parser.add_argument('-p', '--port', help='VPN port', type=int, default=9100)
args = parser.parse_args()

CLIENT_MAC = b'\xf6\x00\x00\x00\x00\x01'
SERVER_MAC = b'\xf6\x00\x00\xff\xff\xfe'
BROADCAST = b'\xff\xff\xff\xff\xff\xff'

class Direction(enum.Enum):
    INBOUND = 0
    OUTBOUND = 1

class State(enum.Enum):
    NEW = 0
    PARTIAL = 1
    ESTABLISHED = 2

@dataclasses.dataclass
class Stream:
    initiator: tuple[typing.Any, typing.Any]
    outbound: bytes
    inbound: bytes
    state: State = State.NEW
    seen: bool = False
    username: bytes = b''
    password: bytes = b''
    ipv4: ipaddress.IPv4Address = ipaddress.IPv4Address(0)
    ipv6: ipaddress.IPv6Address = ipaddress.IPv6Address(0)

    @staticmethod
    def _extract_one(raw: bytes) -> tuple[bytes | None, bytes]:
        if len(raw) < 2:
            return None, raw
        length = int.from_bytes(raw[:2])
        if len(raw) < 2 + length:
            return None, raw
        return raw[2:2 + length], raw[2 + length:]

    def process(self) -> typing.Generator[tuple[Direction, bytes], None, None]:
        if self.state == State.NEW:
            if not self.outbound:
                return
            name_length = self.outbound[0]
            if len(self.outbound) < 1 + name_length + 1:
                return
            pass_length = self.outbound[name_length + 1]
            if len(self.outbound) < 1 + name_length + 1 + pass_length:
                return
            self.username = self.outbound[1:1 + name_length]
            self.password = self.outbound[1 + name_length + 1:1 + name_length + 1 + pass_length]
            self.outbound = self.outbound[1 + name_length + 1 + pass_length:]
            self.state = State.PARTIAL
        if self.state == State.PARTIAL:
            if len(self.inbound) < 4 + 16:
                return
            self.ipv4 = ipaddress.IPv4Address(self.inbound[:4])
            self.ipv6 = ipaddress.IPv6Address(self.inbound[4:4 + 16])
            self.inbound = self.inbound[4 + 16:]
            self.state = State.ESTABLISHED
        if self.state == State.ESTABLISHED:
            while True:
                packet, self.outbound = Stream._extract_one(self.outbound)
                if packet is None:
                    break
                yield Direction.OUTBOUND, packet
            while True:
                packet, self.inbound = Stream._extract_one(self.inbound)
                if packet is None:
                    break
                yield Direction.INBOUND, packet

streams = {}
writer = scapy.utils.PcapWriter(str(args.output), linktype=1, sync=True)
try:
    for packet in pyshark.FileCapture(args.input, use_ek=True, include_raw=True):
        if 'TCP' not in packet or args.port not in (int(packet.tcp.srcport.value), int(packet.tcp.dstport.value)):
            continue
        if 'IP' in packet:
            saddr = (packet.ip.src.value, packet.tcp.srcport.value)
            daddr = (packet.ip.dst.value, packet.tcp.dstport.value)
        elif 'IPV6' in packet:
            saddr = (packet.ipv6.src.value, packet.tcp.srcport.value)
            daddr = (packet.ipv6.dst.value, packet.tcp.dstport.value)
        else:
            continue

        stream_index = packet.tcp.stream.value

        if hasattr(packet.tcp, 'payload'):
            payload = packet.tcp.payload.value
            stream = streams.get(stream_index)
            if stream is not None:
                if saddr == stream.initiator:
                    stream.outbound += payload
                else:
                    stream.inbound += payload
            else:
                stream = streams[stream_index] = Stream(saddr, payload, b'')
            for direction, encapsulated in stream.process():
                if not encapsulated:
                    warnings.warn('Dropping empty packet')
                    continue
                match encapsulated[0] >> 4:
                    case 4: ethertype = 0x0800
                    case 6: ethertype = 0x86dd
                    case _: ethertype = 0xffff # reserved (RFC 1701)
                match direction:
                    case Direction.OUTBOUND: ethernet = SERVER_MAC + CLIENT_MAC + ethertype.to_bytes(2)
                    case Direction.INBOUND: ethernet = CLIENT_MAC + SERVER_MAC + ethertype.to_bytes(2)
                    case _: raise ValueError('Invalid direction')
                if not stream.seen:
                    # Inject a fake broadcast packet to announce the client data.
                    stream.seen = True
                    lines = [
                        ('User', stream.username),
                        ('Password', stream.password),
                        ('IPv4', str(stream.ipv4)),
                        ('IPv6', str(stream.ipv6))
                    ]
                    meta = scapy.layers.l2.Ether(dst=BROADCAST, src=CLIENT_MAC, type=0x0800) / \
                           scapy.layers.inet.IP(dst='255.255.255.255', src='255.255.255.255') / \
                           scapy.layers.inet.UDP(sport=53, dport=53) / \
                           scapy.layers.dns.DNS(id=1337, qr=1, qdcount=1, ancount=4,
                               qd=scapy.layers.dns.DNSQR(qname='metadata.attacking-lab.com', qtype='TXT'),
                               an=[
                                   scapy.layers.dns.DNSRR(rrname=key, type='TXT', rdata=value)
                                   for key, value in lines
                               ]
                           )
                    writer.write(meta)
                writer.write(ethernet + encapsulated)

        if int(packet.tcp.flags_fin.value) and int(packet.tcp.flags_ack.value) or int(packet.tcp.flags_reset.value):
            if (stream := streams.pop(stream_index, None)) is not None:
                if stream.state == State.ESTABLISHED and (stream.outbound or stream.inbound):
                    warnings.warn(f'Incomplete packet remaining in stream: {stream}')
finally:
    writer.flush()
    writer.close()
