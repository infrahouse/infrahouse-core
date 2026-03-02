"""Tests for OrchestratorRaftNode."""

import json
from unittest import mock

import pytest

from infrahouse_core.orchestrator.exceptions import IHRaftPeerError
from infrahouse_core.orchestrator.raft_node import OrchestratorRaftNode


def _mock_instance(private_ip="10.1.1.1", hostname="ip-10-1-1-1"):
    """Helper to create a mock ASGInstance."""
    inst = mock.MagicMock()
    inst.private_ip = private_ip
    inst.hostname = hostname
    return inst


def test_private_ip():
    """private_ip property returns the instance's private IP."""
    node = OrchestratorRaftNode(_mock_instance("10.1.1.1"))
    assert node.private_ip == "10.1.1.1"


def test_hostname():
    """hostname property returns the instance's short hostname."""
    node = OrchestratorRaftNode(_mock_instance(hostname="ip-10-1-1-1"))
    assert node.hostname == "ip-10-1-1-1"


def test_peer_addr():
    """peer_addr returns hostname:raft_port."""
    node = OrchestratorRaftNode(_mock_instance(hostname="ip-10-1-1-1"), raft_port=10008)
    assert node.peer_addr == "ip-10-1-1-1:10008"


def test_peer_addr_custom_port():
    """peer_addr uses the configured raft_port."""
    node = OrchestratorRaftNode(_mock_instance(hostname="ip-10-1-1-1"), raft_port=20000)
    assert node.peer_addr == "ip-10-1-1-1:20000"


def test_instance():
    """instance property returns the underlying ASGInstance."""
    inst = _mock_instance()
    node = OrchestratorRaftNode(inst)
    assert node.instance is inst


def test_raft_peers():
    """raft_peers returns the parsed JSON array from the API."""
    peers = ["ip-10-1-1-1:10008", "ip-10-1-1-2:10008"]
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps(peers), "")
    node = OrchestratorRaftNode(inst)
    assert node.raft_peers == peers
    inst.execute_command.assert_called_once_with("curl -sf http://localhost:3000/api/raft-peers")


def test_raft_peers_command_failure():
    """raft_peers raises IHRaftPeerError when curl fails."""
    inst = _mock_instance()
    inst.execute_command.return_value = (7, "", "Failed to connect")
    node = OrchestratorRaftNode(inst)
    with pytest.raises(IHRaftPeerError, match="Failed to connect"):
        _ = node.raft_peers


def test_raft_leader_with_leader():
    """raft_leader returns the leader address."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps("ip-10-1-1-1:10008"), "")
    node = OrchestratorRaftNode(inst)
    assert node.raft_leader == "ip-10-1-1-1:10008"


def test_raft_leader_nil():
    """raft_leader returns None when Orchestrator reports 'nil'."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps("nil"), "")
    node = OrchestratorRaftNode(inst)
    assert node.raft_leader is None


def test_raft_leader_empty():
    """raft_leader returns None on an empty string."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps(""), "")
    node = OrchestratorRaftNode(inst)
    assert node.raft_leader is None


def test_raft_health():
    """raft_health returns the parsed JSON payload."""
    health = {"Healthy": True, "IsPartOfQuorum": True}
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps(health), "")
    node = OrchestratorRaftNode(inst)
    assert node.raft_health == health


def test_is_leader_true():
    """is_leader returns True when raft_leader matches own peer_addr."""
    node = OrchestratorRaftNode(_mock_instance(hostname="ip-10-1-1-1"), raft_port=10008)
    with mock.patch.object(
        OrchestratorRaftNode, "raft_leader", new_callable=mock.PropertyMock, return_value="ip-10-1-1-1:10008"
    ):
        assert node.is_leader is True


def test_is_leader_false():
    """is_leader returns False when raft_leader is a different node."""
    node = OrchestratorRaftNode(_mock_instance(hostname="ip-10-1-1-1"), raft_port=10008)
    with mock.patch.object(
        OrchestratorRaftNode, "raft_leader", new_callable=mock.PropertyMock, return_value="ip-10-1-1-2:10008"
    ):
        assert node.is_leader is False


def test_is_leader_no_leader():
    """is_leader returns False when there is no leader."""
    node = OrchestratorRaftNode(_mock_instance(hostname="ip-10-1-1-1"), raft_port=10008)
    with mock.patch.object(OrchestratorRaftNode, "raft_leader", new_callable=mock.PropertyMock, return_value=None):
        assert node.is_leader is False


def test_add_peer_success():
    """add_peer succeeds when Orchestrator returns OK."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps({"Code": "OK", "Message": ""}), "")
    node = OrchestratorRaftNode(inst)
    peer = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-3:10008")
    node.add_peer(peer)
    inst.execute_command.assert_called_once_with("curl -sf http://localhost:3000/api/raft-add-peer/ip-10-1-1-3:10008")


def test_add_peer_orchestrator_error():
    """add_peer raises IHRaftPeerError when Orchestrator returns ERROR."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps({"Code": "ERROR", "Message": "peer already exists"}), "")
    node = OrchestratorRaftNode(inst)
    peer = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-3:10008")
    with pytest.raises(IHRaftPeerError, match="peer already exists"):
        node.add_peer(peer)


def test_add_peer_curl_failure():
    """add_peer raises IHRaftPeerError when curl fails."""
    inst = _mock_instance()
    inst.execute_command.return_value = (22, "", "HTTP 500")
    node = OrchestratorRaftNode(inst)
    peer = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-3:10008")
    with pytest.raises(IHRaftPeerError, match="HTTP 500"):
        node.add_peer(peer)


def test_remove_peer_success():
    """remove_peer succeeds when Orchestrator returns OK."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps({"Code": "OK", "Message": ""}), "")
    node = OrchestratorRaftNode(inst)
    peer = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-3:10008")
    node.remove_peer(peer)
    inst.execute_command.assert_called_once_with(
        "curl -sf http://localhost:3000/api/raft-remove-peer/ip-10-1-1-3:10008"
    )


def test_remove_peer_curl_failure():
    """remove_peer raises IHRaftPeerError when curl fails."""
    inst = _mock_instance()
    inst.execute_command.return_value = (7, "", "Connection refused")
    node = OrchestratorRaftNode(inst)
    peer = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-3:10008")
    with pytest.raises(IHRaftPeerError, match="Connection refused"):
        node.remove_peer(peer)


def test_api_get_custom_port():
    """_api_get uses the configured http_port."""
    inst = _mock_instance()
    inst.execute_command.return_value = (0, json.dumps(["peer"]), "")
    node = OrchestratorRaftNode(inst, http_port=8080)
    assert node.raft_peers == ["peer"]
    inst.execute_command.assert_called_once_with("curl -sf http://localhost:8080/api/raft-peers")


def test_check_raft_response_non_dict():
    """_check_raft_response does nothing for non-dict results (e.g. a list)."""
    OrchestratorRaftNode._check_raft_response(["peer1", "peer2"], "test")


def test_from_peer_addr():
    """from_peer_addr creates a node with hostname and port from a peer address string."""
    node = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-1:10008")
    assert node.hostname == "ip-10-1-1-1"
    assert node.peer_addr == "ip-10-1-1-1:10008"
    assert node.instance is None


def test_from_peer_addr_custom_port():
    """from_peer_addr parses the port from the address."""
    node = OrchestratorRaftNode.from_peer_addr("ip-10-1-1-1:20000")
    assert node.peer_addr == "ip-10-1-1-1:20000"
