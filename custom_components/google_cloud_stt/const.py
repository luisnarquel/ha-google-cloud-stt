"""Constants for the Google Cloud Speech-to-Text integration."""

import logging

_LOGGER = logging.getLogger(__package__)


DOMAIN = "google_cloud_stt"
DEFAULT_MODEL = "command_and_search"
DEFAULT_LOCATION = "eu"

CONF_LOCATION = "location"
SERVICE_ACCOUNT_INFO = "service_account_info"

# Models that are only available in the V2 API
V2_MODELS = [
    "chirp_3",
    "chirp_2",
    "long",
    "short",
    "telephony",
    "telephony_short",
]

SUPPORTED_MODELS = [
    "default",
    "command_and_search",
    "latest_short",
    "latest_long",
    "phone_call",
    "video",
    *V2_MODELS,
]

# Locations for the V2 API. Availability depends on the model and language, see
# https://cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages
SUPPORTED_LOCATIONS = [
    "eu",
    "us",
    "global",
    "europe-west4",
    "us-central1",
    "asia-southeast1",
]
