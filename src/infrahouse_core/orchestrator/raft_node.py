"""Module for OrchestratorRaftNode — wraps a single Orchestrator node's HTTP API via SSM."""

import json
from logging import getLogger

from cached_property import cached_property_with_ttl

from infrahouse_core.orchestrator.exceptions import IHRaftPeerError

LOG = getLogger(__name__)


class OrchestratorRaftNode:
    """Wraps the HTTP API of a single MySQL Orchestrator node.

    Commands are executed on the instance via SSM (``execute_command``),
    so the caller does not need direct network access to the Orchestrator
    HTTP port.

    A node may also represent a stale Raft peer whose EC2 instance no longer
    exists.  Use :meth:`from_peer_addr` to create such a node.  Stale nodes
    expose :attr:`hostname` and :attr:`peer_addr` but cannot execute API calls.

    :param instance: An ASG instance running Orchestrator, or ``None`` for stale peers.
    :type instance: infrahouse_core.aws.asg_instance.ASGInstance or None
    :param http_port: Orchestrator HTTP API port.
    :type http_port: int
    :param raft_port: Raft protocol port.
    :type raft_port: int
    """

    def __init__(self, instance=None, http_port=3000, raft_port=10008, hostname=None):
        self._instance = instance
        self._http_port = http_port
        self._raft_port = raft_port
        self._hostname = hostname

    @classmethod
    def from_peer_addr(cls, peer_addr):
        """Create a node from a Raft peer address string.

        Useful for representing stale peers that no longer have a live EC2
        instance.

        :param peer_addr: Raft peer address, e.g. ``"ip-10-1-100-195:10008"``.
        :type peer_addr: str
        :rtype: OrchestratorRaftNode
        """
        hostname, port_str = peer_addr.split(":")
        return cls(hostname=hostname, raft_port=int(port_str))

    @property
    def private_ip(self):
        """Return the private IP address of the underlying EC2 instance.

        :raises AttributeError: If the node has no live instance (stale peer).
        """
        return self._instance.private_ip

    @property
    def hostname(self):
        """Return the short private hostname of the underlying EC2 instance.

        This is what Orchestrator uses as the Raft node identifier,
        e.g. ``"ip-10-1-100-195"``.
        """
        if self._hostname is not None:
            return self._hostname
        return self._instance.hostname

    @property
    def instance(self):
        """Return the underlying ASGInstance, or ``None`` for stale peers."""
        return self._instance

    @property
    def peer_addr(self):
        """Return the Raft peer address for this node in ``hostname:raft_port`` form.

        :rtype: str
        """
        return f"{self.hostname}:{self._raft_port}"

    @cached_property_with_ttl(ttl=10)
    def raft_peers(self):
        """Retrieve the current Raft peer list from this node.

        :return: List of peer addresses, e.g. ``["ip-10-1-100-195:10008", ...]``.
        :rtype: list[str]
        :raises IHRaftPeerError: If the command fails.
        """
        return self._api_get("/api/raft-peers")

    @cached_property_with_ttl(ttl=10)
    def raft_leader(self):
        """Retrieve the current Raft leader address as seen by this node.

        :return: Leader address (``"hostname:raft_port"``), or ``None`` if no leader
            is currently elected.
        :rtype: str or None
        :raises IHRaftPeerError: If the command fails.
        """
        leader = self._api_get("/api/raft-leader")
        if not leader or leader == "nil":
            return None
        return leader

    @cached_property_with_ttl(ttl=10)
    def raft_health(self):
        """Retrieve the Raft health status from this node.

        :return: Raft health payload as returned by Orchestrator.
        :rtype: dict
        :raises IHRaftPeerError: If the command fails.
        """
        return self._api_get("/api/raft-health")

    @property
    def is_leader(self):
        """Return ``True`` if this node believes itself to be the Raft leader.

        :rtype: bool
        """
        return self.raft_leader == self.peer_addr  # pylint: disable=comparison-with-callable

    def add_peer(self, peer):
        """Add a peer to this node's Raft cluster.

        :param peer: The node to add.
        :type peer: OrchestratorRaftNode
        :raises IHRaftPeerError: If Orchestrator reports a failure.
        """
        addr = peer.peer_addr
        LOG.info("Adding Raft peer %s via %s", addr, self.hostname)
        result = self._api_get(f"/api/raft-add-peer/{addr}")
        self._check_raft_response(result, f"add peer {addr}")

    def remove_peer(self, peer):
        """Remove a peer from this node's Raft cluster.

        :param peer: The node to remove.
        :type peer: OrchestratorRaftNode
        :raises IHRaftPeerError: If Orchestrator reports a failure.
        """
        addr = peer.peer_addr
        LOG.info("Removing Raft peer %s via %s", addr, self.hostname)
        result = self._api_get(f"/api/raft-remove-peer/{addr}")
        self._check_raft_response(result, f"remove peer {addr}")

    def _api_get(self, path):
        """Run ``curl`` on the instance via SSM and return the parsed JSON response.

        :param path: API path, e.g. ``"/api/raft-peers"``.
        :type path: str
        :return: Parsed JSON response.
        :raises IHRaftPeerError: If the curl command fails (non-zero exit code).
        """
        url = f"http://localhost:{self._http_port}{path}"
        exit_code, stdout, stderr = self._instance.execute_command(f"curl -sf {url}")
        if exit_code != 0:
            raise IHRaftPeerError(f"curl {url} on {self.hostname} failed (exit {exit_code}): {stderr}")
        return json.loads(stdout)

    @staticmethod
    def _check_raft_response(result, operation):
        """Inspect the parsed Orchestrator response for application-level errors.

        Orchestrator returns HTTP 200 even when the operation failed; the
        ``Code`` field in the body signals success or failure.

        :raises IHRaftPeerError: If ``result["Code"]`` equals ``"ERROR"``.
        """
        if isinstance(result, dict) and result.get("Code") == "ERROR":
            message = result.get("Message", "unknown error")
            raise IHRaftPeerError(f"Orchestrator {operation} failed: {message}")
