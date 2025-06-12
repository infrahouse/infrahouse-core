import logging

from infrahouse_core.logging import setup_logging

LOG = logging.getLogger()


setup_logging(LOG, debug=True, debug_botocore=False)
