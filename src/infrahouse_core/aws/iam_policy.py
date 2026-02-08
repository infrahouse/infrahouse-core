"""
IAM Policy resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(detach from all entities, delete non-default versions, then delete the policy).
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

if TYPE_CHECKING:
    from infrahouse_core.aws.iam_group import IAMGroup
    from infrahouse_core.aws.iam_role import IAMRole
    from infrahouse_core.aws.iam_user import IAMUser

LOG = getLogger(__name__)


class IAMPolicy(AWSResource):
    """Wrapper around an IAM managed policy.

    :param policy_arn: ARN of the IAM policy.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, policy_arn, region=None, role_arn=None, session=None):
        super().__init__(policy_arn, "iam", region=region, role_arn=role_arn, session=session)
        self._attached_roles = None
        self._attached_users = None
        self._attached_groups = None

    @property
    def policy_arn(self) -> str:
        """Return the ARN of the policy.

        :rtype: str
        """
        return self._resource_id

    @property
    def is_aws_managed(self) -> bool:
        """Return ``True`` if this is an AWS-managed policy.

        AWS-managed policies (e.g. ``arn:aws:iam::aws:policy/ReadOnlyAccess``)
        cannot be deleted or modified.

        :rtype: bool
        """
        return ":iam::aws:policy/" in self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the policy exists."""
        try:
            self._client.get_policy(PolicyArn=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                return False
            raise

    # -- Attached entities ---------------------------------------------------

    def _fetch_attached_entities(self) -> None:
        """Fetch all attached roles, users, and groups in a single pagination.

        Uses ``list_entities_for_policy`` to retrieve all three entity types
        in one paginated call, then stores the results in ``_attached_roles``,
        ``_attached_users``, and ``_attached_groups``.  Call
        :meth:`_reset_attached_entities` to invalidate the cache.

        :raises ClientError: If the IAM API call to list entities fails.
        """
        # pylint: disable=import-outside-toplevel
        from infrahouse_core.aws.iam_group import IAMGroup
        from infrahouse_core.aws.iam_role import IAMRole
        from infrahouse_core.aws.iam_user import IAMUser

        roles, users, groups = [], [], []
        paginator = self._client.get_paginator("list_entities_for_policy")
        for page in paginator.paginate(PolicyArn=self._resource_id):
            for role in page.get("PolicyRoles", []):
                roles.append(
                    IAMRole(role["RoleName"], region=self._region, role_arn=self._role_arn, session=self._session)
                )
            for user in page.get("PolicyUsers", []):
                users.append(
                    IAMUser(user["UserName"], region=self._region, role_arn=self._role_arn, session=self._session)
                )
            for group in page.get("PolicyGroups", []):
                groups.append(
                    IAMGroup(group["GroupName"], region=self._region, role_arn=self._role_arn, session=self._session)
                )
        self._attached_roles = roles
        self._attached_users = users
        self._attached_groups = groups

    def _reset_attached_entities(self) -> None:
        """Invalidate the cached attached-entity lists."""
        self._attached_roles = None
        self._attached_users = None
        self._attached_groups = None

    @property
    def attached_roles(self) -> list[IAMRole]:
        """Return roles that have this policy attached.

        :return: List of :class:`IAMRole` instances.
        :rtype: list[IAMRole]
        """
        if self._attached_roles is None:
            self._fetch_attached_entities()
        return self._attached_roles

    @property
    def attached_users(self) -> list[IAMUser]:
        """Return users that have this policy attached.

        :return: List of :class:`IAMUser` instances.
        :rtype: list[IAMUser]
        """
        if self._attached_users is None:
            self._fetch_attached_entities()
        return self._attached_users

    @property
    def attached_groups(self) -> list[IAMGroup]:
        """Return groups that have this policy attached.

        :return: List of :class:`IAMGroup` instances.
        :rtype: list[IAMGroup]
        """
        if self._attached_groups is None:
            self._fetch_attached_entities()
        return self._attached_groups

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the policy after detaching from all entities and removing non-default versions.

        Teardown order:
        1. Detach from all IAM roles, users, and groups.
        2. Delete all non-default policy versions.
        3. Delete the policy itself.

        AWS-managed policies cannot be deleted and are silently skipped.
        Idempotent -- does nothing if the policy does not exist.
        """
        if self.is_aws_managed:
            LOG.info("Skipping deletion of AWS-managed policy %s", self._resource_id)
            return
        try:
            self._detach_from_all_entities()
            self._delete_non_default_versions()
            self._client.delete_policy(PolicyArn=self._resource_id)
            LOG.info("Deleted IAM policy %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                LOG.info("IAM policy %s does not exist.", self._resource_id)
            else:
                raise

    def _detach_from_all_entities(self) -> None:
        """Detach the policy from all roles, users, and groups.

        Delegates to each entity's own ``detach_policy()`` method
        (:meth:`~IAMRole.detach_policy`, :meth:`~IAMUser.detach_policy`,
        :meth:`~IAMGroup.detach_policy`).  Invalidates the attached-entity
        cache after all detach operations complete.

        :raises ClientError: If the IAM API call to detach a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        roles, users, groups = self.attached_roles, self.attached_users, self.attached_groups
        total = len(roles) + len(users) + len(groups)
        if total:
            LOG.info(
                "Detaching policy %s from %d entities (%d roles, %d users, %d groups)",
                self._resource_id,
                total,
                len(roles),
                len(users),
                len(groups),
            )
        for role in roles:
            role.detach_policy(self)
        for user in users:
            user.detach_policy(self)
        for group in groups:
            group.detach_policy(self)
        self._reset_attached_entities()

    def _delete_non_default_versions(self) -> None:
        """Delete all non-default policy versions.

        Lists all versions via ``list_policy_versions`` pagination, then
        deletes each non-default version with ``delete_policy_version``.
        The default version cannot be deleted directly; it is removed
        automatically when the policy itself is deleted.

        :raises ClientError: If the IAM API call to list or delete versions fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        non_default = []
        paginator = self._client.get_paginator("list_policy_versions")
        for page in paginator.paginate(PolicyArn=self._resource_id):
            for version in page["Versions"]:
                if not version["IsDefaultVersion"]:
                    non_default.append(version["VersionId"])
        if non_default:
            LOG.info("Deleting %d non-default versions of policy %s", len(non_default), self._resource_id)
        for version_id in non_default:
            self._client.delete_policy_version(
                PolicyArn=self._resource_id,
                VersionId=version_id,
            )
            LOG.debug("Deleted policy version %s of %s", version_id, self._resource_id)
