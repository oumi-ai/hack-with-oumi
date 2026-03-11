import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import Dict

# Add local pipecat to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pipecat", "src"))

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from loguru import logger

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v2 import LocalSmartTurnAnalyzerV2
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.openai.llm import OpenAILLMService

from pipecat.services.whisper.stt import WhisperSTTServiceMLX, MLXModel
from pipecat.transports.base_transport import TransportParams
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.processors.aggregators.llm_response import LLMUserAggregatorParams

from pipecat.frames.frames import LLMTextFrame, LLMMessagesAppendFrame, TTSSpeakFrame, TextFrame

from agent import RewriteTextFrames

from tts_mlx_isolated import TTSMLXIsolated

load_dotenv(override=True)

app = FastAPI()

pcs_map: Dict[str, SmallWebRTCConnection] = {}

# ice_servers = [IceServer()]


SYSTEM_INSTRUCTION = """You are a banking intent classifier. Classify the user's query into one of  77 banking intents (output is a single integer ID).

IDs:

0: activate_my_card
1: age_limit
2: apple_pay_or_google_pay
3: atm_support
4: automatic_top_up
5: balance_not_updated_after_bank_transfer
6: balance_not_updated_after_cheque_or_cash_deposit
7: beneficiary_not_allowed
8: cancel_transfer
9: card_about_to_expire
10: card_acceptance
11: card_arrival
12: card_delivery_estimate
13: card_linking
14: card_not_working
15: card_payment_fee_charged
16: card_payment_not_recognised
17: card_payment_wrong_exchange_rate
18: card_swallowed
19: cash_withdrawal_charge
20: cash_withdrawal_not_recognised
21: change_pin
22: compromised_card
23: contactless_not_working
24: country_support
25: declined_card_payment
26: declined_cash_withdrawal
27: declined_transfer
28: direct_debit_payment_not_recognised
29: disposable_card_limits
30: edit_personal_details
31: exchange_charge
32: exchange_rate
33: exchange_via_app
34: extra_charge_on_statement
35: failed_transfer
36: fiat_currency_support
37: get_disposable_virtual_card
38: get_physical_card
39: getting_spare_card
40: getting_virtual_card
41: lost_or_stolen_card
42: lost_or_stolen_phone
43: order_physical_card
44: passcode_forgotten
45: pending_card_payment
46: pending_cash_withdrawal
47: pending_top_up
48: pending_transfer
49: pin_blocked
50: receiving_money
51: Refund_not_showing_up
52: request_refund
53: reverted_card_payment?
54: supported_cards_and_currencies
55: terminate_account
56: top_up_by_bank_transfer_charge
57: top_up_by_card_charge
58: top_up_by_cash_or_cheque
59: top_up_failed
60: top_up_limits
61: top_up_reverted
62: topping_up_by_card
63: transaction_charged_twice
64: transfer_fee_charged
65: transfer_into_account
66: transfer_not_received_by_recipient
67: transfer_timing
68: unable_to_verify_identity
69: verify_my_identity
70: verify_source_of_funds
71: verify_top_up
72: virtual_card_not_working
73: visa_or_mastercard
74: why_verify_identity
75: wrong_amount_of_cash_received
76: wrong_exchange_rate_for_cash_withdrawal

CRITICAL INSTRUCTIONS:
1. Choose exactly one integer ID (0-76).
2. Reply with ONLY that number. No words, no reasoning, no punctuation.
Examples: 0, 1, 42

Remember: Respond with ONLY the numeric ID, nothing else."""


