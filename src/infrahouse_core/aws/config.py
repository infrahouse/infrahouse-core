"""
Module for AWSConfig class.
"""

from configparser import ConfigParser, NoOptionError, NoSectionError
from os import path as osp


class AWSConfig:
    """
    Class AWSConfig parses AWS CLI config file, ``~/.aws/config`` by default,
    and provides a convenient interfaces to certain configuration options.

    :param aws_home: Path to a directory with AWS configs. By default, ``~/.aws/``.
    :type aws_home: str
    """

    def __init__(self, aws_home=None):
        self._aws_home = aws_home
        self._config_parser = None

    @property
    def aws_home(self):
        """Path to AWS config directory."""
        if self._aws_home is None:
            self._aws_home = osp.join(osp.expanduser("~"), ".aws")
        return self._aws_home

    @property
    def config_path(self):
        """Path to AWS config file."""
        return osp.join(self.aws_home, "config")

    @property
    def config_parser(self) -> ConfigParser:
        """ConfigParser object that represents ``~/.aws/config``."""
        if self._config_parser is None:
            self._config_parser = ConfigParser()
            self._config_parser.read(self.config_path)

        return self._config_parser

    @property
    def profiles(self) -> list:
        """List of configured AWS profiles."""
        return [
            "default" if section == "default" else section.split(" ")[1]
            for section in self.config_parser.sections()
            if (section.startswith("profile") or section == "default")
        ]

    @property
    def regions(self) -> list:
        """Return a list of all AWS regions"""
        return [
            "af-south-1",
            "ap-east-1",
            "ap-northeast-1",
            "ap-northeast-2",
            "ap-northeast-3",
            "ap-south-1",
            "ap-southeast-1",
            "ap-southeast-2",
            "ap-southeast-3",
            "ca-central-1",
            "eu-central-1",
            "eu-north-1",
            "eu-south-1",
            "eu-west-1",
            "eu-west-2",
            "eu-west-3",
            "me-south-1",
            "sa-east-1",
            "us-east-1",
            "us-east-2",
            "us-west-1",
            "us-west-2",
        ]

    def get_account_id(self, profile_name: str) -> str:
        """
        Read AWS account ID for given profile.

        :param profile_name: AWS profile name.
        :type profile_name: str
        :return: AWS account ID (12-digit number).
        :rtype: str
        :raises NoSectionError: If profile doesn't exist in config.
        :raises NoOptionError: If ``sso_account_id`` is not configured for profile.
        """
        return self.config_parser.get(self._get_section(profile_name), "sso_account_id")

    def get_region(self, profile_name: str) -> str:
        """
        Read AWS region for given profile.

        Falls back to the ``[default]`` section if the profile or region option is not found.

        :param profile_name: AWS profile name.
        :type profile_name: str
        :return: AWS region name, or ``None`` if not configured anywhere.
        :rtype: str or None
        """
        try:
            return self.config_parser.get(self._get_section(profile_name), "region")
        except NoSectionError:
            return self.config_parser.get("default", "region") if "default" in self.config_parser.sections() else None

        except NoOptionError:
            return self.config_parser.get("default", "region") if "default" in self.config_parser.sections() else None

    def get_sso_region(self, profile_name: str) -> str:
        """
        Read SSO region for given profile.

        Looks up the ``sso_session`` for the profile, then reads ``sso_region``
        from that session's config section. Falls back to the ``[default]`` region.

        :param profile_name: AWS profile name.
        :type profile_name: str
        :return: SSO region name, or ``None`` if not configured anywhere.
        :rtype: str or None
        """
        try:
            sso_session = self.config_parser.get(self._get_section(profile_name), "sso_session")
        except NoOptionError:
            return self.config_parser.get("default", "region") if "default" in self.config_parser.sections() else None

        except NoSectionError:
            return self.config_parser.get("default", "region") if "default" in self.config_parser.sections() else None

        try:
            return self.config_parser.get(f"sso-session {sso_session}", "sso_region")
        except NoOptionError:
            return self.config_parser.get("default", "region")

    def get_role(self, profile_name: str) -> str:
        """
        Read AWS IAM role name for given profile.

        :param profile_name: AWS profile name.
        :type profile_name: str
        :return: SSO role name.
        :rtype: str
        :raises NoSectionError: If profile doesn't exist in config.
        :raises NoOptionError: If ``sso_role_name`` is not configured for profile.
        """
        return self.config_parser.get(self._get_section(profile_name), "sso_role_name")

    def get_start_url(self, profile_name: str) -> str:
        """
        Read SSO start URL for given profile.

        Looks up the ``sso_session`` for the profile, then reads ``sso_start_url``
        from that session's config section.

        :param profile_name: AWS profile name.
        :type profile_name: str
        :return: SSO start URL.
        :rtype: str
        :raises NoSectionError: If profile or SSO session section doesn't exist.
        :raises NoOptionError: If ``sso_session`` or ``sso_start_url`` is not configured.
        """
        sso_session = self.config_parser.get(self._get_section(profile_name), "sso_session")
        return self.config_parser.get(f"sso-session {sso_session}", "sso_start_url")

    @staticmethod
    def _get_section(profile_name):
        return "default" if profile_name in ["default", None] else f"profile {profile_name}"
