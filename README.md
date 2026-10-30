# Google Cloud Speech-To-Text for Home Assistant

[![](https://img.shields.io/github/release/luisnarquel/ha-google-cloud-stt/all.svg?style=for-the-badge)](https://github.com/luisnarquel/ha-google-cloud-stt/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![](https://img.shields.io/badge/MAINTAINER-%40chatziko-red?style=for-the-badge)](https://github.com/chatziko)
[![](https://img.shields.io/badge/COMMUNITY-FORUM-success?style=for-the-badge)](https://community.home-assistant.io)


This integration allows to use [Google Cloud Speech-to-Text](https://cloud.google.com/speech-to-text) in Home Assistant.

This is a personal fork of [chatziko/ha-google-cloud-stt](https://github.com/chatziko/ha-google-cloud-stt) that adds support for the V2 API and Chirp models. All credit for the original integration goes to its authors.

## Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=chatziko&repository=ha-google-cloud-stt&category=integration)

You can install this integration via [HACS](https://hacs.xyz/). Click on the badge above or go to HACS / Integrations / Three-dots menu / Custom repositories
and add:
- Repository: `https://github.com/luisnarquel/ha-google-cloud-stt`
- Category: Integration

Then install the "Google Cloud Speech-To-Text" integration.


## Configure

To use it you need to configure a Google Cloud project, following the same instructions as the
[Google Cloud Text-to-Speech](https://www.home-assistant.io/integrations/google_cloud) integration.
Then place the JSON file with the API key you downloaded in the `config` folder.

Next add the integration to your Home Assistant instance.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=google_cloud_stt)

After enabling the integration, you can configure a [Voice Assistant](https://www.home-assistant.io/blog/2023/04/27/year-of-the-voice-chapter-2/#composing-voice-assistants)
to use it by selecting `Google Cloud` in the "Speech-to-text" option.

The supported languages are listed [here](https://cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages).
The list of available models is avaiable [here](https://cloud.google.com/speech-to-text/docs/speech-to-text-requests#select-model). The default model
is `command_and_search`, since it is available in most languages and should perform well in home automation tasks.

### V1 and V2 API

The API version follows from the model selected in the integration options:
- `chirp_3`, `chirp_2`, `long`, `short`, `telephony` and `telephony_short` use V2 of Google Cloud Speech-to-Text.
- All other models use V1 (it is available in more languages and has a free tier).

V2 models also use the `Location` option. Each model and language is only available in
[some locations](https://cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages), for example `chirp_3` is
available in `eu` and `us`.

V2 checks permissions on the Google Cloud project, so unlike V1 the service account needs a role that
grants `speech.recognizers.recognize`, such as Cloud Speech Client (`roles/speech.client`).


## FAQ

#### How much does it cost to use Google Cloud Speech-To-Text?

At the time of writing the pricing of Google Cloud Speech-to-Text V1 is:
- Free for the first 60 minutes / month.
- $0.024 / minute after the first 60 minutes/month.

Check Google's [pricing table](https://cloud.google.com/speech-to-text/pricing#pricing_table) for up-to-date information.