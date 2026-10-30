"""Support for the Google Cloud speech to text service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
import os

from google.api_core.client_options import ClientOptions
from google.cloud import speech, speech_v2
from google.cloud.speech_v2.types import cloud_speech

from homeassistant.components import stt
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_FILE_PATH, CONF_MODEL
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue

from .const import (
    _LOGGER,
    CONF_LOCATION,
    DEFAULT_LOCATION,
    DEFAULT_MODEL,
    DOMAIN,
    SERVICE_ACCOUNT_INFO,
    V2_MODELS,
)

SUPPORTED_LANGUAGES = [
    "af-ZA",
    "sq-AL",
    "am-ET",
    "ar-DZ",
    "ar-BH",
    "ar-EG",
    "ar-IQ",
    "ar-IL",
    "ar-JO",
    "ar-KW",
    "ar-LB",
    "ar-MA",
    "ar-OM",
    "ar-QA",
    "ar-SA",
    "ar-PS",
    "ar-TN",
    "ar-AE",
    "ar-YE",
    "hy-AM",
    "az-AZ",
    "eu-ES",
    "bn-BD",
    "bn-IN",
    "bs-BA",
    "bg-BG",
    "my-MM",
    "ca-ES",
    "zh-CN",
    "zh-TW",
    "hr-HR",
    "cs-CZ",
    "da-DK",
    "nl-BE",
    "nl-NL",
    "en-AU",
    "en-CA",
    "en-GH",
    "en-HK",
    "en-IN",
    "en-IE",
    "en-KE",
    "en-NZ",
    "en-NG",
    "en-PK",
    "en-PH",
    "en-SG",
    "en-ZA",
    "en-TZ",
    "en-GB",
    "en-US",
    "et-EE",
    "fil-PH",
    "fi-FI",
    "fr-BE",
    "fr-CA",
    "fr-FR",
    "fr-CH",
    "gl-ES",
    "ka-GE",
    "de-AT",
    "de-DE",
    "de-CH",
    "el-GR",
    "gu-IN",
    "iw-IL",
    "hi-IN",
    "hu-HU",
    "is-IS",
    "id-ID",
    "it-IT",
    "it-CH",
    "ja-JP",
    "jv-ID",
    "kn-IN",
    "kk-KZ",
    "km-KH",
    "ko-KR",
    "lo-LA",
    "lv-LV",
    "lt-LT",
    "mk-MK",
    "ms-MY",
    "ml-IN",
    "mr-IN",
    "mn-MN",
    "ne-NP",
    "no-NO",
    "fa-IR",
    "pl-PL",
    "pt-BR",
    "pt-PT",
    "ro-RO",
    "ru-RU",
    "sr-RS",
    "si-LK",
    "sk-SK",
    "sl-SI",
    "es-AR",
    "es-BO",
    "es-CL",
    "es-CO",
    "es-CR",
    "es-DO",
    "es-EC",
    "es-SV",
    "es-GT",
    "es-HN",
    "es-MX",
    "es-NI",
    "es-PA",
    "es-PY",
    "es-PE",
    "es-PR",
    "es-ES",
    "es-US",
    "es-UY",
    "es-VE",
    "su-ID",
    "sw-KE",
    "sw-TZ",
    "sv-SE",
    "ta-IN",
    "ta-MY",
    "ta-SG",
    "ta-LK",
    "te-IN",
    "th-TH",
    "tr-TR",
    "uk-UA",
    "ur-IN",
    "ur-PK",
    "uz-UZ",
    "vi-VN",
    "zu-ZA",
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Google Cloud speech-to-text."""

    async_add_entities(
        [
            GoogleCloudSTTProvider(
                hass,
                config_entry.data[SERVICE_ACCOUNT_INFO],
                config_entry.options.get(CONF_MODEL, DEFAULT_MODEL),
                config_entry.options.get(CONF_LOCATION, DEFAULT_LOCATION),
            ),
        ]
    )


