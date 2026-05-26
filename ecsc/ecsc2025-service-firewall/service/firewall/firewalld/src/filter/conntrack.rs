/// Connection tracking for packet filtering.

use crate::filter::packet::{Connection, Packet, Peer};
use ipnet::IpNet;
use moka::{future::Cache, policy::EvictionPolicy};
use regex::bytes::{Captures, Regex};
use std::{hash::RandomState, net::{IpAddr, Ipv4Addr, Ipv6Addr}, sync::LazyLock, time::Duration};

/// Connection state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum State {
    /// Invalid packets (e.g. rejected connections in special cases)
    Invalid,
    /// New connection (e.g. TCP SYN).
    New,
    /// Established connection.
    Established,
    /// Related connections (e.g. FTP data channels, replaces New for these connections).
    Related,
    /// Otherwise untracked packets (e.g. UDP, plain IP, ...).
    Untracked,
}

/// We can derive a connection state from a trackable packet, and apply special tracking rules to
/// it.
// We don't provide any implementations here since this requires an underlying `Table` or similar
// thing. See `filter::context::Context` for an object with an actual implementation of this.
#[async_trait::async_trait]
pub(crate) trait Track {
    /// Determines and returns the connection state of a packet.
    async fn state(&self) -> State;
    /// Applies special tracking rules.
    // This will eventually end up in `Table::apply`.
    async fn track(&self, what: &str, args: &[String]);
}

/// Metadata kept for a connection.
#[derive(Clone)]
struct Metadata {
    pub state: State,
    pub initiator: Peer,
}

impl Metadata {
    fn with_state(self, state: State) -> Self {
        Self { state, initiator: self.initiator }
    }
}

/// Connection state tracking.
// NB: This is done per VPN connection.
#[derive(Clone)]
pub(crate) struct Table {
    // Maps connections to their known state.
    // Entries will remain in here longer than needed to avoid overhead on the "hot" paths of TCP
    // processing. We add established connections on SYN+ACK, related connections by explicit
    // tracking, and check for state on demand.
    cache: Cache<Connection, Metadata, RandomState>,
    pending: Cache<Connection, (), RandomState>,
}

impl Table {
    /// Creates a new connection table
    pub fn new() -> Self {
        let cache = Cache::builder()
            .eviction_policy(EvictionPolicy::lru())
            .time_to_idle(Duration::from_secs(180))
            .initial_capacity(64)
            .max_capacity(4096)
            .build();
        let pending = Cache::builder()
            .eviction_policy(EvictionPolicy::lru())
            .time_to_idle(Duration::from_secs(180))
            .initial_capacity(32)
            .max_capacity(2048)
            .build();
        Self { cache, pending }
    }

    /// Gets the metadata of connection four-tuple.
    async fn get_metadata(&self, conn: &Connection) -> Option<Metadata> {
        self.cache.get(conn).await
    }

    /// Inserts metadata for a connection into the cache.
    async fn insert(&self, conn: Connection, metadata: Metadata) {
        self.cache.insert(conn, metadata).await;
        self.cache.run_pending_tasks().await // Explicitly ensure everything is inserted.
                                             // TODO: I'm not sure this is really necessary.
    }

    /// Forgets a connection four-tuple.
    async fn forget(&self, conn: &Connection) {
        self.cache.invalidate(conn).await;
    }

    /// Gets the state of a connection four-tuple.
    pub async fn get(&self, conn: &Connection) -> Option<State> {
        self.get_metadata(conn).await.map(|m| m.state)
    }

    /// Queries the cache for a pending related connection. Returns the expected state.
    pub async fn complete_pending(&self, conn: &Connection) -> State {
        for partial in conn.partial().into_iter() {
            if let Some(()) = self.pending.remove(&partial).await {
                return State::Related;
            }
        }
        State::New
    }
}

// These are special tracking operations that can set connection state.
impl Table {
    /// Tracks connection state for a TCP connection. Returns the new state of the connection.
    // This only changes state on SYN and SYN-ACK packets to keep processing of data traffic low.
    // Dropped TCP connections will eventually age out of the pool. Actually running TCP
    // connections get a `get()` when a `state` query is made, so we don't have to worry about
    // time-to-idle here.
    async fn tcp<P: Packet>(&self, conn: Connection, packet: &P) -> Option<State> {
        let (l4proto, l4) = packet.layer_4()?;
        if l4proto != libc::IPPROTO_TCP { return None; }
        let flags = l4.get(13)?;

        if flags & (TCP_SYN | TCP_ACK) == TCP_SYN {
            let initiator = Peer::new(packet.source_ip()?, packet.layer_4_ports()?.source);
            let state = self.complete_pending(&conn).await;
            self.insert(conn, Metadata { state, initiator }).await;
            Some(state)
        } else if flags & (TCP_SYN | TCP_ACK) == TCP_SYN | TCP_ACK {
            let source = Peer::new(packet.source_ip()?, packet.layer_4_ports()?.source);
            let metadata = self.get_metadata(&conn).await?;
            if source != metadata.initiator {
                self.insert(conn, metadata.with_state(State::Established)).await;
                Some(State::Established)
            } else {
                self.forget(&conn).await;
                Some(State::Invalid)
            }
        } else {
            None
        }
    }

    /// Tracks related connections for FTP connections. This is needed to allow the data channel
    /// through the firewall.
    async fn ftp<P: Packet>(&self, pattern: &Pattern, packet: &P) -> Option<State> {
        let destination = packet.destination_ip()?;
        let peer = pattern.extract(packet)?;

        let partial = Connection::new(Peer::new(destination, 0), peer);
        tracing::trace!("Connection tracking: FTP: Adding new related connection {partial}");
        self.pending.insert(partial, ()).await;
        None // No change in the state of _this_ connection.
    }

