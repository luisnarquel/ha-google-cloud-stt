"""Tests for the Google Cloud STT integration."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.cloud import speech, speech_v2
from google.cloud.speech_v1.services.speech.transports import (
    SpeechGrpcAsyncIOTransport as SpeechGrpcAsyncIOTransportV1,
)
from google.cloud.speech_v2.services.speech.transports import (
    SpeechGrpcAsyncIOTransport as SpeechGrpcAsyncIOTransportV2,
)
from google.cloud.speech_v2.types import cloud_speech
import grpc
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.google_cloud_stt.const import (
    CONF_LOCATION,
    DOMAIN,
    SERVICE_ACCOUNT_INFO,
    V2_MODELS,
)
from custom_components.google_cloud_stt.stt import (
    ATTEMPTS,
    MAX_REQUEST_AUDIO,
    GoogleCloudSTTProvider,
    _create_client,
)
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


# Start the poller thread of gRPC now, or the harness reports it as left behind
grpc.aio.init_grpc_aio()


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


class FakeGoogle:
    """A gRPC server that answers like the Speech API."""

    def __init__(self) -> None:
        """Start with no scripted behaviour."""
        self.calls: list[list] = []
        self.script: list[dict] = []
        self.received_audio = asyncio.Event()
        self.channel = None

    def reply(self, *transcripts: str, hang: bool = False) -> None:
        """Answer the next call."""
        self.script.append({"transcripts": transcripts, "hang": hang})

    def fail(self, code: grpc.StatusCode, after_requests: int = 0) -> None:
        """Fail the next call."""
        self.script.append({"code": code, "after_requests": after_requests})

    def provider(self, model: str) -> GoogleCloudSTTProvider:
        """Return a provider connected to this server."""
        if model in V2_MODELS:
            client = speech_v2.SpeechAsyncClient(
                transport=SpeechGrpcAsyncIOTransportV2(channel=self.channel)
            )
        else:
            client = speech.SpeechAsyncClient(
                transport=SpeechGrpcAsyncIOTransportV1(channel=self.channel)
            )
        return GoogleCloudSTTProvider(client, model, "eu", "test-project")

    def handler(self, request_type, response_type):
        """Return the handler of StreamingRecognize."""

        async def streaming_recognize(requests, context):
            step = self.script.pop(0)
            call: list = []
            self.calls.append(call)
            async for request in requests:
                call.append(request)
                if len(call) == 2:
                    self.received_audio.set()
                if step.get("code") and len(call) >= step["after_requests"]:
                    await context.abort(step["code"], "scripted failure")
            if step.get("code"):
                await context.abort(step["code"], "scripted failure")
            if step["hang"]:
                await asyncio.sleep(30)
            yield response_type(
                results=[
                    {"alternatives": [{"transcript": transcript}], "is_final": True}
                    for transcript in step["transcripts"]
                ]
            )

        return grpc.stream_stream_rpc_method_handler(
            streaming_recognize,
            request_deserializer=request_type.deserialize,
            response_serializer=response_type.serialize,
        )


@pytest.fixture
async def fake_google(expected_lingering_tasks) -> AsyncIterator[FakeGoogle]:
    """Run a fake Speech API."""
    fake = FakeGoogle()
    handlers = {
        "google.cloud.speech.v1.Speech": {
            "StreamingRecognize": fake.handler(
                speech.StreamingRecognizeRequest, speech.StreamingRecognizeResponse
            )
        },
        "google.cloud.speech.v2.Speech": {
            "StreamingRecognize": fake.handler(
                cloud_speech.StreamingRecognizeRequest,
                cloud_speech.StreamingRecognizeResponse,
            )
        },
    }
    server = grpc.aio.server()
    server.add_generic_rpc_handlers(
        [
            grpc.method_handlers_generic_handler(service, methods)
            for service, methods in handlers.items()
        ]
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    fake.channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    yield fake
    await fake.channel.close()
    await server.stop(None)


@pytest.mark.parametrize(
    ("location", "endpoint"),
    [
        ("eu", "eu-speech.googleapis.com"),
        ("us", "us-speech.googleapis.com"),
        ("global", "speech.googleapis.com"),
    ],
)
def test_v2_endpoint(service_account_info: dict, location: str, endpoint: str) -> None:
    """Test a V2 model uses the regional endpoint."""
    client = _create_client(service_account_info, "chirp_3", location)
    assert client.api_endpoint == endpoint


def test_v1_endpoint(service_account_info: dict) -> None:
    """Test a V1 model uses the global V1 API."""
    client = _create_client(service_account_info, "command_and_search", "eu")
    assert isinstance(client, speech.SpeechAsyncClient)
    assert client.api_endpoint == "speech.googleapis.com"


async def test_v2_streams_while_speaking(hass: HomeAssistant, fake_google) -> None:
    """Test audio reaches Google before the speech has ended."""
    provider = fake_google.provider("chirp_3")
    fake_google.reply("liga a luz")
    release = asyncio.Event()

    async def speech_stream():
        yield b"ab"
        await fake_google.received_audio.wait()
        release.set()
        yield b"cd"

    result = await provider.async_process_audio_stream(metadata(), speech_stream())

    assert release.is_set()
    assert result.result == SpeechResultState.SUCCESS
    assert result.text == "liga a luz"

    first, *rest = fake_google.calls[0]
    assert first.recognizer == "projects/test-project/locations/eu/recognizers/_"
    config = first.streaming_config.config
    assert config.model == "chirp_3"
    assert list(config.language_codes) == ["pt-PT"]
    decoding = config.explicit_decoding_config
    assert decoding.encoding == decoding.AudioEncoding.LINEAR16
    assert decoding.sample_rate_hertz == 16000
    assert decoding.audio_channel_count == 1
    assert not first.audio
    assert [request.audio for request in rest] == [b"ab", b"cd"]


async def test_v2_opus(hass: HomeAssistant, fake_google) -> None:
    """Test V2 decodes Opus audio."""
    provider = fake_google.provider("chirp_3")
    fake_google.reply("olá")

    await provider.async_process_audio_stream(
        metadata(AudioCodecs.OPUS), audio_stream()
    )

    decoding = fake_google.calls[0][0].streaming_config.config.explicit_decoding_config
    assert decoding.encoding == decoding.AudioEncoding.OGG_OPUS


async def test_v2_joins_results(hass: HomeAssistant, fake_google) -> None:
    """Test every part of a long sentence is kept."""
    provider = fake_google.provider("chirp_3")
    fake_google.reply("liga a luz", " da sala")

    result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.text == "liga a luz da sala"


async def test_large_chunks_are_split(hass: HomeAssistant, fake_google) -> None:
    """Test no request is over the size limit of the API."""
    provider = fake_google.provider("chirp_3")
    fake_google.reply("olá")

    async def large_stream():
        yield bytes(MAX_REQUEST_AUDIO * 2 + 1)

    await provider.async_process_audio_stream(metadata(), large_stream())

    sizes = [len(request.audio) for request in fake_google.calls[0][1:]]
    assert sizes == [MAX_REQUEST_AUDIO, MAX_REQUEST_AUDIO, 1]


async def test_v2_no_speech(hass: HomeAssistant, fake_google) -> None:
    """Test V2 reports an error when nothing was recognized."""
    provider = fake_google.provider("chirp_3")
    fake_google.reply()

    result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.result == SpeechResultState.ERROR
    assert result.text is None


async def test_retry_sends_the_whole_audio(hass: HomeAssistant, fake_google) -> None:
    """Test a stream that fails halfway is sent again from the start."""
    provider = fake_google.provider("chirp_3")
    fake_google.fail(grpc.StatusCode.UNAVAILABLE, after_requests=2)
    fake_google.reply("liga a luz")

    async def speech_stream():
        yield b"ab"
        await fake_google.received_audio.wait()
        yield b"cd"
        yield b"ef"

    result = await provider.async_process_audio_stream(metadata(), speech_stream())

    assert result.text == "liga a luz"
    assert len(fake_google.calls) == 2
    first, *rest = fake_google.calls[1]
    assert first.streaming_config.config.model == "chirp_3"
    assert b"".join(request.audio for request in rest) == b"abcdef"


async def test_gives_up_after_retries(hass: HomeAssistant, fake_google) -> None:
    """Test a persistent outage ends in an error result."""
    provider = fake_google.provider("chirp_3")
    for _ in range(ATTEMPTS):
        fake_google.fail(grpc.StatusCode.UNAVAILABLE)

    result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.result == SpeechResultState.ERROR
    assert len(fake_google.calls) == ATTEMPTS


async def test_no_retry_on_permanent_error(hass: HomeAssistant, fake_google) -> None:
    """Test a rejected request is reported without trying again."""
    provider = fake_google.provider("chirp_3")
    fake_google.fail(grpc.StatusCode.PERMISSION_DENIED)

    result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.result == SpeechResultState.ERROR
    assert len(fake_google.calls) == 1


async def test_timeout(hass: HomeAssistant, fake_google) -> None:
    """Test Google not answering ends in an error result."""
    provider = fake_google.provider("chirp_3")
    fake_google.reply("olá", hang=True)

    with patch("custom_components.google_cloud_stt.stt.TIMEOUT", 0.1):
        result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.result == SpeechResultState.ERROR


async def test_v1_streams(hass: HomeAssistant, fake_google) -> None:
    """Test a V1 model streams through the V1 API."""
    provider = fake_google.provider("command_and_search")
    fake_google.reply("olá")

    result = await provider.async_process_audio_stream(metadata(), audio_stream())

    assert result.text == "olá"
    first, *rest = fake_google.calls[0]
    config = first.streaming_config.config
    assert config.model == "command_and_search"
    assert config.language_code == "pt-PT"
    assert [request.audio_content for request in rest] == [b"ab", b"cd"]


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
