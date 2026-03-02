"""Tests for OrchestratorRaftCluster."""

from unittest import mock

import pytest

from infrahouse_core.aws.asg import ASG
from infrahouse_core.orchestrator.exceptions import (
    IHRaftLeaderNotFound,
    IHRaftPeerError,
)
from infrahouse_core.orchestrator.raft_cluster import OrchestratorRaftCluster
from infrahouse_core.orchestrator.raft_node import OrchestratorRaftNode


def _mock_asg_instance(private_ip, hostname):
    """Helper to create a mock ASGInstance."""
    inst = mock.MagicMock()
    inst.private_ip = private_ip
    inst.hostname = hostname
    return inst


def test_nodes_from_asg():
    """nodes creates an OrchestratorRaftNode per ASG instance."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    instances = [
        _mock_asg_instance("10.1.1.1", "ip-10-1-1-1"),
        _mock_asg_instance("10.1.1.2", "ip-10-1-1-2"),
    ]
    with mock.patch.object(OrchestratorRaftCluster, "_asg", new_callable=mock.PropertyMock) as mock_asg:
        mock_asg.return_value.instances = instances
        nodes = cluster.nodes
        assert len(nodes) == 2
        assert nodes[0].hostname == "ip-10-1-1-1"
        assert nodes[1].hostname == "ip-10-1-1-2"
        # Each node wraps the original ASGInstance
        assert nodes[0].instance is instances[0]
        assert nodes[1].instance is instances[1]


def test_leader_found():
    """leader returns the node that is the Raft leader."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node1.raft_leader = "ip-10-1-1-2:10008"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    node2.raft_leader = "ip-10-1-1-2:10008"
    with mock.patch.object(
        OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
    ):
        leader = cluster.leader
        assert leader.hostname == "ip-10-1-1-2"


def test_leader_not_found():
    """leader raises IHRaftLeaderNotFound when no node reports a leader."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node1.raft_leader = None
    with mock.patch.object(OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1]):
        with pytest.raises(IHRaftLeaderNotFound):
            _ = cluster.leader


def test_leader_skips_unreachable():
    """leader skips nodes that raise exceptions."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    type(node1).raft_leader = mock.PropertyMock(side_effect=IHRaftPeerError("curl failed"))
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    node2.raft_leader = "ip-10-1-1-2:10008"
    with mock.patch.object(
        OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
    ):
        leader = cluster.leader
        assert leader.hostname == "ip-10-1-1-2"


def test_leader_not_in_asg():
    """leader raises IHRaftLeaderNotFound when leader hostname is not in ASG."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node1.raft_leader = "ip-10-1-1-99:10008"
    with mock.patch.object(OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1]):
        with pytest.raises(IHRaftLeaderNotFound):
            _ = cluster.leader


def test_peers_returns_nodes():
    """peers returns OrchestratorRaftNode objects."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
        ),
    ):
        peers = cluster.peers
        assert len(peers) == 2
        # Live nodes are returned as-is
        assert peers[0] is node1
        assert peers[1] is node2


def test_peers_includes_stale():
    """peers returns instance-less nodes for stale Raft peers."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-99:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1]),
    ):
        peers = cluster.peers
        assert len(peers) == 2
        assert peers[0] is node1
        # Stale peer is a real OrchestratorRaftNode with no instance
        assert isinstance(peers[1], OrchestratorRaftNode)
        assert peers[1].hostname == "ip-10-1-1-99"
        assert peers[1].peer_addr == "ip-10-1-1-99:10008"
        assert peers[1].instance is None


def test_add_peer():
    """add_peer delegates to the leader with the node object."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1", raft_port=10008)
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    node = mock.MagicMock(spec=OrchestratorRaftNode)
    node.peer_addr = "ip-10-1-1-3:10008"
    with mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader):
        cluster.add_peer(node)
        mock_leader.add_peer.assert_called_once_with(node)


def test_remove_peer():
    """remove_peer delegates to the leader with the node object."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1", raft_port=10008)
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    node = mock.MagicMock(spec=OrchestratorRaftNode)
    node.peer_addr = "ip-10-1-1-3:10008"
    with mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader):
        cluster.remove_peer(node)
        mock_leader.remove_peer.assert_called_once_with(node)


def test_reconcile_removes_stale():
    """reconcile removes peers not in the ASG."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008", "ip-10-1-1-3:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
        ),
    ):
        cluster.reconcile()
    mock_leader.remove_peer.assert_called_once()
    removed_node = mock_leader.remove_peer.call_args[0][0]
    assert isinstance(removed_node, OrchestratorRaftNode)
    assert removed_node.peer_addr == "ip-10-1-1-3:10008"
    mock_leader.add_peer.assert_not_called()


