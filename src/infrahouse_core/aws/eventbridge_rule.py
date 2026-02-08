"""
EventBridge Rule resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(remove all targets before deleting the rule).
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class EventBridgeRule(AWSResource):
    """Wrapper around an EventBridge rule.

    :param rule_name: Name of the EventBridge rule.
    :param event_bus_name: Name of the event bus (defaults to ``"default"``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, rule_name, event_bus_name="default", region=None, role_arn=None, session=None
    ):
        super().__init__(rule_name, "events", region=region, role_arn=role_arn, session=session)
        self._event_bus_name = event_bus_name

    @property
    def rule_name(self) -> str:
        """Return the name of the rule.

        :rtype: str
        """
        return self._resource_id

    @property
    def event_bus_name(self) -> str:
        """Return the event bus name.

        :rtype: str
        """
        return self._event_bus_name

    @property
    def exists(self) -> bool:
        """Return ``True`` if the rule exists.

        Returns ``False`` if the API raises ``ResourceNotFoundException``.
        """
        try:
            self._client.describe_rule(
                Name=self._resource_id,
                EventBusName=self._event_bus_name,
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the rule after removing all targets.

        Teardown order:
        1. List and remove all targets.
        2. Delete the rule itself.

        Idempotent -- does nothing if the rule does not exist.
        """
        try:
            self._remove_all_targets()
            self._client.delete_rule(
                Name=self._resource_id,
                EventBusName=self._event_bus_name,
            )
            LOG.info("Deleted EventBridge rule %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("EventBridge rule %s does not exist.", self._resource_id)
            else:
                raise

    def _remove_all_targets(self) -> None:
        """Remove all targets from the rule.

        Paginates through ``list_targets_by_rule`` and calls
        ``remove_targets`` for each batch of target IDs.

        :raises ClientError: If the EventBridge API call fails.
            ``ResourceNotFoundException`` is not caught here; the caller
            is responsible for handling it.
        """
        paginator = self._client.get_paginator("list_targets_by_rule")
        for page in paginator.paginate(
            Rule=self._resource_id,
            EventBusName=self._event_bus_name,
        ):
            targets = page.get("Targets", [])
            if not targets:
                continue
            target_ids = [t["Id"] for t in targets]
            self._client.remove_targets(
                Rule=self._resource_id,
                EventBusName=self._event_bus_name,
                Ids=target_ids,
            )
            LOG.debug(
                "Removed %d targets from rule %s",
                len(target_ids),
                self._resource_id,
            )
