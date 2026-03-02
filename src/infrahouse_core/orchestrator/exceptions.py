"""Top level exceptions.

The exception hierarchy repeats the structure of the infrahouse_core package.
Each module in the package has its own exceptions.py module.
The module exceptions are inherited from the upper module exceptions.

"""

from infrahouse_core.exceptions import IHCoreException


class IHOrchestratorException(IHCoreException):
    """Orchestrator related InfraHouse exception"""


class IHRaftLeaderNotFound(IHOrchestratorException):
    """No Raft leader could be found among the known nodes"""


class IHRaftPeerError(IHOrchestratorException):
    """A raft-add-peer or raft-remove-peer call failed"""
