/// For filtering, we keep a separate context object for each packet. This is a caching layer
/// around a packet (using its `packet::PacketUtil` to provide a more efficient `packet::Packet`
/// implementation) and a conntrack table (to provide a `conntrack::Track` implementation).
/// This saves lookup time for repeated lookups of the same property.

use crate::filter::{conntrack::{State, Table, Track}, packet::{Connection, IpVersion, PacketUtil, Packet, Peer, Ports}};
use std::{net::IpAddr, sync::OnceLock};
use tokio::sync::RwLock;

/// A caching wrapper for the packet lookups.
pub(crate) struct Context<'packet, P: PacketUtil + ?Sized> {
    inner: &'packet P,
    ip_version: OnceLock<Option<IpVersion>>,
    source_ip: OnceLock<Option<IpAddr>>,
    destination_ip: OnceLock<Option<IpAddr>>,
    layer_4: OnceLock<Option<(i32, &'packet [u8])>>,
    layer_4_ports: OnceLock<Option<Ports>>,
    layer_4_source: OnceLock<Option<Peer>>,
    layer_4_destination: OnceLock<Option<Peer>>,
    layer_5: OnceLock<Option<&'packet [u8]>>,
    connection: OnceLock<Option<Connection>>,

    // This can actually change during processing
    table: Table,
    state: RwLock<Option<State>>,
}

impl<'packet, P: PacketUtil + Sync + ?Sized> Context<'packet, P> {
    pub fn new(inner: &'packet P, table: Table) -> Self {
        Self {
            inner,
            ip_version: OnceLock::new(),
            source_ip: OnceLock::new(),
            destination_ip: OnceLock::new(),
            layer_4: OnceLock::new(),
            layer_4_ports: OnceLock::new(),
            layer_4_source: OnceLock::new(),
            layer_4_destination: OnceLock::new(),
            layer_5: OnceLock::new(),
            connection: OnceLock::new(),
            table,
            state: RwLock::new(None),
        }
    }
}

impl<'packet, P: PacketUtil + Sync + ?Sized> Packet for Context<'packet, P> where Self: 'packet {
    fn ip_version(&self) -> Option<IpVersion> {
        self.ip_version.get_or_init(|| self.inner.ip_version()).clone()
    }

    fn source_ip(&self) -> Option<IpAddr> {
        self.source_ip.get_or_init(|| self.inner.source_ip(self.ip_version())).clone()
    }

    fn destination_ip(&self) -> Option<IpAddr> {
        self.destination_ip.get_or_init(|| self.inner.destination_ip(self.ip_version())).clone()
    }

    fn layer_3(&self) -> &[u8] {
        self.inner.layer_3() // This one is cheap and does not need to be cached.
    }

    fn layer_4(&self) -> Option<(i32, &'packet [u8])> {
        self.layer_4.get_or_init(|| self.inner.layer_4(self.ip_version())).clone()
    }

    fn layer_4_ports(&self) -> Option<Ports> {
        self.layer_4_ports.get_or_init(|| P::layer_4_ports(self.layer_4())).clone()
    }

    fn layer_5(&self) -> Option<&'packet [u8]> {
        self.layer_5.get_or_init(move || {
            // Oof. Can't extend the lifetime of self.layer_4() to 'packet even though we know the
            // reference is valid. In any case, this is the only place where we need to do this
            // nonsense and filters on L5 contents are generally rare anyways.
            P::layer_5(self.inner.layer_4(self.ip_version()))
        }).clone()
    }

    fn layer_4_source(&self) -> Option<Peer> {
        self.layer_4_source.get_or_init(|| P::layer_4_source(self.source_ip(), self.layer_4_ports())).clone()
    }

    fn layer_4_destination(&self) -> Option<Peer> {
        self.layer_4_destination.get_or_init(|| P::layer_4_destination(self.destination_ip(), self.layer_4_ports())).clone()
    }

    fn connection(&self) -> Option<Connection> {
        self.connection.get_or_init(|| P::connection(self.layer_4_source(), self.layer_4_destination())).clone()
    }
}

#[async_trait::async_trait]
impl<'packet, P: PacketUtil + Sync + ?Sized> Track for Context<'packet, P> where Self: 'packet {
    async fn state(&self) -> State {
        let reader = self.state.read().await;
        if let Some(state) = *reader {
            return state;
        }
        drop(reader);

        let mut writer = self.state.write().await;
        match *writer {
            Some(state) => state,
            None => {
                let state = match self.connection() {
                    Some(conn) => self.table.get(&conn).await.unwrap_or(State::Untracked),
                    None => State::Untracked,
                };
                *writer = Some(state);
                state
            }
        }
    }

    async fn track(&self, what: &str, args: &[String]) {
        if let Some(state) = self.table.apply(self, what, args).await {
            let mut writer = self.state.write().await;
            *writer = Some(state);
        }
    }
}
