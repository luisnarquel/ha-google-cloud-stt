"""Tests for the Google Cloud STT integration."""

from collections.abc import AsyncIterable
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.cloud import speech, speech_v2
from google.cloud.speech_v2.types import cloud_speech
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.google_cloud_stt.const import (
    CONF_LOCATION,
    DOMAIN,
    SERVICE_ACCOUNT_INFO,
)
from custom_components.google_cloud_stt.stt import GoogleCloudSTTProvider
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResultState,
)
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow the custom integration to load."""


@pytest.fixture(scope="module")
def service_account_info() -> dict:
    """Return a service account with a throwaway key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test",
        "private_key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def metadata(codec: AudioCodecs = AudioCodecs.PCM) -> SpeechMetadata:
    """Return the metadata Assist sends."""
    return SpeechMetadata(
        language="pt-PT",
        format=AudioFormats.OGG if codec == AudioCodecs.OPUS else AudioFormats.WAV,
        codec=codec,
        bit_rate=AudioBitRates.BITRATE_16,
        sample_rate=AudioSampleRates.SAMPLERATE_16000,
        channel=AudioChannels.CHANNEL_MONO,
    )


async def audio_stream() -> AsyncIterable[bytes]:
    """Stream two chunks of audio."""
    yield b"ab"
    yield b"cd"


def v2_response(*transcripts: str) -> cloud_speech.RecognizeResponse:
    """Return a V2 response with one result per transcript."""
    return cloud_speech.RecognizeResponse(
        results=[
            cloud_speech.SpeechRecognitionResult(
                alternatives=[
                    cloud_speech.SpeechRecognitionAlternative(transcript=transcript)
                ]
            )
            for transcript in transcripts
        ]
    )


@pytest.mark.parametrize(
    ("location", "endpoint"),
    [
        ("eu", "eu-speech.googleapis.com"),
        ("us", "us-speech.googleapis.com"),
        ("global", "speech.googleapis.com"),
    ],
)
async def test_v2_request(
    hass: HomeAssistant, service_account_info: dict, location: str, endpoint: str
) -> None:
    """Test a V2 model uses the regional endpoint and an inline config."""
    provider = GoogleCloudSTTProvider(hass, service_account_info, "chirp_3", location)

    with patch.object(
        speech_v2.SpeechClient, "recognize", return_value=v2_response("liga a luz")
    ) as recognize:
        result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.result == SpeechResultState.SUCCESS
    assert result.text == "liga a luz"
    assert provider._client.api_endpoint == endpoint

    request = recognize.call_args.kwargs["request"]
    assert (
        request.recognizer
        == f"projects/test-project/locations/{location}/recognizers/_"
    )
    assert request.content == b"abcd"
    assert request.config.model == "chirp_3"
    assert list(request.config.language_codes) == ["pt-PT"]
    decoding = request.config.explicit_decoding_config
    assert decoding.encoding == decoding.AudioEncoding.LINEAR16
    assert decoding.sample_rate_hertz == 16000
    assert decoding.audio_channel_count == 1


async def test_v2_opus(hass: HomeAssistant, service_account_info: dict) -> None:
    """Test V2 decodes Opus audio."""
    provider = GoogleCloudSTTProvider(hass, service_account_info, "chirp_3", "eu")

    with patch.object(
        speech_v2.SpeechClient, "recognize", return_value=v2_response("olá")
    ) as recognize:
        await provider.async_process_audio_stream(
            metadata(AudioCodecs.OPUS), audio_stream()
        )

    decoding = recognize.call_args.kwargs["request"].config.explicit_decoding_config
    assert decoding.encoding == decoding.AudioEncoding.OGG_OPUS


async def test_v2_no_speech(hass: HomeAssistant, service_account_info: dict) -> None:
    """Test V2 reports an error when nothing was recognized."""
    provider = GoogleCloudSTTProvider(hass, service_account_info, "chirp_3", "eu")

    with patch.object(
        speech_v2.SpeechClient, "recognize", return_value=v2_response()
    ):
        result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.result == SpeechResultState.ERROR
    assert result.text is None


async def test_v1_model_uses_v1(hass: HomeAssistant, service_account_info: dict) -> None:
    """Test a V1 model still calls the global V1 API."""
    provider = GoogleCloudSTTProvider(
        hass, service_account_info, "command_and_search", "eu"
    )
    response = speech.RecognizeResponse(
        results=[
            speech.SpeechRecognitionResult(
                alternatives=[speech.SpeechRecognitionAlternative(transcript="olá")]
            )
        ]
    )

    with patch.object(
        speech.SpeechClient, "recognize", return_value=response
    ) as recognize:
        result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.text == "olá"
    assert provider._client.api_endpoint == "speech.googleapis.com"
    config = recognize.call_args.kwargs["config"]
    assert config.model == "command_and_search"
    assert config.language_code == "pt-PT"


async def test_options_are_saved_and_used(
    hass: HomeAssistant, service_account_info: dict
) -> None:
    """Test the options flow stores the model and sets up a V2 provider."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={SERVICE_ACCOUNT_INFO: service_account_info}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("stt.google_cloud_stt")
    assert state is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL: "chirp_3", CONF_LOCATION: "eu"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options == {CONF_MODEL: "chirp_3", CONF_LOCATION: "eu"}
    assert hass.states.get("stt.google_cloud_stt") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults == {CONF_MODEL: "chirp_3", CONF_LOCATION: "eu"}
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL: "chirp_3", CONF_LOCATION: "us"}
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_LOCATION] == "us"
