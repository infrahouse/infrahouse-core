import logging

from infrahouse_core.logging import setup_logging

LOG = logging.getLogger()

setup_logging(LOG, debug_botocore=False)
logging.getLogger("urllib3").setLevel(logging.WARNING)