def test_reconcile_adds_missing():
    """reconcile adds ASG instances not in the peer list."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    node3 = mock.MagicMock(spec=OrchestratorRaftNode)
    node3.hostname = "ip-10-1-1-3"
    node3.peer_addr = "ip-10-1-1-3:10008"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2, node3]
        ),
    ):
        cluster.reconcile()
    mock_leader.add_peer.assert_called_once_with(node3)
    mock_leader.remove_peer.assert_not_called()


def test_reconcile_no_changes():
    """reconcile does nothing when ASG and Raft peers match."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
        ),
    ):
        cluster.reconcile()
    mock_leader.add_peer.assert_not_called()
    mock_leader.remove_peer.assert_not_called()


def test_reconcile_both_stale_and_missing():
    """reconcile handles simultaneous stale and missing peers."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node3 = mock.MagicMock(spec=OrchestratorRaftNode)
    node3.hostname = "ip-10-1-1-3"
    node3.peer_addr = "ip-10-1-1-3:10008"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node3]
        ),
    ):
        cluster.reconcile()
    mock_leader.remove_peer.assert_called_once()
    removed_node = mock_leader.remove_peer.call_args[0][0]
    assert isinstance(removed_node, OrchestratorRaftNode)
    assert removed_node.peer_addr == "ip-10-1-1-2:10008"
    mock_leader.add_peer.assert_called_once_with(node3)


def test_reconcile_raises_on_remove_error():
    """reconcile propagates IHRaftPeerError from remove_peer."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008"]
    mock_leader.remove_peer.side_effect = IHRaftPeerError("failed")
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1]),
    ):
        with pytest.raises(IHRaftPeerError):
            cluster.reconcile()


def test_leader_found_by_ip():
    """leader matches when Raft returns IP addresses instead of hostnames (issue #105)."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node1.private_ip = "10.1.1.1"
    node1.raft_leader = "10.1.1.2:10008"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    node2.private_ip = "10.1.1.2"
    node2.raft_leader = "10.1.1.2:10008"
    with mock.patch.object(
        OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
    ):
        leader = cluster.leader
        assert leader.hostname == "ip-10-1-1-2"


def test_peers_returns_nodes_by_ip():
    """peers matches live nodes when Raft uses IP addresses (issue #105)."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["10.1.1.1:10008", "10.1.1.2:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node1.private_ip = "10.1.1.1"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    node2.private_ip = "10.1.1.2"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2]
        ),
    ):
        peers = cluster.peers
        assert len(peers) == 2
        assert peers[0] is node1
        assert peers[1] is node2


def test_reconcile_with_ip_addresses():
    """reconcile works when Raft uses IP addresses (issue #105)."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    mock_leader = mock.MagicMock(spec=OrchestratorRaftNode)
    mock_leader.raft_peers = ["10.1.1.1:10008", "10.1.1.2:10008", "10.1.1.99:10008"]
    node1 = mock.MagicMock(spec=OrchestratorRaftNode)
    node1.hostname = "ip-10-1-1-1"
    node1.private_ip = "10.1.1.1"
    node2 = mock.MagicMock(spec=OrchestratorRaftNode)
    node2.hostname = "ip-10-1-1-2"
    node2.private_ip = "10.1.1.2"
    node3 = mock.MagicMock(spec=OrchestratorRaftNode)
    node3.hostname = "ip-10-1-1-3"
    node3.private_ip = "10.1.1.3"
    with (
        mock.patch.object(OrchestratorRaftCluster, "leader", new_callable=mock.PropertyMock, return_value=mock_leader),
        mock.patch.object(
            OrchestratorRaftCluster, "nodes", new_callable=mock.PropertyMock, return_value=[node1, node2, node3]
        ),
    ):
        cluster.reconcile()
    # Stale peer 10.1.1.99 removed
    mock_leader.remove_peer.assert_called_once()
    removed_node = mock_leader.remove_peer.call_args[0][0]
    assert isinstance(removed_node, OrchestratorRaftNode)
    assert removed_node.peer_addr == "10.1.1.99:10008"
    # Missing node3 added
    mock_leader.add_peer.assert_called_once_with(node3)


def test_asg_session_propagated():
    """The ASG instance receives the session from the cluster."""
    mock_session = mock.MagicMock()
    cluster = OrchestratorRaftCluster(
        "my-asg", region="us-east-1", role_arn="arn:aws:iam::123:role/r", session=mock_session
    )
    with mock.patch.object(ASG, "__init__", return_value=None) as mock_init:
        _ = cluster._asg
        mock_init.assert_called_once_with(
            "my-asg", region="us-east-1", role_arn="arn:aws:iam::123:role/r", session=mock_session
        )


def test_asg_lazy_created_once():
    """The ASG instance is created only once."""
    cluster = OrchestratorRaftCluster("my-asg", region="us-east-1")
    with mock.patch.object(ASG, "__init__", return_value=None) as mock_init:
        _ = cluster._asg
        _ = cluster._asg
        mock_init.assert_called_once()
