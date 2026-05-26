use bytes::Bytes;
use crate::{
    filter::packet::Packet,
    vpn::{arp::{ArpTableReader, MacAddress, get_mac_address}, core::ConnectionMapReader}
};
use nix::{
    errno::Errno, net::if_::if_nametoindex, poll::{self, PollFd, PollFlags, PollTimeout},
    sys::{
        mman::{self, MapFlags, ProtFlags},
        socket::{self, AddressFamily, MsgFlags, Shutdown, SockFlag, SockType, SockaddrLike}
    },
    unistd::{self, SysconfVar}
};
use tokio::sync::{mpsc::{self, error::TrySendError}, oneshot};
use std::{
    io::ErrorKind, net::IpAddr, num::NonZero, os::fd::{AsFd, AsRawFd, OwnedFd}, ptr::NonNull,
    sync::Arc, thread, time::{Duration, Instant}
};

/// Sets a socket option with setsockopt.
pub(crate) fn setsockopt<F: AsRawFd, V>(fd: &F, level: i32, name: i32, value: &V) -> nix::Result<()> {
    let res = unsafe {
        libc::setsockopt(
            fd.as_raw_fd(),
            level,
            name,
            value as *const V as *const libc::c_void,
            std::mem::size_of::<V>() as u32
        )
    };
    Errno::result(res).map(drop)
}

/// Creates a nix-compatible link-layer adress from the libc::sockaddr_ll.
fn link_addr_from(sll: libc::sockaddr_ll) -> std::io::Result<socket::LinkAddr> {
    // There is no constructor for LinkAddr, so we have to do the dance through a
    // *const libc::sockaddr. See https://github.com/nix-rust/nix/issues/2059
    unsafe {
        socket::LinkAddr::from_raw(
            &sll as *const libc::sockaddr_ll as *const libc::sockaddr,
            Some(std::mem::size_of::<libc::sockaddr_ll>() as u32)
        )
    }.ok_or(ErrorKind::AddrNotAvailable.into())
}

/// Creates a link-layer address for the given interface.
fn link_addr_for_interface(interface: i32) -> std::io::Result<socket::LinkAddr> {
    let sll = libc::sockaddr_ll {
        sll_family: libc::AF_PACKET as u16,
        sll_protocol: (libc::ETH_P_ALL as u16).to_be(),
        sll_ifindex: interface,
        sll_hatype: 0,
        sll_pkttype: 0,
        sll_halen: 0,
        sll_addr: [0u8; 8],
    };
    link_addr_from(sll)
}

/// Makes an ethernet header.
fn ethernet_header(destination: &MacAddress, source: &MacAddress, ethertype: u16) -> [u8; libc::ETH_HLEN as usize] {
    let mut header = [0u8; libc::ETH_HLEN as usize];
    (&mut header[..libc::ETH_ALEN as usize]).copy_from_slice(destination);
    (&mut header[libc::ETH_ALEN as usize..2 * libc::ETH_ALEN as usize]).copy_from_slice(source);
    header[2 * libc::ETH_ALEN as usize] = (ethertype >> 8) as u8;
    header[2 * libc::ETH_ALEN as usize + 1] = (ethertype & 0xff) as u8;
    header
}

/// Packet ring address information.
#[derive(Clone, Copy, Debug)]
struct AddressData {
    pub mac: MacAddress,
}

/// A packet ring config.
#[derive(Clone, Debug)]
pub struct RingConfig {
    /// Size of each block, in bytes.
    pub block_size: usize,
    /// Number of blocks.
    pub block_count: usize,
    /// Size of each frame (should be > MTU).
    pub frame_size: usize,
    /// Timeout at which to receive non-full receive blocks.
    pub rx_retire_timeout: Option<Duration>,
}

impl TryInto<libc::tpacket_req3> for RingConfig {
    type Error = std::io::Error;

