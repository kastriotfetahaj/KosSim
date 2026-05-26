use bytes::Bytes;
use crate::filter::packet::Packet;
use evmap::{shallow_copy::CopyValue, ReadHandle, WriteHandle};
use futures::stream::TryStreamExt;
use nix::{errno::Errno, ioctl_read_bad, sys::socket::{self, AddressFamily, MsgFlags, SockFlag, SockProtocol, SockType, SockaddrIn, SockaddrIn6}};
use rtnetlink::{packet_route::neighbour::{NeighbourAddress, NeighbourAttribute, NeighbourState}, Handle, IpVersion};
use std::{hash::RandomState, net::{IpAddr, SocketAddrV4, SocketAddrV6}, os::fd::AsRawFd, thread, time::{Duration, Instant}};
use tokio::sync::{mpsc::{self, error::TrySendError, Receiver, WeakSender}, oneshot};

// Raw ioctl wrapper to get the hardware address of an interface.
ioctl_read_bad!(get_hw_address, libc::SIOCGIFHWADDR, libc::ifreq);

/// Size of the fallback queue.
const FALLBACK_QUEUE_SIZE: usize = 1024;

/// Lifetime of the ARP table entries.
const ARP_TABLE_ENTRY_LIFETIME: Duration = Duration::from_secs(30);

/// A MAC address is six bytes.
pub(crate) type MacAddress = [u8; libc::ETH_ALEN as usize];

trait MacAddressExt {
    fn to_string(&self) -> String;
}
impl MacAddressExt for MacAddress {
    fn to_string(&self) -> String {
        format!("{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}", self[0], self[1], self[2], self[3], self[4], self[5])
    }
}

/// Returns the MAC address of an interface.
pub(crate) fn get_mac_address(any_socket_fd: i32, interface: &str) -> nix::Result<MacAddress> {
    let bytes = interface.as_bytes();
    if bytes.len() > libc::IFNAMSIZ as usize {
        return Err(Errno::from_raw(libc::ENODEV));
    }
    let bytes = unsafe { // Ugh.
        std::slice::from_raw_parts(
            bytes.as_ptr() as *const i8,
            bytes.len()
        )
    };

    let mut ifr = unsafe { std::mem::zeroed::<libc::ifreq>() };
    (&mut ifr.ifr_name[..bytes.len()]).copy_from_slice(bytes);
    unsafe { get_hw_address(any_socket_fd, &mut ifr as *mut libc::ifreq) }?;

    let sockaddr = unsafe { ifr.ifr_ifru.ifru_hwaddr };
    if sockaddr.sa_family != libc::ARPHRD_ETHER {
        // Can't forward on a non-Ethernet device
        tracing::error!("{} has unsupported hardware address type {}", interface, sockaddr.sa_family);
        Err(Errno::from_raw(libc::ESOCKTNOSUPPORT))
    } else {
        Ok([
            sockaddr.sa_data[0] as u8,
            sockaddr.sa_data[1] as u8,
            sockaddr.sa_data[2] as u8,
            sockaddr.sa_data[3] as u8,
            sockaddr.sa_data[4] as u8,
            sockaddr.sa_data[5] as u8,
        ])
    }
}

/// An ARP table entry.
#[derive(Copy, Clone, Debug, Eq, Hash, PartialEq)]
pub(crate) struct ArpTableEntry {
    pub address: MacAddress,
    pub expires: Instant,
}

/// The neighbor/ARP table.
pub(crate) type ArpTableReader = ReadHandle<IpAddr, CopyValue<ArpTableEntry>, (), RandomState>;
pub(crate) type ArpTableWriter = WriteHandle<IpAddr, CopyValue<ArpTableEntry>, (), RandomState>;

/// Checks the system neighbor table for a specific neighbor.
async fn query_neigh_table(destination: IpAddr, handle: &Handle) -> Result<Option<MacAddress>, rtnetlink::Error> {
    let (version, addr) = match destination {
        IpAddr::V4(addr) => (IpVersion::V4, NeighbourAddress::Inet(addr)),
        IpAddr::V6(addr) => (IpVersion::V6, NeighbourAddress::Inet6(addr)),
    };
    let mut req = handle.neighbours().get().set_family(version);
    req.message_mut().attributes.push(NeighbourAttribute::Destination(addr));
    let mut neighs = req.execute();
    'next_entry: while let Some(entry) = neighs.try_next().await? {
        if entry.header.state != NeighbourState::Reachable &&
           entry.header.state != NeighbourState::Permanent {
            continue;
        }
        let mut lladdr = None;
        let mut matched = false;
        for nla in entry.attributes.into_iter() {
            match nla {
                NeighbourAttribute::Destination(value) => {
                    let ip = match value {
                        NeighbourAddress::Inet(ipv4) => IpAddr::V4(ipv4),
                        NeighbourAddress::Inet6(ipv6) => IpAddr::V6(ipv6),
                        _ => continue 'next_entry,
                    };
                    if ip != destination {
                        continue 'next_entry;
                    }
                    matched = true;
                },
                NeighbourAttribute::LinkLocalAddress(value) => {
                    if value.len() != libc::ETH_ALEN as usize {
                        tracing::debug!("Neighbor lookup: ignoring unknown address type of length {}", value.len());
                    } else {
                        lladdr = Some(value);
                    }
                },
                _ => continue,
            }
            if matched && lladdr.is_some() {
                break;
            }
        }
        if !matched {
            tracing::debug!("Neighbor lookup: ignoring entry without destination information");
        } else if let Some(lladdr) = lladdr {
            return Ok(Some([lladdr[0], lladdr[1], lladdr[2], lladdr[3], lladdr[4], lladdr[5]]));
        } else {
            tracing::debug!("Neighbor lookup: ignoring entry without MAC address");
        }
    }
    Ok(None)
}