async def run_bot(webrtc_connection):
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV2(
                smart_turn_model_path="",  # Download from HuggingFace
                params=SmartTurnParams(),
            ),
        ),
    )

    rewrite_text = RewriteTextFrames()

    stt = WhisperSTTServiceMLX(model=MLXModel.LARGE_V3_TURBO_Q4)

    tts = TTSMLXIsolated(model="mlx-community/Kokoro-82M-bf16", voice="af_heart", sample_rate=24000)
    # tts = TTSMLXIsolated(model="Marvis-AI/marvis-tts-250m-v0.1", voice=None)

    llm = OpenAILLMService(
        api_key="dummyKey",
        model="default",
        # model="gemma-3n-e4b-it-text",  # Small model. Uses ~4GB of RAM.
        # model="google/gemma-3-12b",  # Medium-sized model. Uses ~8.5GB of RAM.
        # model="mlx-community/Qwen3-235B-A22B-Instruct-2507-3bit-DWQ", # Large model. Uses ~110GB of RAM!
        base_url="http://127.0.0.1:1234/v1", # "http://127.0.0.1:1234/v1",
        max_tokens=4096,
    )

    context = OpenAILLMContext(
        [
            {
                "role": "user",
                "content": SYSTEM_INSTRUCTION,
            }
        ],
    )
    context_aggregator = llm.create_context_aggregator(
        context,
        # Whisper local service isn't streaming, so it delivers the full text all at
        # once, after the UserStoppedSpeaking frame. Set aggregation_timeout to a
        # a de minimus value since we don't expect any transcript aggregation to be
        # necessary.
        user_params=LLMUserAggregatorParams(aggregation_timeout=0.05),
    )

    #
    # RTVI events for Pipecat client UI
    #
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            rtvi,
            context_aggregator.user(),
            llm,
            rewrite_text,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    first_message_json = {
        "role": "assistant",
        "content": "I'm Banksy, a banking customer support agent. How can I help?",
    }

    first_message = "I'm Banksy, a banking customer support agent. How can I help?"

    # Example: Bot speaks first when pipeline starts
    # @rtvi.event_handler("on_client_ready")
    # async def on_client_ready(rtvi):
    #     # Trigger a response
    #     # await task.queue_frames([LLMRunFrame()])
    #     await rtvi.set_bot_ready()
    #     await task.queue_frames([LLMMessagesAppendFrame([first_message], run_llm=False)])

    @rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        await rtvi.set_bot_ready()

        await task.queue_frames([TTSSpeakFrame(first_message, append_to_context=True)])
        await task.queue_frames([LLMTextFrame(first_message)])
        # await task.queue_frames([LLMMessagesAppendFrame([first_message_json], run_llm=False)])
        # await task.queue_frames([TextFrame(first_message, skip_tts=True)])
        # await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        print(f"Participant joined: {participant}")
        await transport.capture_participant_transcription(participant["id"])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        print(f"Participant left: {participant}")
        await task.cancel()

    @transport.event_handler("on_app_message")
    async def on_app_message(transport, message, sender):
        print(f"Message from {sender}: {message}")

    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)


@app.post("/api/offer")
async def offer(request: dict, background_tasks: BackgroundTasks):
    pc_id = request.get("pc_id")

    if pc_id and pc_id in pcs_map:
        pipecat_connection = pcs_map[pc_id]
        logger.info(f"Reusing existing connection for pc_id: {pc_id}")
        await pipecat_connection.renegotiate(
            sdp=request["sdp"],
            type=request["type"],
            restart_pc=request.get("restart_pc", False),
        )
    else:
        pipecat_connection = SmallWebRTCConnection()
        await pipecat_connection.initialize(sdp=request["sdp"], type=request["type"])

        @pipecat_connection.event_handler("closed")
        async def handle_disconnected(webrtc_connection: SmallWebRTCConnection):
            logger.info(f"Discarding peer connection for pc_id: {webrtc_connection.pc_id}")
            pcs_map.pop(webrtc_connection.pc_id, None)

        # Run example function with SmallWebRTC transport arguments.
        background_tasks.add_task(run_bot, pipecat_connection)

    answer = pipecat_connection.get_answer()
    # Updating the peer connection inside the map
    pcs_map[answer["pc_id"]] = pipecat_connection

    return answer


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # Run app
    coros = [pc.disconnect() for pc in pcs_map.values()]
    await asyncio.gather(*coros)
    pcs_map.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Bot Runner")
    parser.add_argument(
        "--host", default="localhost", help="Host for HTTP server (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=7860, help="Port for HTTP server (default: 7860)"
    )
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
