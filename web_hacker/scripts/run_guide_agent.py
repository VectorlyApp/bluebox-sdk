#!/usr/bin/env python3
"""
web_hacker/scripts/run_guide_agent.py

Terminal-based chat interface for the Guide Agent.

Usage:
    python -m web_hacker.scripts.run_guide_agent
"""

import sys

from web_hacker.agents.guide_agent.guide_agent import GuideAgent
from web_hacker.data_models.llms.interaction import (
    ChatLite,
    ChatMessageType,
    ChatThreadLite,
    EmittedChatMessage,
)
from web_hacker.data_models.llms.vendors import OpenAIModel
from web_hacker.config import Config
from web_hacker.utils.exceptions import ApiKeyNotFoundError
from web_hacker.utils.logger import get_logger

logger = get_logger(__name__)


class TerminalGuideChat:
    """Terminal interface for Guide Agent."""

    def __init__(self) -> None:
        self.agent = GuideAgent(
            emit_message_callable=self._handle_emitted_message,
            persist_chat_callable=self._persist_chat,
            persist_chat_thread_callable=self._persist_chat_thread,
            llm_model=OpenAIModel.GPT_5_MINI,
        )

    def _persist_chat(self, chat: ChatLite) -> None:
        """Persist a ChatLite object. In the future, this will POST to DynamoDB."""
        logger.debug("Would persist ChatLite: %s", chat.id)

    def _persist_chat_thread(self, thread: ChatThreadLite) -> None:
        """Persist a ChatThreadLite object. In the future, this will POST/PATCH to DynamoDB."""
        logger.debug("Would persist ChatThreadLite: %s", thread.id)

    def _handle_emitted_message(self, message: EmittedChatMessage) -> None:
        """Handle messages emitted by the agent."""
        if message.type == ChatMessageType.CHAT_RESPONSE:
            if message.content:
                print(f"\nAssistant: {message.content}")

        elif message.type == ChatMessageType.TOOL_INVOCATION_REQUEST:
            print("\n" + "=" * 60)
            print("TOOL INVOCATION REQUEST")
            if message.tool_invocation:
                print(f"Tool: {message.tool_invocation.tool_name}")
                print(f"Arguments: {message.tool_invocation.tool_arguments}")
            print("=" * 60)
            print("Type 'yes' to confirm or 'no' to deny:")

        elif message.type == ChatMessageType.TOOL_INVOCATION_RESULT:
            print("\n" + "-" * 60)
            if message.tool_result:
                print(f"Tool executed successfully!")
                print(f"Result: {message.tool_result}")
            elif message.error:
                print(f"Tool execution failed: {message.error}")
            elif message.content:
                print(message.content)
            print("-" * 60)

        elif message.type == ChatMessageType.ERROR:
            print(f"\nError: {message.error}")

    def run(self) -> None:
        """Run the terminal chat loop."""
        print("=" * 60)
        print("Welcome to the Web Hacker Guide Agent")
        print("I'll help you define your web automation routine.")
        print("Type 'quit' or 'exit' to end the conversation.")
        print("=" * 60)
        print()

        while True:
            try:
                # Get user input
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit"):
                    print("Goodbye!")
                    sys.exit(0)

                # Handle tool confirmation
                if self.agent.has_pending_tool_invocation:
                    pending = self.agent.get_thread().pending_tool_invocation
                    if pending:
                        if user_input.lower() in ("yes", "y", "confirm"):
                            self.agent.confirm_tool_invocation(pending.invocation_id)
                        elif user_input.lower() in ("no", "n", "deny"):
                            self.agent.deny_tool_invocation(pending.invocation_id, "User denied")
                        else:
                            print("Please type 'yes' to confirm or 'no' to deny.")
                        continue

                # Process message
                self.agent.process_user_message(user_input)

            except KeyboardInterrupt:
                print("\nGoodbye!")
                sys.exit(0)
            except Exception as e:
                logger.exception("Error in chat loop: %s", e)
                print(f"\nAn error occurred: {e}")


def main() -> None:
    """Entry point for the terminal chat."""
    # Ensure OpenAI API key is set
    if Config.OPENAI_API_KEY is None:
        logger.error("OPENAI_API_KEY is not set")
        raise ApiKeyNotFoundError("OPENAI_API_KEY is not set")

    chat = TerminalGuideChat()
    chat.run()


if __name__ == "__main__":
    main()