    fn try_into(self) -> Result<libc::tpacket_req3, Self::Error> {
        let page_size = unistd::sysconf(SysconfVar::PAGE_SIZE)?
            .expect("sysconf(_SC_PAGE_SIZE) has no value?") as usize;
        if self.frame_size > self.block_size || self.frame_size < libc::TPACKET3_HDRLEN {
            tracing::warn!("Frame size is out of range");
            return Err(ErrorKind::InvalidInput.into());
        }
        if self.block_size % page_size != 0 {
            tracing::warn!("Block size is not page-aligned");
            return Err(ErrorKind::InvalidInput.into());
        }
        if self.block_count == 0 {
            tracing::warn!("No blocks in ring");
            return Err(ErrorKind::InvalidInput.into());
        }

        let frames_per_block = self.block_size / self.frame_size;
        let Some(frame_count) = self.block_count.checked_mul(frames_per_block) else {
            tracing::warn!("Too many frames");
            return Err(ErrorKind::InvalidInput.into());
        };

        // We want them as usize, but the kernel would really like u32.
        let Ok(tp_block_size) = self.block_size.try_into() else {
            tracing::warn!("Block size is too large");
            return Err(ErrorKind::InvalidInput.into());
        };
        let Ok(tp_block_nr) = self.block_count.try_into() else {
            tracing::warn!("Block count is too large");
            return Err(ErrorKind::InvalidInput.into());
        };
        let Ok(tp_frame_size) = self.frame_size.try_into() else {
            tracing::warn!("Frame size is too large");
            return Err(ErrorKind::InvalidInput.into());
        };
        let Ok(tp_frame_nr) = frame_count.try_into() else {
            tracing::warn!("Frame count is too large");
            return Err(ErrorKind::InvalidInput.into());
        };
        let tp_retire_blk_tov: u32 = match self.rx_retire_timeout {
            Some(timeout) => match timeout.as_millis().try_into() {
                Ok(timeout) => timeout,
                Err(_) => {
                    tracing::warn!("Block retiry timeout is too large");
                    return Err(ErrorKind::InvalidInput.into())
                },
            },
            None => 0u32,
        };

        Ok(libc::tpacket_req3 {
            tp_block_size, tp_block_nr, tp_frame_size, tp_frame_nr, tp_retire_blk_tov,
            tp_sizeof_priv: 0,
            tp_feature_req_word: 0,
        })
    }
}

impl RingConfig {
    /// Total size of the mapped ring.
    pub fn ring_size(&self) -> Option<usize> {
        self.block_size.checked_mul(self.block_count)
    }

    /// Number of frames in each block.
    pub fn frames_per_block(&self) -> Option<usize> {
        self.block_size.checked_div(self.frame_size)
    }
}

/// A packet ring. Releases its memory on drop.
struct Ring {
    socket: Arc<OwnedFd>,
    memory: *mut libc::c_void,
    size: usize,
    config: RingConfig,
    addrs: AddressData,
}

impl Drop for Ring {
    fn drop(&mut self) {
        if let Some(addr) = NonNull::new(self.memory) {
            let _ = unsafe { mman::munmap(addr, self.size) }; // If this fails, we can't really do
                                                              // anything.
        }
    }
}

impl Ring {
    /// Creates a new `Ring`.
    ///
    /// # Safety
    ///
    /// `memory` must point to `size` bytes of mapped memory, corresponding to a ring with the
    /// specified properties.
    unsafe fn new(socket: Arc<OwnedFd>, memory: *mut libc::c_void, size: usize, config: RingConfig, addrs: AddressData) -> Self {
        Self { socket, memory, size, config, addrs }
    }
}

// SAFETY: The pointers in here are guaranteed to be pointers into the ring memory.
// The ring memory itself is owned by the ring object, and unmapped on destruction.
// The ring pointers never leak out of the object. Thus, sending the ring across thread boundaries
// is safe (but operating it from separate threads simultaneously is not).
unsafe impl Send for Ring {}

/// A receive ring.
pub struct RxRing(Ring);

impl Into<RxRing> for Ring {
    fn into(self) -> RxRing { RxRing(self) }
}

/// A transmit ring.
pub struct TxRing(Ring);

impl Into<TxRing> for Ring {
    fn into(self) -> TxRing { TxRing(self) }
}

/// A TPACKET_V3 packet socket (with receive and transmit rings).
pub struct PacketSocket {
    pub rx: RxRing,
    pub tx: TxRing,
}

