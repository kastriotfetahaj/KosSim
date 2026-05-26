/// Individual VPN connections

use bytes::Bytes;
use crate::{auth::{Auth, AuthError, Authenticator}, filter::{conntrack::Table, packet::Packet, Filter, Verdict}, logging::Logger, vpn::core::ConnectionId};
use std::{collections::HashSet, net::{IpAddr, SocketAddr}, sync::Arc};
use tokio::{io::{AsyncReadExt, AsyncWriteExt}, net::{tcp::{OwnedReadHalf, OwnedWriteHalf}, TcpStream}, sync::mpsc::{self, Receiver, Sender}};
use tokio_util::sync::CancellationToken;

const PACKET_BACKLOG: usize = 32;
const MAX_INBOUND_PACKET_LENGTH: u16 = 1500;

pub(crate) struct Connection {
    /// Name of this connection in the log.
    name: String,
    /// Underlying TCP stream.
    tcp: TcpStream,
    /// Downstream packet transmit queue.
    queue: Sender<Bytes>,
    /// Packet filtering hook.
    filter: Filter,
    /// Packet logger.
    logger: Arc<dyn Logger>,
    /// Connection tracking for filtering.
    ct: Table,
    /// Authentication, if any
    auth: Option<Auth>,
}

impl Connection {
    /// Creates a new `Connection`.
    pub fn new(id: ConnectionId, remote: SocketAddr, tcp: TcpStream, queue: Sender<Bytes>, filter: Filter, logger: Arc<dyn Logger>) -> Self {
        Self { name: format!("{remote} ({id})"), tcp, queue, filter, logger, ct: Table::new(), auth: None }
    }

    /// Reads single-byte length and appropriately many bytes for the handshake.
    async fn read_block(&mut self) -> Result<Vec<u8>, AuthError> {
        if let Ok(length) = self.tcp.read_u8().await {
            let mut buffer = vec![0u8; length.into()];
            if let Ok(_) = self.tcp.read_exact(&mut buffer).await {
                return Ok(buffer);
            }
        }
        Err(AuthError::NetworkError)
    }

    /// Performs the initial handshake on the connection.
    pub async fn handshake(&mut self, auth: Arc<dyn Authenticator>) -> Result<Auth, AuthError> {
        let user_bytes = self.read_block().await?;
        let password_bytes = self.read_block().await?;
        if user_bytes.is_empty() || password_bytes.is_empty() {
            return Err(AuthError::InvalidRequest);
        }
        let user = std::str::from_utf8(&user_bytes).map_err(|_| AuthError::InvalidRequest)?;
        let password = std::str::from_utf8(&password_bytes).map_err(|_| AuthError::InvalidRequest)?;
        tracing::debug!("{}: Attempting to authenticate as user {:?}", &self.name, user);
        let auth = auth.authenticate(user, password).await?;

        let ipv4 = auth.ipv4();
        let ipv6 = auth.ipv6();
        if ipv4.is_none() && ipv6.is_none() {
            return Err(AuthError::InternalError(format!("User {:?} has no assigned IP addresses", user)));
        }

        let ipv4 = ipv4.map(|ip| ip.octets()).unwrap_or_default();
        let ipv6 = ipv6.map(|ip| ip.octets()).unwrap_or_default();
        self.tcp.write_all(&ipv4).await.map_err(|_| AuthError::NetworkError)?;
        self.tcp.write_all(&ipv6).await.map_err(|_| AuthError::NetworkError)?;

        self.auth = Some(auth.clone());
        Ok(auth)
    }

    /// Turns the `Connection` into an inbound packet stream (that forwards packets into the given
    /// queue), an outbound packet stream (that takes packets and pushes them into the TCP
    /// connection), and a packet `Sender` to which to pass outbound packets for this specific
    /// recipient.
    pub fn confirm(self) -> (Inbound, Outbound, Sender<Bytes>) {
        let (tcp_read, tcp_write) = self.tcp.into_split();
        let (outbound_write, outbound_read) = mpsc::channel(PACKET_BACKLOG);
        let (user, ips) = match self.auth {
            Some(auth) => (Some(auth.name), auth.ips.into_iter().collect()),
            None => (None, HashSet::new()),
        };
        (
            Inbound { name: self.name.clone(), user: user.clone(), read: tcp_read, queue: self.queue, filter: self.filter.clone(), logger: self.logger.clone(), ips, ct: self.ct.clone() },
            Outbound { name: self.name, user, write: tcp_write, queue: outbound_read, filter: self.filter, logger: self.logger, ct: self.ct },
            outbound_write
        )
    }
}

pub(crate) struct Inbound {
    /// Name of this connection in the log.
    name: String,
    /// Name of the user for this connection.
    user: Option<String>,
    /// Read half of the TCP stream.
    read: OwnedReadHalf,
    /// Downstream packet transmit queue.
    queue: Sender<Bytes>,
    /// Packet filtering hook.
    filter: Filter,
    /// Packet logger.
    logger: Arc<dyn Logger>,
    /// Connection tracking table.
    ct: Table,
    /// Allowed inbound IPs.
    ips: HashSet<IpAddr>,
}

pub(crate) struct Outbound {
    /// Name of this connection in the log.
    name: String,
    /// Name of the user for this connection.
    user: Option<String>,
    /// Write half of the TCP stream.
    write: OwnedWriteHalf,
    /// Queue from downstream.
    queue: Receiver<Bytes>,
    /// Packet filtering hook.
    filter: Filter,
    /// Packet logger.
    logger: Arc<dyn Logger>,
    /// Connection tracking table.
    ct: Table,
}

