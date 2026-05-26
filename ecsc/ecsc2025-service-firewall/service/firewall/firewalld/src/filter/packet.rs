/// Utilities for packet slicing.

use std::{fmt::{Display, Formatter}, net::{IpAddr, Ipv4Addr, Ipv6Addr}};

/// IP protocol version in use.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum IpVersion {
    V4,
    V6,
}

/// Turns a slice into an IPv4 address. Panics if the slice is of the wrong size.
fn ipv4_from_slice(addr: &[u8]) -> Ipv4Addr {
    let mut array = [0u8; 4];
    array.copy_from_slice(addr);
    Ipv4Addr::from(array)
}

/// Turns a slice into an IPv6 address. Panics if the slice is of the wrong size.
fn ipv6_from_slice(addr: &[u8]) -> Ipv6Addr {
    let mut array = [0u8; 16];
    array.copy_from_slice(addr);
    Ipv6Addr::from(array)
}

/// Port information.
#[derive(Clone, Copy)]
pub(crate) struct Ports {
    pub source: u16,
    pub destination: u16,
}

/// An IP address and port pair.
#[derive(Clone, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub(crate) struct Peer {
    pub ip: IpAddr,
    pub port: u16,
}

impl Display for Peer {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}:{}", self.ip, self.port)
    }
}

impl Peer {
    /// Creates a new `Peer`.
    pub fn new(ip: IpAddr, port: u16) -> Self {
        Self { ip, port }
    }
}

/// A connection four-tuple has two peers. Since connections are bidirectional, we order the peers.
#[derive(Clone, Eq, Hash, PartialEq)]
pub(crate) struct Connection {
    pub peers: [Peer; 2],
}

impl Display for Connection {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} <=> {}", self.peers[0], self.peers[1])
    }
}

impl Connection {
    /// Build the four-tuple from two peers.
    pub fn new(p1: Peer, p2: Peer) -> Self {
        if p1 <= p2 {
            Self { peers: [p1, p2] }
        } else {
            Self { peers: [p2, p1] }
        }
    }

    /// Drops one of the ports from the connection to match pending connections.
    pub fn partial(&self) -> [Self; 2] {
        let mut partial = [self.clone(), self.clone()];
        partial[0].peers[0].port = 0;
        partial[1].peers[1].port = 0;
        partial
    }
}

/// A sliceable packet.
pub(crate) trait Packet {
    /// IP version.
    fn ip_version(&self) -> Option<IpVersion>;
    /// Source IP.
    fn source_ip(&self) -> Option<IpAddr>;
    /// Destination IP.
    fn destination_ip(&self) -> Option<IpAddr>;
    /// Layer 3 (IPv4/IPv6) header and data.
    fn layer_3(&self) -> &[u8];
    /// Layer 4 (TCP/UDP/...) header and data.
    fn layer_4(&self) -> Option<(i32, &[u8])>;
    /// Layer 4 ports.
    fn layer_4_ports(&self) -> Option<Ports>;
    /// Source IP and layer 4 port
    fn layer_4_source(&self) -> Option<Peer>;
    /// Destination IP and layer 4 port
    fn layer_4_destination(&self) -> Option<Peer>;
    /// Layer 5 (or higher) header and data.
    fn layer_5(&self) -> Option<&[u8]>;
    /// Bidirectional connection information.
    fn connection(&self) -> Option<Connection>;
}

impl<P: PacketUtil + ?Sized> Packet for P {
    fn ip_version(&self) -> Option<IpVersion> { self.ip_version() }
    fn source_ip(&self) -> Option<IpAddr> { self.source_ip(self.ip_version()) }
    fn destination_ip(&self) -> Option<IpAddr> { self.destination_ip(self.ip_version()) }
    fn layer_3(&self) -> &[u8] { self.layer_3() }
    fn layer_4(&self) -> Option<(i32, &[u8])> { self.layer_4(self.ip_version()) }
    fn layer_4_ports(&self) -> Option<Ports> { Self::layer_4_ports(self.layer_4(self.ip_version())) }
    fn layer_4_source(&self) -> Option<Peer> { Self::layer_4_source(self.source_ip(self.ip_version()), Self::layer_4_ports(self.layer_4(self.ip_version()))) }
    fn layer_4_destination(&self) -> Option<Peer> { Self::layer_4_destination(self.destination_ip(self.ip_version()), Self::layer_4_ports(self.layer_4(self.ip_version()))) }
    fn layer_5(&self) -> Option<&[u8]> { Self::layer_5(self.layer_4(self.ip_version())) }
    fn connection(&self) -> Option<Connection> {
        let ports = Self::layer_4_ports(self.layer_4(self.ip_version()));
        Self::connection(
            Self::layer_4_source(self.source_ip(self.ip_version()), ports),
            Self::layer_4_destination(self.destination_ip(self.ip_version()), ports),
        )
    }
}