impl PacketSocket {
    /// Attempts to create a new memory-mapped TPACKET_V3 packet socket.
    pub fn new(interface: &str, rx_config: RingConfig, tx_config: RingConfig) -> std::io::Result<Self> {
        // Retire timeout is only valid on receive rings.
        if tx_config.rx_retire_timeout.is_some() {
            return Err(ErrorKind::InvalidInput.into());
        }

        // Recieve code assumes that the blocks split nicely across frames
        if rx_config.block_size % rx_config.frame_size != 0 {
            return Err(ErrorKind::InvalidInput.into());
        }

        // Sanity check the ring sizes.
        let Some(rx_size) = rx_config.ring_size() else {
            return Err(ErrorKind::InvalidInput.into());
        };
        let Some(tx_size) = tx_config.ring_size() else {
            return Err(ErrorKind::InvalidInput.into());
        };

        // Need the TX size for the send buffer
        let Ok(send_buffer): Result<u32, _> = tx_size.try_into() else {
            return Err(ErrorKind::InvalidInput.into());
        };
        // ...and the total mapping size
        let Some(mapping_size) = rx_size.checked_add(tx_size).and_then(NonZero::new) else {
            return Err(ErrorKind::InvalidInput.into());
        };


        // Convert into packet requests.
        let rx_req: libc::tpacket_req3 = rx_config.clone().try_into()?;
        let tx_req: libc::tpacket_req3 = tx_config.clone().try_into()?;

        let ifindex = if_nametoindex(interface)? as i32; // Casting the c_uint into i32 is fine,
                                                           // since half the kernel APIs take this
                                                           // signed, and half take it unsigned.

        // Build the socket.
        let socket = socket::socket(
            AddressFamily::Packet,
            SockType::Raw,
            SockFlag::SOCK_CLOEXEC | SockFlag::SOCK_NONBLOCK,
            None
        )?;

        // Configure the socket. These socket options are not implemented in nix, so here we go.
        setsockopt(&socket, libc::SOL_PACKET, libc::PACKET_VERSION, &libc::tpacket_versions::TPACKET_V3)?;
        setsockopt(&socket, libc::SOL_PACKET, libc::PACKET_LOSS, &1i32)?;
        setsockopt(&socket, libc::SOL_PACKET, libc::PACKET_RX_RING, &rx_req)?;
        setsockopt(&socket, libc::SOL_PACKET, libc::PACKET_TX_RING, &tx_req)?;
        setsockopt(&socket, libc::SOL_SOCKET, libc::SO_SNDBUF, &send_buffer)?;
        setsockopt(&socket, libc::SOL_PACKET, libc::PACKET_ADD_MEMBERSHIP, &libc::packet_mreq {
            mr_ifindex: ifindex,
            mr_type: libc::PACKET_MR_PROMISC as u16,
            mr_alen: 0,
            mr_address: [0u8; 8],
        })?;

        // Bind the socket to our target interface.
        socket::bind(socket.as_raw_fd(), &link_addr_for_interface(ifindex)?)?;

        // Map the rings.
        let ring_memory = unsafe { mman::mmap(
            None,
            mapping_size,
            ProtFlags::PROT_READ | ProtFlags::PROT_WRITE,
            MapFlags::MAP_SHARED,
            &socket,
            0
        ) }?;

        // Get the MAC address of the interface
        let addrs = AddressData {
            mac: get_mac_address(socket.as_raw_fd(), interface)?
        };

        // Share the socket around.
        let socket = Arc::new(socket);

        // Split up the memory.
        let rx_ring = unsafe { Ring::new(socket.clone(), ring_memory.as_ptr(), rx_size, rx_config, addrs) };
        let tx_ring = unsafe { Ring::new(socket, ring_memory.byte_add(rx_size).as_ptr(), tx_size, tx_config, addrs) };

        Ok(Self { rx: rx_ring.into(), tx: tx_ring.into() })
    }
}


/// Determines whether the given `oneshot::Receiver` has received a closing signal.
fn should_terminate(rx: &mut oneshot::Receiver<()>) -> bool {
    match rx.try_recv() {
        Ok(()) | Err(oneshot::error::TryRecvError::Closed) => true,
        Err(oneshot::error::TryRecvError::Empty) => false,
    }
}


/// A receive ring yields packets. Since the packet needs to be shoveled into a longer-lived queue
/// immediately to not stall the ring, this inherently incurs a memcpy. But that should be fine.
impl RxRing {
    /// Runs the receive loop on a separate native thread.
    pub fn receive(self, map: ConnectionMapReader) -> (oneshot::Sender<()>, thread::JoinHandle<Result<(), Errno>>) {
        let (tx_terminate, rx_terminate) = oneshot::channel();
        let join_handle = thread::spawn(move || self.receive_thread(rx_terminate, map));
        (tx_terminate, join_handle)
    }

