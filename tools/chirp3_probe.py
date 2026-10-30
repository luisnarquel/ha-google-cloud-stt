#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-cloud-speech==2.40.0"]
# ///
"""Check that a model and language are usable from a Google Cloud project.

    tools/chirp3_probe.py KEY.json [--wav AUDIO.wav] [--location eu]
                          [--model chirp_3] [--language pt-PT]

Without --wav it sends one second of silence (an empty transcript still proves
the model is available). The key is only used to authenticate with Google.
Exits 0 when the model answered, 1 otherwise.
"""

import argparse
import json
import sys
import time
import wave

from google.api_core import exceptions
from google.api_core.client_options import ClientOptions
from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("key", help="service account JSON file")
parser.add_argument("--wav", help="16-bit PCM mono WAV to transcribe")
parser.add_argument("--location", default="eu")
parser.add_argument("--model", default="chirp_3")
parser.add_argument("--language", default="pt-PT")
args = parser.parse_args()

with open(args.key) as f:
    info = json.load(f)
project = info["project_id"]

if args.wav:
    with wave.open(args.wav) as w:
        if (w.getsampwidth(), w.getnchannels()) != (2, 1):
            sys.exit("WAV must be 16-bit PCM mono")
        rate, audio = w.getframerate(), w.readframes(w.getnframes())
else:
    rate, audio = 16000, bytes(32000)

endpoint = (
    "speech.googleapis.com"
    if args.location == "global"
    else f"{args.location}-speech.googleapis.com"
)
client = speech_v2.SpeechClient.from_service_account_info(
    info, client_options=ClientOptions(api_endpoint=endpoint)
)
request = cloud_speech.RecognizeRequest(
    recognizer=f"projects/{project}/locations/{args.location}/recognizers/_",
    config=cloud_speech.RecognitionConfig(
        explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=rate,
            audio_channel_count=1,
        ),
        language_codes=[args.language],
        model=args.model,
    ),
    content=audio,
)

print(f"project={project} endpoint={endpoint} model={args.model} language={args.language}")
start = time.monotonic()
try:
    response = client.recognize(request=request, timeout=30)
except exceptions.PermissionDenied as err:
    print(f"FAIL permission denied (API disabled, or the service account lacks a Speech role): {err.message}")
    sys.exit(1)
except exceptions.InvalidArgument as err:
    print(f"FAIL rejected, likely this model/language/location combination: {err.message}")
    sys.exit(1)
except exceptions.GoogleAPICallError as err:
    print(f"FAIL {type(err).__name__}: {err.message}")
    sys.exit(1)

elapsed = time.monotonic() - start
text = " ".join(
    result.alternatives[0].transcript.strip()
    for result in response.results
    if result.alternatives
)
print(f"OK available, answered in {elapsed:.2f}s, billed {response.metadata.total_billed_duration.total_seconds():g}s")
print(f"transcript: {text!r}")