/// Underlying packet implementations that allow caching.
pub(crate) trait PacketUtil {
    fn ip_version(&self) -> Option<IpVersion>;
    fn source_ip(&self, ip_version: Option<IpVersion>) -> Option<IpAddr>;
    fn destination_ip(&self, ip_version: Option<IpVersion>) -> Option<IpAddr>;
    fn layer_3(&self) -> &[u8];
    fn layer_4(&self, ip_version: Option<IpVersion>) -> Option<(i32, &[u8])>;
    fn layer_4_ports(layer_4: Option<(i32, &[u8])>) -> Option<Ports>;
    fn layer_4_source(source_ip: Option<IpAddr>, ports: Option<Ports>) -> Option<Peer>;
    fn layer_4_destination(destination_ip: Option<IpAddr>, ports: Option<Ports>) -> Option<Peer>;
    fn layer_5(layer_4: Option<(i32, &[u8])>) -> Option<&[u8]>;
    fn connection(source: Option<Peer>, destination: Option<Peer>) -> Option<Connection>;
}

impl PacketUtil for [u8] {
    fn ip_version(&self) -> Option<IpVersion> {
        match self.get(0)? >> 4 {
            4 => Some(IpVersion::V4),
            6 => Some(IpVersion::V6),
            _ => None,
        }
    }

    fn source_ip(&self, ip_version: Option<IpVersion>) -> Option<IpAddr> {
        ip_version.and_then(|v| {
            match v {
                IpVersion::V4 => Some(ipv4_from_slice(self.get(12..16)?).into()),
                IpVersion::V6 => Some(ipv6_from_slice(self.get(8..24)?).into()),
            }
        })
    }

    fn destination_ip(&self, ip_version: Option<IpVersion>) -> Option<IpAddr> {
        ip_version.and_then(|v| {
            match v {
                IpVersion::V4 => Some(ipv4_from_slice(self.get(16..20)?).into()),
                IpVersion::V6 => Some(ipv6_from_slice(self.get(24..40)?).into()),
            }
        })
    }

    fn layer_3(&self) -> &[u8] {
        &self
    }

    fn layer_4(&self, ip_version: Option<IpVersion>) -> Option<(i32, &[u8])> {
        ip_version.and_then(|v| {
            match v {
                IpVersion::V4 => {
                    let ihl = self[0] & 0xf;
                    let proto = *self.get(9)?;
                    Some((proto.into(), self.get((ihl * 4).into()..)?))
                },
                IpVersion::V6 => {
                    let mut next_header = (*self.get(6)?).into();
                    let mut remaining = self.get(40..)?;
                    loop {
                        match next_header {
                            // These IPv6 headers encode their own length
                            libc::IPPROTO_HOPOPTS | libc::IPPROTO_ROUTING |
                            libc::IPPROTO_DSTOPTS | libc::IPPROTO_MH => {
                                let size: usize = (*remaining.get(1)?).into();
                                next_header = remaining[0].into();
                                remaining = remaining.get((size + 1)..)?;
                            },
                            // Fixed-length headers
                            libc::IPPROTO_FRAGMENT => {
                                next_header = (*remaining.get(0)?).into();
                                remaining = remaining.get(8..)?;
                            },
                            // IPPROTO_NONE: no L4 contents.
                            libc::IPPROTO_NONE => return None,
                            // Other protocols: treat as L4.
                            proto => return Some((proto, remaining)),
                        }
                    }
                },
            }
        })
    }

    fn layer_4_ports(layer_4: Option<(i32, &[u8])>) -> Option<Ports> {
        layer_4.and_then(|(proto, data)| {
            match proto {
                libc::IPPROTO_TCP | libc::IPPROTO_UDP => {
                    let sport = u16::from_be_bytes(data.get(0..2)?.try_into().ok()?);
                    let dport = u16::from_be_bytes(data.get(2..4)?.try_into().ok()?);
                    Some(Ports { source: sport, destination: dport })
                },
                _ => None,
            }
        })
    }

    fn layer_4_source(source_ip: Option<IpAddr>, ports: Option<Ports>) -> Option<Peer> {
        Some(Peer::new(source_ip?, ports?.source))
    }

    fn layer_4_destination(destination_ip: Option<IpAddr>, ports: Option<Ports>) -> Option<Peer> {
        Some(Peer::new(destination_ip?, ports?.destination))
    }

    fn layer_5(layer_4: Option<(i32, &[u8])>) -> Option<&[u8]> {
        layer_4.and_then(|(proto, data)| {
            match proto {
                libc::IPPROTO_TCP => {
                    let offset: usize = (data.get(12)? >> 4).into();
                    data.get((offset * 4)..)
                },
                libc::IPPROTO_UDP => data.get(8..),
                _ => None,
            }
        })
    }

    fn connection(source: Option<Peer>, destination: Option<Peer>) -> Option<Connection> {
        Some(Connection::new(source?, destination?))
    }
}