impl Inbound {
    /// Decides whether this connection may accept the given packet.
    fn may_accept(&self, packet: &[u8]) -> bool {
        match packet.source_ip() {
            Some(addr) => self.ips.contains(&addr),
            None => false,
        }
    }

    /// Called when a packet is dropped for any reason.
    async fn dropped(&self, packet: &[u8]) {
        match &self.user {
            Some(user) => {
                if let Err(error) = self.logger.log_packet(user, packet).await {
                    tracing::error!(
                        "Failed to log inbound packet {:?}: {}",
                        bytes::Bytes::copy_from_slice(packet),
                        error
                    );
                }
            },
            None => tracing::warn!(
                "Dropping inbound packet {:?} with no associated user on connection {}",
                bytes::Bytes::copy_from_slice(packet),
                &self.name
            ),
        }
    }

    /// Forward packets until an error occurs (e.g., the connection is closed), or the `token` is
    /// cancelled.
    pub async fn forward_until(mut self, token: CancellationToken) {
        loop {
            let length = tokio::select! {
                _ = token.cancelled() => return,
                result = self.read.read_u16() => match result {
                    Ok(length) => length,
                    Err(error) => {
                        // Packet reading failed, probably the client just closed the connection.
                        tracing::debug!("{}: Failed to receive inbound packet header: {}", &self.name, error);
                        return;
                    },
                },
            };

            let mut buffer = vec![0u8; length.into()];
            tokio::select! {
                _ = token.cancelled() => return,
                result = self.read.read_exact(&mut buffer) => match result {
                    Ok(_) => (),
                    Err(error) => {
                        // Packet reading failed, probably the client just closed the connection.
                        tracing::debug!("{}: Failed to receive inbound packet data: {}", &self.name, error);
                        return;
                    }
                },
            };

            if length >= MAX_INBOUND_PACKET_LENGTH {
                tracing::trace!("{} (inbound): Dropping overlong packet ({} bytes)", &self.name, length);
                self.dropped(&buffer).await;
                continue;
            }
            if !self.may_accept(&buffer) {
                tracing::trace!("{} (inbound): Dropping invalid packet", &self.name);
                self.dropped(&buffer).await;
                continue;
            }

            let mut packet = buffer.into();
            tracing::trace!("{} (inbound): Processing {} bytes", &self.name, length);
            match self.filter.apply(&mut packet, self.ct.clone()).await {
                Verdict::Allow => (),
                Verdict::Drop => {
                    self.dropped(&packet).await;
                    continue;
                },
            };

            tracing::trace!("{} (inbound): Forwarding {} bytes", &self.name, length);
            tokio::select! {
                _ = token.cancelled() => return,
                result = self.queue.send(packet) => match result {
                    Ok(()) => continue,
                    Err(_) => {
                        // Packet forwarding failed, maybe the token is late?
                        tracing::warn!("{}: Failed to forward inbound packet", &self.name);
                        return;
                    },
                },
            }
        }
    }
}

impl Outbound {
    /// Called when a packet is dropped for any reason.
    async fn dropped(&self, packet: &[u8]) {
        match &self.user {
            Some(user) => {
                if let Err(error) = self.logger.log_packet(user, packet).await {
                    tracing::error!(
                        "Failed to log outbound packet {:?}: {}",
                        bytes::Bytes::copy_from_slice(packet),
                        error
                    );
                }
            },
            None => tracing::warn!(
                "Dropping outbound packet {:?} with no associated user on connection {}",
                bytes::Bytes::copy_from_slice(packet),
                &self.name
            ),
        }
    }

    /// Forward packets until an error occurs (e.g., the connection is closed), or the `token` is
    /// cancelled.
    pub async fn forward_until(mut self, token: CancellationToken) {
        loop {
            let mut packet = tokio::select! {
                _ = token.cancelled() => return,
                result = self.queue.recv() => match result {
                    Some(packet) => packet,
                    None => {
                        // Queue closed, was the token late?
                        tracing::trace!("{}: Failed to read outbound packet", &self.name);
                        return;
                    },
                },
            };

            let Ok(length): Result<u16, _> = packet.len().try_into() else {
                tracing::trace!("{} (outbound): Dropping overlong packet ({} bytes)", &self.name, packet.len());
                self.dropped(&packet).await;
                continue;
            };

            // We don't need to filter on destination() here since we already mapped the
            // destination IP to this connection.

            tracing::trace!("{} (outbound): Processing {} bytes", &self.name, packet.len());
            match self.filter.apply(&mut packet, self.ct.clone()).await {
                Verdict::Allow => (),
                Verdict::Drop => {
                    self.dropped(&packet).await;
                    continue;
                },
            };

            tracing::trace!("{} (outbound): Forwarding {} bytes", &self.name, packet.len());
            tokio::select! {
                _ = token.cancelled() => return,
                result = self.write.write_u16(length) => match result {
                    Ok(()) => (),
                    Err(error) => {
                        // Packet sending failed, probably the client just closed the connection.
                        tracing::debug!("{}: Failed to send outbound packet header: {}", &self.name, error);
                        return;
                    },
                },
            };
            tokio::select! {
                _ = token.cancelled() => return,
                result = self.write.write_all(&packet) => match result {
                    Ok(_) => (),
                    Err(error) => {
                        // Packet sending failed, probably the client just closed the connection.
                        tracing::debug!("{}: Failed to send outbound packet data: {}", &self.name, error);
                        return;
                    },
                },
            };
        }
    }
}
