/// The core VPN packet shoveling infrastructure.

use bytes::Bytes;
use evmap::{ReadHandle, WriteHandle};
use tokio_util::sync::CancellationToken;
use std::{hash::{Hash, RandomState}, net::IpAddr, sync::Arc};
use tokio::{net::TcpListener, sync::{mpsc::Sender, Mutex}};

use crate::{auth::Authenticator, filter::Filter, logging::Logger, vpn::connection::Connection};

pub(crate) type ConnectionId = u64;

/// State for a single connection. Kept in an evmap to translate IP addresses to connections
/// efficiently.
pub(crate) struct ConnectionState {
    pub outbound: Sender<Bytes>,
    pub id: ConnectionId,
}
impl Hash for ConnectionState {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        // Don't hash in the Sender. That doesn't matter for our usecase.
        self.id.hash(state)
    }
}
impl PartialEq for ConnectionState {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}
impl Eq for ConnectionState {}

/// Connection mappings.
pub(crate) type ConnectionMapReader = ReadHandle<IpAddr, Arc<ConnectionState>, (), RandomState>;
pub(crate) type ConnectionMapWriter = WriteHandle<IpAddr, Arc<ConnectionState>, (), RandomState>;

/// Listens for new VPN connections.
pub(crate) struct VpnListener {
    /// Unique connection ID. Counts up.
    next: ConnectionId,
    /// TCP listener for the VPN socket.
    listener: TcpListener,
    /// Authenticator for the VPN
    auth: Arc<dyn Authenticator>,
    /// Logger for invalid packets
    logger: Arc<dyn Logger>,
    /// Writer/updater for the connection map.
    updater: Arc<Mutex<ConnectionMapWriter>>,
    /// Global submission queue for filtered packets.
    submission_queue: Sender<Bytes>,
    /// The packet filter.
    filter: Filter,
}

impl VpnListener {
    /// Accept connections until an error occurs (e.g., the connection is closed), or the `token`
    /// is cancelled.
    pub async fn handle_until(&mut self, token: CancellationToken) {
        loop {
            self.next = self.next.wrapping_add(1);
            let id = self.next;
            tokio::select! {
                _ = token.cancelled() => return,
                connection = self.listener.accept() => match connection {
                    Ok((tcp, remote)) => {
                        tracing::debug!("New VPN connection {id} from {remote}");
                        let mut connection = Connection::new(
                            id,
                            remote,
                            tcp,
                            self.submission_queue.clone(),
                            self.filter.clone(),
                            self.logger.clone(),
                        );
                        let token = token.clone();
                        let updater = self.updater.clone();
                        let authenticator = self.auth.clone();
                        tokio::spawn(async move {
                            let auth = tokio::select! {
                                _ = token.cancelled() => { return; }
                                result = connection.handshake(authenticator) => {
                                    match result {
                                        Ok(auth) => auth,
                                        Err(error) => {
                                            tracing::info!("Connection {}: {}", id, error);
                                            return;
                                        }
                                    }
                                }
                            };

                            tracing::debug!("Connection {} authenticated as {}", id, &auth.name);
                            let (inbound, outbound, queue) = connection.confirm();
                            let state = Arc::new(ConnectionState { outbound: queue, id });

                            // Start the outbound task first. This will error eventually when the
                            // connection goes away.
                            tokio::spawn(outbound.forward_until(token.clone()));

                            // Then, insert the connection into the packet mapping.
                            {
                                let mut guard = updater.lock().await;
                                for ip in auth.ips.iter() {
                                    guard.update(*ip, state.clone());
                                }
                                guard.refresh();
                            }

                            // Finally, start forwarding inbound packets
                            tracing::debug!("Connection {id} is now forwarding traffic");
                            inbound.forward_until(token).await;

                            // Once this is done, remove it from the queue. That'll close the
                            // outbound submission queue and then kill the outbound task.
                            {
                                let mut guard = updater.lock().await;
                                for ip in auth.ips.into_iter() {
                                    guard.remove(ip, state.clone());
                                }
                                guard.refresh();
                            }
                            tracing::debug!("Connection {id} disconnected");
                        });
                    },
                    Err(error) => {
                        tracing::error!("Failed to accept inbound connection: {error}");
                        return;
                    },
                }
            }
        }
    }

    /// Creates a new VPN listener and connection map reader for the packet receive ring.
    /// Takes a `TcpListener` (for inbound connections), a `Sender<Bytes>` on which to submit
    /// packets to the packet ring, and the filter implementation.
    pub(crate) fn new(listener: TcpListener, auth: Arc<dyn Authenticator>, logger: Arc<dyn Logger>, submission_queue: Sender<Bytes>, filter: Filter) -> (VpnListener, ConnectionMapReader) {
        let (reader, writer) = evmap::new();
        let vpn = VpnListener {
            next: 0,
            listener,
            auth,
            logger,
            updater: Arc::new(Mutex::new(writer)),
            submission_queue,
            filter
        };
        (vpn, reader)
    }
}

