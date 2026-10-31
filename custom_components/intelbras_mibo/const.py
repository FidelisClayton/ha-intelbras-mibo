from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "intelbras_mibo"
PLATFORMS = [Platform.SWITCH]
CONF_DEVICE_IDS = "device_ids"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