async def async_get_engine(hass, config, discovery_info=None):
    """Initialize Google Cloud STT import config."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=config
    )
    if (
        result["type"] == FlowResultType.CREATE_ENTRY
        or result["reason"] == "single_instance_allowed"
    ):
        async_create_issue(
            hass,
            HOMEASSISTANT_DOMAIN,
            f"deprecated_yaml_{DOMAIN}",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="deprecated_yaml",
            translation_placeholders={
                "domain": DOMAIN,
                "integration_title": "Google Cloud Speech-to-Text",
            },
        )
    else:
        async_create_issue(
            hass,
            DOMAIN,
            f"deprecated_yaml_import_issue_{result['reason']}",
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=IssueSeverity.ERROR,
            translation_key=f"deprecated_yaml_import_issue_{result['reason']}",
            learn_more_url=f"/config/integrations/dashboard/add?domain={DOMAIN}",
        )


class GoogleCloudSTTProvider(stt.SpeechToTextEntity):
    """The Google Cloud STT API provider."""

    _attr_name = "Google Cloud STT"
    _attr_unique_id = "google-cloud-speech-to-text"

    def __init__(self, hass, service_account_info, model, location) -> None:
        """Init Google Cloud STT service."""
        self.hass = hass

        self._model = model
        self._location = location
        self._service_account_info = service_account_info
        self._client = None

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return SUPPORTED_LANGUAGES

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return a list of supported formats."""
        return [AudioFormats.WAV, AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return a list of supported codecs."""
        return [AudioCodecs.PCM, AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return a list of supported bitrates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return a list of supported samplerates."""
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return a list of supported channels."""
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Process an audio stream to STT service."""
        # Collect data
        audio_data = b""
        async for chunk in stream:
            audio_data += chunk

        recognize = (
            self._recognize_v2 if self._model in V2_MODELS else self._recognize_v1
        )

        async with asyncio.timeout(10):
            assert self.hass
            response = await self.hass.async_add_executor_job(
                recognize, audio_data, metadata
            )
            if response.results and response.results[0].alternatives:
                return SpeechResult(
                    response.results[0].alternatives[0].transcript,
                    SpeechResultState.SUCCESS,
                )
            return SpeechResult(None, SpeechResultState.ERROR)

    def _recognize_v1(self, audio_data: bytes, metadata: SpeechMetadata):
        """Recognize audio with the V1 API."""
        audio = speech.RecognitionAudio(content=audio_data)
        encoding = (
            speech.RecognitionConfig.AudioEncoding.OGG_OPUS
            if metadata.codec == AudioCodecs.OPUS
            else speech.RecognitionConfig.AudioEncoding.LINEAR16
        )
        config = speech.RecognitionConfig(
            language_code=metadata.language,
            encoding=encoding,
            sample_rate_hertz=metadata.sample_rate,
            model=self._model,
        )

        # Create the client on first use, so that it is created inside the executor job
        if self._client is None:
            self._client = speech.SpeechClient.from_service_account_info(self._service_account_info)

        return self._client.recognize(config=config, audio=audio)

    def _recognize_v2(self, audio_data: bytes, metadata: SpeechMetadata):
        """Recognize audio with the V2 API, which uses regional endpoints."""
        encoding = (
            cloud_speech.ExplicitDecodingConfig.AudioEncoding.OGG_OPUS
            if metadata.codec == AudioCodecs.OPUS
            else cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16
        )
        config = cloud_speech.RecognitionConfig(
            explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                encoding=encoding,
                sample_rate_hertz=metadata.sample_rate,
                audio_channel_count=metadata.channel,
            ),
            language_codes=[metadata.language],
            model=self._model,
        )
        project_id = self._service_account_info["project_id"]

        # Create the client on first use, so that it is created inside the executor job
        if self._client is None:
            endpoint = (
                "speech.googleapis.com"
                if self._location == "global"
                else f"{self._location}-speech.googleapis.com"
            )
            self._client = speech_v2.SpeechClient.from_service_account_info(
                self._service_account_info,
                client_options=ClientOptions(api_endpoint=endpoint),
            )

        return self._client.recognize(
            request=cloud_speech.RecognizeRequest(
                recognizer=f"projects/{project_id}/locations/{self._location}/recognizers/_",
                config=config,
                content=audio_data,
            )
        )