    /// Applies any of the "special" tracking rules to this packet.
    pub async fn apply<P: Packet>(&self, packet: &P, what: &str, args: &[String]) -> Option<State> {
        match what {
            "tcp" => {
                let should_track = |net: IpNet| -> Option<bool> {
                    Some(net.contains(&packet.destination_ip()?) || net.contains(&packet.source_ip()?))
                };
                if args.is_empty() || args.iter().any(|net| net.parse::<IpNet>().ok().and_then(should_track).unwrap_or(false)) {
                    self.tcp(packet.connection()?, packet).await
                } else {
                    None
                }
            },
            "ftp" => {
                let server: Vec<_> = args.iter().map(|ip| ip.parse::<IpAddr>()).filter_map(|ip| ip.ok()).collect();
                if server.contains(&packet.destination_ip()?) {
                    self.ftp(&FTP_PORT, packet).await;
                    self.ftp(&FTP_EPRT, packet).await
                } else if server.contains(&packet.source_ip()?) {
                    self.ftp(&FTP_PASV, packet).await;
                    self.ftp(&FTP_EPSV, packet).await
                } else {
                    None
                }
            },
            _ => {
                tracing::warn!("Attempting to track connection with unknown tracking rule \"{what}\"");
                None
            },
        }
    }
}

// TCP flags for connection tracking
const TCP_SYN: u8 = 0x02;
const TCP_ACK: u8 = 0x10;

// FTP patterns for connection tracking
struct Pattern {
    regex: Regex,
    parse: fn (Captures<'_>, IpAddr) -> Option<Peer>,
}

impl Pattern {
    /// Creates a new `Pattern`.
    pub fn new(regex: &str, parse: fn (Captures<'_>, IpAddr) -> Option<Peer>) -> Result<Self, regex::Error> {
        Ok(Self { regex: Regex::new(regex)?, parse })
    }

    /// Extracts the peer information from a packet.
    pub fn extract<P: Packet>(&self, packet: &P) -> Option<Peer> {
        (self.parse)(self.regex.captures(packet.layer_5()?)?, packet.source_ip()?)
    }
}

static FTP_PORT: LazyLock<Pattern> = LazyLock::new(|| {
    Pattern::new(r"PORT\s+(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})", |captures, _| {
        // PORT 192,0,2,42,5,57
        ftp_extract(captures).ok()
    }).expect("Invalid pattern")
});
static FTP_PASV: LazyLock<Pattern> = LazyLock::new(|| {
    Pattern::new(r"227\s+.+\s+\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})\)", |captures, _| {
        // 227 Entering passive mode (192,0,2,42,5,57)
        ftp_extract(captures).ok()
    }).expect("Invalid pattern")
});
static FTP_EPRT: LazyLock<Pattern> = LazyLock::new(|| {
    Pattern::new(r"EPRT\s+([!-~])(\d)([!-~])([0-9a-fA-F.:]+)([!-~])(\d{1,5})([!-~])", |captures, _| {
        // EPRT |2|2001:0db8::42|1337|
        let (_, captures): (&[u8], [&[u8]; 7]) = captures.extract();
        if captures[0] != captures[2] || captures[0] != captures[4] || captures[0] != captures[6] {
            // Delimiter <d> must always be the same.
            return None;
        }
        let port = atoi_simd::parse::<u16>(captures[5]).ok()?;
        let address = std::str::from_utf8(captures[3]).ok()?;
        let destination: IpAddr = match captures[1] {
            b"1" => address.parse::<Ipv4Addr>().ok()?.into(),
            b"2" => address.parse::<Ipv6Addr>().ok()?.into(),
            _ => return None, // Unknown address family
        };
        Some(Peer::new(destination, port))
    }).expect("Invalid pattern")
});
static FTP_EPSV: LazyLock<Pattern> = LazyLock::new(|| {
    Pattern::new(r"229\s+.+\s+\(([!-~]{3})(\d{1,5})([!-~])\)", |captures, source_ip| {
        // 229 Entering extended passive mode (|||1337|)
        let (_, captures): (&[u8], [&[u8]; 3]) = captures.extract();
        if captures[0].into_iter().any(|byte| *byte != captures[2][0]) {
            // Delimiter <d> must always be the same.
            return None;
        }
        let port = atoi_simd::parse::<u16>(captures[1]).ok()?;
        Some(Peer::new(source_ip, port))
    }).expect("Invalid pattern")
});

/// Extracts IPv4 FTP PORT/PASV specifiers from Regex captures
fn ftp_extract<'h>(captures: Captures<'h>) -> Result<Peer, atoi_simd::AtoiSimdError<'h>> {
    let (_, captures): (&[u8], [&[u8]; 6]) = captures.extract();
    let ip: IpAddr = Ipv4Addr::new(
        atoi_simd::parse::<u8>(captures[0])?,
        atoi_simd::parse::<u8>(captures[1])?,
        atoi_simd::parse::<u8>(captures[2])?,
        atoi_simd::parse::<u8>(captures[3])?,
    ).into();
    let port_high: u16 = atoi_simd::parse::<u8>(captures[4])?.into();
    let port_low: u16 = atoi_simd::parse::<u8>(captures[5])?.into();
    let port = port_high << 8 | port_low;
    Ok(Peer::new(ip, port))
}
