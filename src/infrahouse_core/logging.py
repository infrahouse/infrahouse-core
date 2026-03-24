"""
InfraHouse Toolkit Logging.
"""

import logging
import sys
from typing import Optional


class LessThanFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Filters out log messages of a lower level."""

    def __init__(self, exclusive_maximum, name=""):
        super().__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record):
        # non-zero return means we log this message
        return 1 if record.levelno < self.max_level else 0


def setup_logging(  # pragma: no cover
    logger: Optional[logging.Logger] = None,
    debug: bool = False,
    quiet: bool = False,
    debug_botocore: bool = False,
) -> None:
    """
    Configure logging for the module.

    Sets up stdout/stderr handlers with level-based routing. The logger is
    configured in place and nothing is returned.

    :param logger: Logger to configure. If ``None``, uses the root logger.
    :type logger: logging.Logger or None
    :param debug: Enable debug logging.
    :type debug: bool
    :param quiet: Suppress INFO logs.
    :type quiet: bool
    :param debug_botocore: If True, keep botocore at debug level instead of suppressing it.
    :type debug_botocore: bool
    """
    logger = logger or logging.getLogger()
    fmt_str = "%(asctime)s: %(levelname)s: %(name)s:%(module)s.%(funcName)s():%(lineno)d: %(message)s"

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.addFilter(LessThanFilter(logging.WARNING))
    console_handler.setLevel(logging.ERROR if quiet else logging.INFO)
    console_handler.setFormatter(logging.Formatter(fmt_str))

    # Log errors and warnings to stderr
    console_handler_err = logging.StreamHandler(stream=sys.stderr)
    console_handler_err.setLevel(logging.ERROR if quiet else logging.WARNING)
    console_handler_err.setFormatter(logging.Formatter(fmt_str))

    # Log debug to stderr
    console_handler_debug = logging.StreamHandler(stream=sys.stderr)
    console_handler_debug.addFilter(LessThanFilter(logging.INFO))
    console_handler_debug.setLevel(logging.DEBUG)
    console_handler_debug.setFormatter(logging.Formatter(fmt_str))

    logger.handlers = []
    logger.addHandler(console_handler)
    logger.addHandler(console_handler_err)

    if debug:
        logger.addHandler(console_handler_debug)
        logger.debug_enabled = True

    logger.setLevel(logging.DEBUG)

    # botocore prints a lot of logs at INFO and WARNING level that deserve to be only DEBUG.
    botocore_level = logging.DEBUG if debug_botocore else logging.WARNING
    logging.getLogger("botocore").setLevel(botocore_level if debug else logging.ERROR)
