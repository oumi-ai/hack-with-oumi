from loguru import logger

from pipecat.frames.frames import Frame, LLMTextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import LLMTextFrame, LLMMessagesAppendFrame, TTSSpeakFrame, TextFrame

with open('./template/server/banking77-labels.txt', 'r') as file:
    lines = file.readlines()

labels = [l.split('\t')[1].strip().replace('_', ' ') for l in lines]

from loguru import logger

class RewriteTextFrames(FrameProcessor):
    """
    Agent intercepts and transforms text
    """

    # We'll do our own aggregating
    llm_response = []

    def __init__(self):
        super().__init__()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not isinstance(frame, InputAudioRawFrame):
            logger.info(f"Frame type: {type(frame)}")

        if isinstance(frame, LLMFullResponseStartFrame):
            self.llm_response.clear()

        if isinstance(frame, LLMTextFrame):
            if frame.text.isdigit():
                self.llm_response.append(frame.text)
                frame.append_to_context = False
                return
            
        if isinstance(frame, LLMFullResponseEndFrame):
            full_response = "".join(self.llm_response).strip()

            logger.info(f"Full response: {full_response}")

            # frame.text = "test"
            if full_response.isdigit():
                transformed_reply = f") I think you want help with: {labels[int(full_response)]}"
                logger.info(f"{transformed_reply}")

                response_frame = TTSSpeakFrame(transformed_reply, append_to_context=True)
                await self.push_frame(response_frame, direction)

                await self.push_frame(LLMTextFrame(transformed_reply), direction)
                return

        if hasattr(frame, "text") and frame.text.isdigit():
            gothere = True

        await self.push_frame(frame, direction)