/// Performs an address lookup
async fn system_lookup(destination: IpAddr, handle: &Handle) -> Option<MacAddress> {
    // Look up in the neighbor cache first. This is more expensive for non-cached entries, but
    // we should only ever do this once per neighbor anyways.
    match query_neigh_table(destination, handle).await {
        Err(error) => {
            tracing::error!("Neighbor lookup: failed for {destination}: {error}");
            None
        },
        Ok(result) => result,
    }
}

/// Resubmits a packet after lookup.
async fn resubmit(packet: Bytes, submit: &WeakSender<Bytes>) -> Result<(), ()> {
    if let Some(queue) = submit.upgrade() {
        match queue.try_send(packet) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => {
                tracing::warn!("Neighbor lookup: dropping packet (send queue is full)");
                Ok(())
            },
            Err(TrySendError::Closed(_)) => Err(()),
        }
    } else {
        Err(())
    }
}

/// Fallback packet submission if ARP lookup fails.
fn fallback(mut queue: Receiver<Bytes>, ready: oneshot::Sender<()>) -> std::io::Result<()> {
    let make_raw_socket = |af| socket::socket(af, SockType::Raw,
                                              SockFlag::SOCK_CLOEXEC | SockFlag::SOCK_NONBLOCK,
                                              Some(SockProtocol::Raw));
    let socket_v4 = make_raw_socket(AddressFamily::Inet)?;
    let socket_v6 = make_raw_socket(AddressFamily::Inet6)?;
    ready.send(()).map_err(|_| std::io::Error::other("Failed to signal that ARP lookup is ready"))?;

    while let Some(packet) = queue.blocking_recv() {
        if let Err(error) = match packet.destination_ip() {
            Some(IpAddr::V4(ip)) => {
                let addr: SockaddrIn = SocketAddrV4::new(ip, 0).into();
                socket::sendto(socket_v4.as_raw_fd(), &packet, &addr, MsgFlags::MSG_DONTWAIT)
            },
            Some(IpAddr::V6(ip)) => {
                let addr: SockaddrIn6 = SocketAddrV6::new(ip, 0, 0, 0).into();
                socket::sendto(socket_v6.as_raw_fd(), &packet, &addr, MsgFlags::MSG_DONTWAIT)
            },
            None => continue, // We should never get here.
        } {
            tracing::debug!("Neighbor lookup: Fallback path failed to forward packet: {error}");
        }
    }

    Ok(())
}

/// Looks up IP addresses and resubmits the packet once it has a match.
pub(crate) async fn lookup(mut queue: Receiver<(IpAddr, Bytes)>, submit: WeakSender<Bytes>, reader: ArpTableReader, mut table: ArpTableWriter, ready: oneshot::Sender<()>) -> std::io::Result<()> {
    let (connection, handle, _) = rtnetlink::new_connection()?;
    tokio::spawn(connection);

    let (fallback_tx, fallback_rx) = mpsc::channel(FALLBACK_QUEUE_SIZE);
    let fallback_join = thread::spawn(move || {
        if let Err(error) = fallback(fallback_rx, ready) {
            tracing::error!("Neighbor lookup: Unhandled error in fallback path: {error}");
        }
    });

    while let Some((destination, packet)) = queue.recv().await {
        match reader.get_one(&destination) {
            Some(entry) if entry.expires > Instant::now() => {
                // Short-circuit in case of race.
                if resubmit(packet, &submit).await.is_err() {
                    break;
                }
                continue;
            },
            Some(entry) => {
                tracing::debug!("Neighbor lookup: entry for {} (resolving to {}) has expired",
                                destination, entry.address.to_string());
            },
            _ => {
                tracing::debug!("Neighbor lookup: no entry for {}", destination);
            },
        }
        // No entry, or the entry is stale.
        if let Some(mac) = system_lookup(destination, &handle).await {
            // Got a MAC address for this destination from the system table.
            tracing::debug!("Neighbor lookup: resolved {} to {}", destination, mac.to_string());
            let entry = ArpTableEntry {
                address: mac,
                expires: Instant::now() + ARP_TABLE_ENTRY_LIFETIME,
            };
            table.update(destination, entry.into());
            table.refresh();
            if resubmit(packet, &submit).await.is_err() {
                break;
            }
        } else {
            // Use the fallback socket to force the kernel to do the lookup.
            tracing::debug!("Neighbor lookup: failed to resolve {destination}, using fallback");
            if let Err(error) = fallback_tx.try_send(packet) {
                tracing::warn!("Neighbor lookup: failed to submit packet for {destination} to fallback socket: {error}");
            }
        }
    }

    if let Err(_) = tokio::task::spawn_blocking(move || {
        if let Err(_) = fallback_join.join() { tracing::error!("Fallback thread panicked"); }
    }).await {
        tracing::warn!("Failed to wait for fallback thread");
    }

    Ok(())
}
