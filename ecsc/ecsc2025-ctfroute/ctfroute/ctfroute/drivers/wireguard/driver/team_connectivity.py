from logging import getLogger
from typing import NamedTuple, Optional

from pyroute2 import NDB, WireGuard
from pyroute2.netlink.generic.wireguard import wgmsg

from ctfroute.drivers.base import TeamConnectivityDriver
from ctfroute.drivers.exceptions import BadState, InsufficientState
from ctfroute.drivers.utils import get_team_ifname
from ctfroute.drivers.wireguard.state import (
    WireGuardPeer,
    WireGuardTeamConnectivity,
)
from ctfroute.state.internal import Team

LOGGER = getLogger()


class Peer(NamedTuple):
    public_key: str
    allowed_ips: str

    @classmethod
    def from_wg_peer(cls, peer: WireGuardPeer) -> "Peer":
        """
        Create a Peer from a WireGuardPeer.

        Args:
            peer: The WireGuardPeer

        Returns:
            The created Peer
        """
        return cls(public_key=peer.public_key, allowed_ips=str(peer.allowed_ips))


class WireguardTeamConnectivityDriver(TeamConnectivityDriver):
    """Manages the WireGuard interfaces for the teams."""

    name = "wireguard"
    ndb_factory = NDB
    wg_factory = WireGuard

    async def sync(self, team: Team) -> str:
        """
        Synchronize the WireGuard interface for the team.

        This method creates the interface (if it does not exist), ensures the private key is set,
        removes any extra peers, and adds any missing peers.

        Args:
            team: The team to sync its interface with

        Returns:
            The name of the synchronized interface

        Raises:
            BadState: If the teams driver is of the wrong type
            InsufficientState: If the state lacks critical information
            NetlinkError: If the WireGuard interface could not be created
        """
        connectivity = team.connectivity
        if not isinstance(connectivity, WireGuardTeamConnectivity):
            raise BadState(
                f"{self.__class__.__name__} can only handle {WireGuardTeamConnectivity.__name__}"
            )

        # We check the data here and then assert that it is complete and sane in
        # downstream code. This avoids opening netlink sockets and later realizing that
        # we can't go through with the operation.
        # Doing this check here is unproblematic, because despite this function being
        # declared async everything it does is synchronous. If we ever start doing async
        # here, we should copy the team and implement locking to avoid concurrent calls
        # to sync for the same team.
        if team.network is None or team.gateway is None:
            raise InsufficientState(f"Team {team.id} has no network or gateway.")

        LOGGER.info(f"Syncing WireGuard interface for team {team.id}")
        ifname = get_team_ifname(team.id)

        with self.wg_factory() as wg, self.ndb_factory() as ndb:
            if ifname not in ndb.interfaces:
                self._create_interface(
                    ndb=ndb,
                    wg=wg,
                    ifname=ifname,
                    team=team,
                    listen_port=connectivity.port,
                )

            current_key, existing_peers = self._gather_interface_info(wg, ifname)

            self._update_key(wg, current_key, connectivity.private_key, ifname)

            self._update_peers(wg, existing_peers, connectivity.peers, ifname)

            self._verify_peer_sync(wg, connectivity.peers, ifname)
        return ifname

    async def teardown(self, team: Team) -> None:
        """
        Tear a teams interface down.

        Args:
            team: The team to tear the interface down
        """
        with self.ndb_factory() as ndb:
            ifname = get_team_ifname(team.id)
            if ifname in ndb.interfaces:
                LOGGER.info(f"Deleting WireGuard interface {ifname}")
                with ndb.interfaces[ifname] as link:
                    link.set(state="down")
                    link.remove()

    @staticmethod
    def _recover_peers(sub_info: wgmsg) -> set[Peer]:
        recovered_peers: set[Peer] = set()
        peer_info = sub_info.get("WGDEVICE_A_PEERS")
        if peer_info is None:
            return recovered_peers
        for peers in peer_info:
            for i in range(len(peers)):  # Not directly iterable!
                peer = peers[i]
                allowed_ips = peer.get("WGPEER_A_ALLOWEDIPS")
                try:
                    recovered_peers.add(
                        Peer(
                            public_key=peer.get("WGPEER_A_PUBLIC_KEY").decode(),
                            allowed_ips=allowed_ips[0]["addr"],
                        )
                    )
                except (KeyError, IndexError):
                    LOGGER.warning(
                        # FIXME: Ifname interpolation
                        "Invalid peer for {ifname}. allowed_ips={allowed_ips}"
                    )
        return recovered_peers

    def _create_interface(
        self, ndb: NDB, wg: WireGuard, ifname: str, team: Team, listen_port: int
    ) -> None:
        # Needs to be checked by caller
        assert team.network is not None
        assert team.gateway is not None

        """Create a WireGuard interface for a team."""
        LOGGER.info("Creating WireGuard interface {ifname}")

        network_prefix_len = team.network.prefixlen
        with ndb.interfaces.create(kind="wireguard", ifname=ifname) as link:
            link.add_ip(f"{team.gateway}/{network_prefix_len}")
            link.set(state="up")
            link.set(mtu=self.mtu)
        wg.set(interface=ifname, listen_port=listen_port)

    def _gather_interface_info(
        self,
        wg: WireGuard,
        ifname: str,
    ) -> tuple[Optional[bytes], set[Peer]]:
        current_key = None
        existing_peers = set()
        for sub_info in wg.info(ifname):
            if current_key is None:
                current_key = sub_info.get("WGDEVICE_A_PRIVATE_KEY")
            existing_peers |= self._recover_peers(sub_info)
        return current_key, existing_peers

    def _update_key(
        self, wg: WireGuard, current_key: Optional[bytes], private_key: str, ifname: str
    ) -> None:
        if current_key is None or current_key.decode() != private_key:
            LOGGER.info(f"Setting private key for {ifname}")
            wg.set(interface=ifname, private_key=private_key)

    def _update_peers(
        self,
        wg: WireGuard,
        existing_peers: set[Peer],
        peers: list[WireGuardPeer],
        ifname: str,
    ) -> None:
        configured_peers = set(Peer.from_wg_peer(p) for p in peers)
        # Remove superfluous peers
        for peer in existing_peers - configured_peers:
            peer_config = {"public_key": peer.public_key, "remove": True}
            try:
                wg.set(ifname, peer=peer_config)
            except ValueError:
                LOGGER.exception(f"Failed to remove peer {peer} on interface {ifname}")

        # Add missing peers
        for peer in configured_peers - existing_peers:
            peer_config = {
                "public_key": peer.public_key,
                "allowed_ips": [str(peer.allowed_ips)],
                "persistent_keepalive": 1,
            }
            try:
                wg.set(ifname, peer=peer_config)
            except ValueError:
                LOGGER.exception(f"Failed to add peer {peer} on interface {ifname}")

    def _verify_peer_sync(
        self, wg: WireGuard, peers: list[WireGuardPeer], ifname: str
    ) -> None:
        updated_peers = set()
        for sub_info in wg.info(ifname):
            updated_peers |= self._recover_peers(sub_info)

        if updated_peers != set(Peer.from_wg_peer(p) for p in peers):
            LOGGER.error(f"Peer mismatch after sync on {ifname}")
