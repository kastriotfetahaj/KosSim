/// A simple VPN to communicate with the network behind this firewall.
///
/// Thread layout: There are two separate hardware threads for packet ring management.
/// The remaining threads handle inbound and outbound traffic through tokio, and perform the actual
/// firewalling.

use bytes::Bytes;
use tokio::{net::TcpSocket, sync::{mpsc::{self, Receiver, Sender}, oneshot}};
use tokio_util::sync::CancellationToken;
use std::{net::{IpAddr, SocketAddr}, sync::Arc, time::Duration};

pub(crate) mod arp;
pub(crate) mod core;
use core::{ConnectionMapReader, VpnListener};
pub(crate) mod connection;
pub(crate) mod packets;
use packets::{PacketSocket, RingConfig};

use crate::{auth::Authenticator, filter::Filter, logging::Logger};

const BLOCK_SIZE: usize = 0x1000 << 11;
const BLOCK_COUNT: usize = 32;
const FRAME_SIZE: usize = 0x800;
const RX_RETIRE_TIMEOUT: Duration = Duration::from_millis(100);

const SHARED_QUEUE_SIZE: usize = 16384; // Across _all_ clients
const ARP_QUEUE_SIZE: usize = 8192;

/// The main VPN object.
pub(crate) struct Vpn {
    address: SocketAddr,
    listener: VpnListener,
    socket: PacketSocket,
    connection_map: ConnectionMapReader,
    submission_rx: Receiver<Bytes>,
    arp_tx: Sender<(IpAddr, Bytes)>,
    arp_reader: arp::ArpTableReader,
}

impl Vpn {
    /// Creates a new VPN instance.
    pub async fn new(address: SocketAddr, interface: String, bind_device: Option<String>, auth: Arc<dyn Authenticator>, logger: Arc<dyn Logger>, filter: Filter) -> std::io::Result<Self> {
        let socket = if address.is_ipv6() { TcpSocket::new_v6()? } else { TcpSocket::new_v4()? };
        socket.set_reuseaddr(true)?;
        if let Some(bind_device) = bind_device { socket.bind_device(Some(bind_device.as_bytes()))?; }
        socket.bind(address)?;
        let listener = socket.listen(1024)?;

        let rx_config = RingConfig {
            block_count: BLOCK_COUNT,
            block_size: BLOCK_SIZE,
            frame_size: FRAME_SIZE,
            rx_retire_timeout: Some(RX_RETIRE_TIMEOUT),
        };
        let tx_config = RingConfig {
            block_count: BLOCK_COUNT,
            block_size: BLOCK_SIZE,
            frame_size: FRAME_SIZE,
            rx_retire_timeout: None
        };
        let socket = PacketSocket::new(&interface, rx_config, tx_config)?;

        let (submission_tx, submission_rx) = mpsc::channel(SHARED_QUEUE_SIZE);
        let (listener, connection_map) = VpnListener::new(listener, auth, logger, submission_tx.clone(), filter);
        let weak_tx = submission_tx.downgrade();

        // Run the VPN's ARP lookup service.
        // We start it here instead of in run() to ensure that we can drop privileges cleanly later.
        let (arp_tx, arp_rx) = mpsc::channel(ARP_QUEUE_SIZE);
        let (arp_reader, arp_writer) = evmap::new();
        let arp_internal = arp_reader.clone();
        let (arp_ready_tx, arp_ready_rx) = oneshot::channel();
        tokio::spawn(async move {
            if let Err(error) = arp::lookup(arp_rx, weak_tx /* Resubmit */, arp_internal, arp_writer,
                                            arp_ready_tx).await {
                tracing::warn!("Neighbor lookup failed internally: {error}");
            }
        });
        // Wait for ARP lookup to finish all privileged operations.
        arp_ready_rx.await.map_err(|_| std::io::Error::other("Failed to wait for ARP service"))?;

        Ok(Self { address, listener, socket, connection_map, submission_rx, arp_tx, arp_reader })
    }

    /// Runs the VPN until the given `token` is cancelled or a fatal error occurs.
    pub async fn run(mut self, token: CancellationToken) {
        tracing::info!("VPN is listening on {}", self.address);

        let (tx_terminate, tx_join) = self.socket.tx.transmit(self.submission_rx, self.arp_reader, self.arp_tx);
        let (rx_terminate, rx_join) = self.socket.rx.receive(self.connection_map);

        self.listener.handle_until(token).await;

        if let Err(_) = rx_terminate.send(()) {
            tracing::warn!("Failed to signal termination to the receive thread");
        }
        if let Err(_) = tx_terminate.send(()) {
            tracing::warn!("Failed to signal termination to the transmit thread");
        }
        if let Err(_) = tokio::task::spawn_blocking(move || {
            if let Err(_) = rx_join.join() { tracing::error!("Receive thread panicked"); }
            if let Err(_) = tx_join.join() { tracing::error!("Transmit thread panicked"); }
        }).await {
            tracing::warn!("Failed to wait for packet forwarding threads");
        }
    }
}

