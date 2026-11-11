"""Constants for the E.ON W1000 integration."""

from datetime import timedelta

DOMAIN = "eon_w1000"

CONF_SCRIPT_URL = "script_url"
CONF_TOKEN = "token"
CONF_IMPORT_COLUMN = "import_column"
CONF_EXPORT_COLUMN = "export_column"
CONF_INTERVAL_END = "interval_end"
CONF_POD = "pod"

DEFAULT_NAME = "E.ON"
DEFAULT_IMPORT_COLUMN = "+A"
DEFAULT_EXPORT_COLUMN = "-A"

SCRIPT_URL_PREFIX = "https://script.google.com/"

UPDATE_INTERVAL = timedelta(hours=1)
PAGE_LIMIT = 10
MAX_PAGES = 10
SEEN_IDS_KEPT = 500

KIND_IMPORT = "import"
KIND_EXPORT = "export"
KIND_NAMES = {KIND_IMPORT: "consumption", KIND_EXPORT: "feed-in"}

DATA_EXTENSIONS = (".csv", ".xlsx", ".txt")