    /// Runs the receive loop.
    fn receive_thread(self, mut terminate: oneshot::Receiver<()>, map: ConnectionMapReader) -> Result<(), Errno> {
        let mut block_index = 0;
        let mut block = self.0.memory as *mut libc::tpacket_block_desc;
        while !should_terminate(&mut terminate) {
            // Wait for a block to become ready.
            let (status, mut frames, offset) = {
                let header = unsafe { &(*block).hdr.bh1 };
                (header.block_status, header.num_pkts, header.offset_to_first_pkt)
            };

            if status & libc::TP_STATUS_USER == 0 {
                let mut fds = [PollFd::new(self.0.socket.as_fd(),
                                           PollFlags::POLLERR | PollFlags::POLLIN)];
                tracing::trace!("Receive thread: polling on socket");
                if let Err(error) = poll::poll(&mut fds, PollTimeout::NONE) {
                    if error != Errno::EINTR {
                        return Err(error)
                    }
                }
                continue;
            }

            tracing::trace!("Receive thread: found {frames} frames in block {block_index}");
            let mut frame = unsafe { block.byte_add(offset as usize) as *mut libc::tpacket3_hdr };
            while frames > 0 {
                let captured_length = unsafe { (&*frame).tp_snaplen } as usize;
                let wire_length = unsafe { (&*frame).tp_len } as usize;
                if wire_length > captured_length {
                    tracing::trace!("Discarding truncated outbound packet (larger than MTU)");
                } else {
                    let macoff = unsafe { (&*frame).tp_mac } as usize;
                    let netoff = unsafe { (&*frame).tp_net } as usize;
                    let length = wire_length.saturating_sub(netoff.saturating_sub(macoff));

                    // Sanity-check the packet here. We don't want to do additional work on this
                    // thread, but the evmap lookup should be reasonably fast and save overall load.
                    // If we run into throughput trouble, we can revisit this decision.
                    if length >= 20 { // IPv4 packets are at least 20 bytes, IPv6 packets are at least
                                      // 40 bytes. Anything smaller we can discard immediately, without
                                      // even constructing the slice.
                        let ptr = unsafe { frame.byte_add(netoff) as *mut u8 };
                        let data = unsafe { std::slice::from_raw_parts(ptr, length) };

                        #[cfg(feature = "packet-trace")]
                        tracing::trace!("Received {:?}", Bytes::from_static(data));

                        // Grab the destination address
                        if let Some(destination) = data.destination_ip() {
                            tracing::trace!("Receive thread: received valid packet for {destination}");
                            if let Some(connection) = map.get_one(&destination) {
                                // We don't care if this fails. If the queue is gone, great, whatever.
                                // If the queue is full, too bad, drop the packet.
                                let _ = connection.outbound.try_send(Bytes::copy_from_slice(data));
                            }
                        }
                    }
                }

                frames -= 1;
                frame = unsafe { frame.byte_add((&*frame).tp_next_offset as usize) };
            }

            unsafe { (*block).hdr.bh1.block_status = libc::TP_STATUS_KERNEL };
            block_index = (block_index + 1) % self.0.config.block_count;
            block = unsafe {
                self.0.memory.byte_add(block_index * self.0.config.block_size)
                    as *mut libc::tpacket_block_desc
            };
        }
        tracing::trace!("Receive thread: shutting down");
        socket::shutdown(self.0.socket.as_raw_fd(), Shutdown::Read)
    }
}

/// A transmit ring pulls packets from a queue and tries to send them out as fast as possible.
impl TxRing {
    /// Runs the transmit loop on a separate native thread.
    pub fn transmit(self, queue: mpsc::Receiver<Bytes>, arp: ArpTableReader, arp_queue: mpsc::Sender<(IpAddr, Bytes)>) -> (oneshot::Sender<()>, thread::JoinHandle<Result<(), Errno>>) {
        let (tx_terminate, rx_terminate) = oneshot::channel();
        let tx_join_handle = thread::spawn(move || self.transmit_thread(rx_terminate, queue, arp, arp_queue));
        (tx_terminate, tx_join_handle)
    }

    /// Flushes pending packets.
    fn flush(&self, wait: bool) -> Result<(), Errno> {
        socket::send(
            self.0.socket.as_raw_fd(),
            &[],
            if wait { MsgFlags::empty() } else { MsgFlags::MSG_DONTWAIT }
        ).map(drop)
    }

