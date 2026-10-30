"""Support for the Google Cloud speech to text service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
import os

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import (
    Aborted,
    GoogleAPIError,
    InternalServerError,
    ServiceUnavailable,
)
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

# Requests in a stream can't carry more than 25 KB of audio
MAX_REQUEST_AUDIO = 25000
TIMEOUT = 30
ATTEMPTS = 3
RETRY_DELAY = 0.1
RETRYABLE_ERRORS = (Aborted, InternalServerError, ServiceUnavailable)

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
    service_account_info = config_entry.data[SERVICE_ACCOUNT_INFO]
    model = config_entry.options.get(CONF_MODEL, DEFAULT_MODEL)
    location = config_entry.options.get(CONF_LOCATION, DEFAULT_LOCATION)

    async_add_entities(
        [
            GoogleCloudSTTProvider(
                _create_client(service_account_info, model, location),
                model,
                location,
                service_account_info["project_id"],
            ),
        ]
    )


def _create_client(service_account_info, model, location):
    """Create the client of the API that serves the model."""
    if model not in V2_MODELS:
        return speech.SpeechAsyncClient.from_service_account_info(service_account_info)

    endpoint = (
        "speech.googleapis.com"
        if location == "global"
        else f"{location}-speech.googleapis.com"
    )
    return speech_v2.SpeechAsyncClient.from_service_account_info(
        service_account_info,
        client_options=ClientOptions(api_endpoint=endpoint),
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


class AudioReplay:
    """Read an audio stream once, so that every attempt can send all of it.

    A failed call must not cancel the read of the live stream, so it happens in
    its own task.
    """

    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        """Start reading the stream."""
        self._chunks: list[bytes] = []
        self._done = False
        self._changed = asyncio.Event()
        self._reader = asyncio.create_task(self._read(stream))

    async def _read(self, stream: AsyncIterable[bytes]) -> None:
        """Keep the chunks of the stream."""
        try:
            async for chunk in stream:
                self._chunks.append(chunk)
                self._notify()
        finally:
            self._done = True
            self._notify()

    def _notify(self) -> None:
        """Wake up the attempt that is waiting for audio."""
        self._changed.set()
        self._changed = asyncio.Event()

    async def chunks(self) -> AsyncIterator[bytes]:
        """Yield the stream from the start, within the request size limit."""
        sent = 0
        while True:
            if sent < len(self._chunks):
                chunk = self._chunks[sent]
                sent += 1
                for start in range(0, len(chunk), MAX_REQUEST_AUDIO):
                    yield chunk[start : start + MAX_REQUEST_AUDIO]
            elif self._done:
                return
            else:
                await self._changed.wait()

    def close(self) -> None:
        """Stop reading the stream."""
        self._reader.cancel()


class GoogleCloudSTTProvider(stt.SpeechToTextEntity):
    """The Google Cloud STT API provider."""

    _attr_name = "Google Cloud STT"
    _attr_unique_id = "google-cloud-speech-to-text"

    def __init__(self, client, model, location, project_id) -> None:
        """Init Google Cloud STT service."""
        self._client = client
        self._model = model
        self._location = location
        self._project_id = project_id

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
        audio = AudioReplay(stream)
        requests = (
            self._requests_v2 if self._model in V2_MODELS else self._requests_v1
        )

        try:
            async with asyncio.timeout(TIMEOUT):
                for attempt in range(1, ATTEMPTS + 1):
                    try:
                        transcript = await self._recognize(requests(audio, metadata))
                        break
                    except RETRYABLE_ERRORS as err:
                        if attempt == ATTEMPTS:
                            raise
                        _LOGGER.warning("Retrying after error: %s", err)
                        await asyncio.sleep(RETRY_DELAY * attempt)
        except (GoogleAPIError, TimeoutError) as err:
            _LOGGER.error("Error during speech recognition: %r", err)
            return SpeechResult(None, SpeechResultState.ERROR)
        finally:
            audio.close()

        if transcript:
            return SpeechResult(transcript, SpeechResultState.SUCCESS)
        return SpeechResult(None, SpeechResultState.ERROR)

    async def _recognize(self, requests: AsyncIterator) -> str:
        """Stream the requests, returning the whole transcript."""
        responses = await self._client.streaming_recognize(
            requests=requests, retry=None, timeout=TIMEOUT
        )

        transcripts = []
        async for response in responses:
            for result in response.results:
                if result.alternatives:
                    transcripts.append(result.alternatives[0].transcript.strip())
        return " ".join(filter(None, transcripts))

    async def _requests_v1(
        self, audio: AudioReplay, metadata: SpeechMetadata
    ) -> AsyncIterator[speech.StreamingRecognizeRequest]:
        """Yield the requests of a V1 stream."""
        encoding = (
            speech.RecognitionConfig.AudioEncoding.OGG_OPUS
            if metadata.codec == AudioCodecs.OPUS
            else speech.RecognitionConfig.AudioEncoding.LINEAR16
        )
        yield speech.StreamingRecognizeRequest(
            streaming_config=speech.StreamingRecognitionConfig(
                config=speech.RecognitionConfig(
                    language_code=metadata.language,
                    encoding=encoding,
                    sample_rate_hertz=metadata.sample_rate,
                    model=self._model,
                )
            )
        )
        async for chunk in audio.chunks():
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    async def _requests_v2(
        self, audio: AudioReplay, metadata: SpeechMetadata
    ) -> AsyncIterator[cloud_speech.StreamingRecognizeRequest]:
        """Yield the requests of a V2 stream."""
        encoding = (
            cloud_speech.ExplicitDecodingConfig.AudioEncoding.OGG_OPUS
            if metadata.codec == AudioCodecs.OPUS
            else cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16
        )
        yield cloud_speech.StreamingRecognizeRequest(
            recognizer=f"projects/{self._project_id}/locations/{self._location}/recognizers/_",
            streaming_config=cloud_speech.StreamingRecognitionConfig(
                config=cloud_speech.RecognitionConfig(
                    explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                        encoding=encoding,
                        sample_rate_hertz=metadata.sample_rate,
                        audio_channel_count=metadata.channel,
                    ),
                    language_codes=[metadata.language],
                    model=self._model,
                )
            ),
        )
        async for chunk in audio.chunks():
            yield cloud_speech.StreamingRecognizeRequest(audio=chunk)
