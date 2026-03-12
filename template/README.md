# Voice Agent for Banking Customer Support
This folder contains a locally-run voice AI agent connected to a single SLM that was fine-tuned with Oumi.

Imagine you are calling your bank’s customer support line. The SLM classifies the caller query into one of a number of categories to determine where to route the call or what additional questions to ask. In our example, a fixed response is spoken back to the caller based on the classification of their intent.

This example illustrates all the steps required for a Voice Agent:

* a pipeline for STT, LLM inference, and TTS; and,
* an “agent” with a single deterministic step.

## Installation
Due to library incompatibilities, it’s important to fix the versions to known working ones. My setup works for Mac but can be easily adapted for Windows and Linux:
```bash
conda create --name pipecat python=3.12.12
conda activate pipecat
git clone https://github.com/oumi-ai/hack-with-oumi
cd hack-with-oumi/template/server
pip install -r requirements.txt
```
Download and cache the TTS model in advance to avoid any delays in the pipeline when it is starting for the first time:
```bash
mlx-audio.generate --model "mlx-community/Kokoro-82M-bf16" --text "Hello, I'm Pipecat!" --output "output.wav"
```

## Running Agent

### Start inference server
The agent makes use of a single model that is served locally by vLLM-MLX via an OpenAI-compatible API. (Read the Oumi docs to learn how to fine-tune models with Oumi.) Install vLLM-MLX or another service for local inference. On my machine, the command to launch vLLM-MLX is:
```bash
vllm-mlx serve stefanwebb/banking77-intent-classifier-mlx --port 1234
```
This will launch a local web server for our SLM at `http://127.0.0.1:1234/v1/chat/completions`. Open a new tab in your terminal window in the same directory.

### Start Pipecat server
Pipecat handles the audio parts of our voice agent as well as connecting that to the LLM-based part of the agent. From the project directory:
```bash
cd template/server
python server.py
```
After the first run and the models are cached, you can run with `HF_HUB_OFFLINE=1 python server.py` to speed up launch.

### Start Pipecat client
The Pipecat client handles the user interface to the voice agent, passes audio from the microphone to the server, receives and plays audio back from the server, and is responsible for other communication with the server.

We use a default React frontend from [voice-ui-kit](https://github.com/pipecat-ai/voice-ui-kit). From the project directory:
```bash
cd template/client
npm i
npm run dev
```
Then navigate to the given URL for the frontend in your browser. If you have set up everything correctly, you should be able to ask the service agent banking support questions and have it respond with a categorization (see video above).