    /// Runs the receive loop.
    fn transmit_thread(self, mut terminate: oneshot::Receiver<()>, mut queue: mpsc::Receiver<Bytes>, arp: ArpTableReader, arp_queue: mpsc::Sender<(IpAddr, Bytes)>) -> Result<(), Errno> {
        let mut frame = self.0.memory as *mut libc::tpacket3_hdr;
        let end = unsafe { self.0.memory.byte_add(self.0.size) } as *mut libc::tpacket3_hdr;

        let mut pending = 0usize;
        let pending_limit = self.0.config.frames_per_block().unwrap_or(1024);

        while !should_terminate(&mut terminate) {
            if pending >= pending_limit {
                tracing::trace!("Transmit thread: {pending} pending packets (and consistently busy), flushing socket");
                self.flush(false)?;
                pending = 0;
            }

            // Grab a packet. If none are available, flush the send buffer and wait.
            let packet = match queue.try_recv() {
                Ok(packet) => packet,
                Err(mpsc::error::TryRecvError::Disconnected) => break,
                Err(mpsc::error::TryRecvError::Empty) => {
                    if pending > 0 {
                        tracing::trace!("Transmit thread: {pending} pending packets (and none in queue), flushing socket");
                        self.flush(true)?;
                        pending = 0;
                    }
                    match queue.blocking_recv() {
                        Some(packet) => packet,
                        None => break,
                    }
                }
            };

            // Drop invalid packets early
            if packet.is_empty() || packet.len() > self.0.config.frame_size - libc::TPACKET3_HDRLEN - libc::ETH_HLEN as usize {
                tracing::trace!("Transmit thread: dropping empty or oversized packet ({} bytes)", packet.len());
                continue;
            }

            let Some(destination_ip) = packet.destination_ip() else {
                tracing::trace!("Transmit thread: dropping non-IP packet");
                continue;
            };

            let arp_table_entry = match arp.get_one(&destination_ip).map(|guard| *guard) {
                Some(entry) if entry.expires > Instant::now() => entry,
                _ => {
                    match arp_queue.try_send((destination_ip, packet)) {
                        Ok(()) => continue,
                        Err(TrySendError::Closed(_)) => break,
                        Err(TrySendError::Full(_)) => {
                            tracing::error!("Queue for ARP lookups is full, dropping packet");
                            continue;
                        },
                    }
                }
            };

            let destination_mac = &arp_table_entry.address;
            let header = match packet[0] >> 4 {
                4 => ethernet_header(destination_mac, &self.0.addrs.mac, libc::ETH_P_IP as u16),
                6 => ethernet_header(destination_mac, &self.0.addrs.mac, libc::ETH_P_IPV6 as u16),
                _ => unreachable!("Should not have gotten a valid destination for a non-IP packet"),
            };

            // Wait for an available frame.
            loop {
                let status = unsafe { (*frame).tp_status };
                if status & (libc::TP_STATUS_SEND_REQUEST | libc::TP_STATUS_SENDING) != 0 {
                    if pending > 0 {
                        tracing::trace!("Transmit thread: {pending} pending packets (and no space), flushing socket");
                        self.flush(false)?;
                        pending = 0;
                    } else {
                        let mut fds = [PollFd::new(self.0.socket.as_fd(),
                                                   PollFlags::POLLERR | PollFlags::POLLOUT)];
                        tracing::trace!("Transmit thread: polling on socket");
                        if let Err(error) = poll::poll(&mut fds, PollTimeout::NONE) {
                            if error != Errno::EINTR {
                                return Err(error)
                            }
                        }
                    }
                    continue;
                }

                // We know this fits because frame_size fits into u32 also, and we checked against frame_size above.
                let len = packet.len() as u32 + libc::ETH_HLEN as u32;

                let payload_start = unsafe {
                    frame.byte_add(libc::TPACKET3_HDRLEN - std::mem::size_of::<libc::sockaddr_ll>())
                        as *mut u8
                };

                let hdr = unsafe {
                    std::slice::from_raw_parts_mut(payload_start, libc::ETH_HLEN as usize)
                };
                let raw = unsafe {
                    std::slice::from_raw_parts_mut(
                        payload_start.byte_add(libc::ETH_HLEN as usize),
                        packet.len()
                    )
                };

                #[cfg(feature = "packet-trace")]
                tracing::trace!("Transmitting {packet:?}");

                unsafe {
                    hdr.copy_from_slice(&header);
                    (*frame).tp_len = len;
                    raw.copy_from_slice(&packet);
                    (*frame).tp_status = libc::TP_STATUS_SEND_REQUEST;
                }

                pending += 1;
                tracing::trace!("Transmit thread: submitted {len} bytes");
                frame = unsafe { frame.byte_add(self.0.config.frame_size) };
                if frame >= end {
                    frame = self.0.memory as *mut libc::tpacket3_hdr;
                }

                break;
            }
        }
        tracing::trace!("Transmit thread: shutting down");
        socket::shutdown(self.0.socket.as_raw_fd(), Shutdown::Write)
    }
}
