"""Module for OrchestratorRaftCluster — ties Raft membership to an ASG."""

from logging import getLogger

from infrahouse_core.aws.asg import ASG
from infrahouse_core.orchestrator.exceptions import (
    IHRaftLeaderNotFound,
    IHRaftPeerError,
)
from infrahouse_core.orchestrator.raft_node import OrchestratorRaftNode

LOG = getLogger(__name__)


class OrchestratorRaftCluster:
    """Ties MySQL Orchestrator Raft membership to an AWS Auto Scaling Group.

    Creates one :class:`OrchestratorRaftNode` per live ASG instance and
    provides methods to add/remove peers and reconcile the full Raft peer
    list against the live ASG membership.

    Commands are executed on instances via SSM, so the caller does not need
    direct network access to the Orchestrator HTTP port.

    :param asg_name: Name of the Auto Scaling Group running Orchestrator.
    :type asg_name: str
    :param region: AWS region.
    :type region: str
    :param role_arn: IAM role ARN for cross-account access.
    :type role_arn: str
    :param session: Pre-configured ``boto3.Session``.
    :param http_port: Orchestrator HTTP API port.
    :type http_port: int
    :param raft_port: Raft protocol port.
    :type raft_port: int
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        asg_name,
        region=None,
        role_arn=None,
        session=None,
        http_port=3000,
        raft_port=10008,
    ):
        self._asg_name = asg_name
        self._region = region
        self._role_arn = role_arn
        self._session = session
        self._http_port = http_port
        self._raft_port = raft_port
        self._asg_instance = None

    @property
    def _asg(self):
        """Lazily create and return the underlying :class:`ASG` instance."""
        if self._asg_instance is None:
            self._asg_instance = ASG(
                self._asg_name,
                region=self._region,
                role_arn=self._role_arn,
                session=self._session,
            )
        return self._asg_instance

    @property
    def nodes(self):
        """Return an :class:`OrchestratorRaftNode` for each live ASG instance.

        :rtype: list[OrchestratorRaftNode]
        """
        return [
            OrchestratorRaftNode(
                instance,
                http_port=self._http_port,
                raft_port=self._raft_port,
            )
            for instance in self._asg.instances
        ]

    def _node_lookup(self, nodes):
        """Build a dict mapping both private_ip and hostname to each node.

        Raft may identify peers by IP address (e.g. ``"10.1.100.195"``) or by
        short hostname (e.g. ``"ip-10-1-100-195"``).  This lookup supports both.

        :rtype: dict[str, OrchestratorRaftNode]
        """
        lookup = {}
        for node in nodes:
            ip = node.private_ip
            if ip is not None:
                lookup[ip] = node
            lookup[node.hostname] = node
        return lookup

    @property
    def leader(self):
        """Return the :class:`OrchestratorRaftNode` that is the current Raft leader.

        Queries each live ASG instance until one responds with a non-nil leader.
        All mutation operations (add/remove peer) should be sent to the leader.

        :rtype: OrchestratorRaftNode
        :raises IHRaftLeaderNotFound: If no node reports a leader.
        """
        nodes = self.nodes
        lookup = self._node_lookup(nodes)
        for node in nodes:
            try:
                leader_addr = node.raft_leader
            except IHRaftPeerError:
                LOG.warning("Could not reach node %s, skipping.", node.hostname)
                continue
            if leader_addr is not None:
                leader_host = leader_addr.split(":")[0]
                candidate = lookup.get(leader_host)
                if candidate is not None:
                    LOG.info("Found Raft leader at %s", leader_host)
                    return candidate
                LOG.warning(
                    "Leader %s is not in the current ASG instance list.",
                    leader_addr,
                )
        raise IHRaftLeaderNotFound(f"No Raft leader found among ASG instances for {self._asg_name}")

    @property
    def peers(self):
        """Return the current Raft peer list from the leader as node objects.

        Live ASG instances are returned as full nodes; stale peers (terminated
        instances no longer in the ASG) are returned as instance-less nodes
        created via :meth:`OrchestratorRaftNode.from_peer_addr`.

        :rtype: list[OrchestratorRaftNode]
        """
        lookup = self._node_lookup(self.nodes)
        return [
            lookup.get(addr.split(":")[0], OrchestratorRaftNode.from_peer_addr(addr)) for addr in self.leader.raft_peers
        ]

    def add_peer(self, node):
        """Add a peer to the Raft cluster.

        :param node: The node to add.
        :type node: OrchestratorRaftNode
        :raises IHRaftLeaderNotFound: If no leader is reachable.
        :raises IHRaftPeerError: If the add operation fails.
        """
        self.leader.add_peer(node)

    def remove_peer(self, node):
        """Remove a peer from the Raft cluster.

        :param node: The node to remove.
        :type node: OrchestratorRaftNode
        :raises IHRaftLeaderNotFound: If no leader is reachable.
        :raises IHRaftPeerError: If the remove operation fails.
        """
        self.leader.remove_peer(node)

    def reconcile(self):
        """Reconcile the Raft peer list against the live ASG membership.

        1. Collect the hostnames of all currently live ASG instances.
        2. Collect the hostnames from the leader's Raft peer list.
        3. Remove stale peers (in Raft but not in ASG) by their Raft address.
        4. Add missing peers (in ASG but not in Raft) via their node objects.

        :raises IHRaftLeaderNotFound: If no leader is reachable.
        :raises IHRaftPeerError: If any add or remove operation fails.
        """
        leader = self.leader
        LOG.info("Reconciling Raft peers via leader %s", leader.hostname)

        live_nodes = self.nodes
        LOG.debug("Live ASG instances: %s", [node.hostname for node in live_nodes])

        # Build a map of raft host -> stale node for peers not in the ASG
        raft_peer_addrs = {}
        for addr in leader.raft_peers:
            host = addr.split(":")[0]
            raft_peer_addrs[host] = OrchestratorRaftNode.from_peer_addr(addr)
        LOG.debug("Current Raft peer hosts: %s", set(raft_peer_addrs))

        stale_hosts = (
            set(raft_peer_addrs) - {node.private_ip for node in live_nodes} - {node.hostname for node in live_nodes}
        )
        missing_nodes = [
            node
            for node in live_nodes
            if node.private_ip not in raft_peer_addrs and node.hostname not in raft_peer_addrs
        ]

        for host in stale_hosts:
            LOG.info("Removing stale Raft peer %s", host)
            self.remove_peer(raft_peer_addrs[host])

        for node in missing_nodes:
            LOG.info("Adding missing Raft peer %s", node.hostname)
            self.add_peer(node)

        LOG.info("Raft reconcile complete: removed=%d added=%d", len(stale_hosts), len(missing_nodes))
