import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dotenv import load_dotenv
from enum import StrEnum
from pydantic import BaseModel, Field, ConfigDict
from openai import OpenAI

load_dotenv()

# dedicated logger for summarization with console output
summary_logger = logging.getLogger("llm_context_manager")
summary_logger.setLevel(logging.DEBUG)

# add console handler if not already present
if not summary_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # INFO level for console (DEBUG is too noisy)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    summary_logger.addHandler(console_handler)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    role: MessageRole = Field(description="The role of the message sender")
    content: str = Field(description="The content of the message")


class Summary(BaseModel):
    summary: str = Field(description="The summary of the conversation")
    anchor_message_idx: int = Field(description="The anchor idx of the conversation (index into messages list)")


class LLMContextManager(BaseModel):
    """
    Manages LLM context with automatic summarization and draining.

    Flow:
    1. When T_current > T_drain (after LLM response): start async summarization
    2. When T_current > T_max: drain context, reset last_response_id, update anchor
    """

    # openai models
    chat_model: str = Field(default="gpt-5.1", description="The model to use for the chat")
    summary_model: str = Field(default="gpt-5.1", description="The model to use for the summary")

    # context window hyper parameters (lowered for testing - see comments for production values)
    # Production values: T_max=600_000, T_drain=400_000, T_target=250_000, T_summary_max=100_000
    T_max: int = Field(default=50_000, description="Maximum chars before forced drain (~12k tokens)")
    T_drain: int = Field(default=30_000, description="Threshold to start async summarization (~8k tokens)")
    T_target: int = Field(default=18_000, description="Target chars after drain (~5k tokens)")
    T_summary_max: int = Field(default=10_000, description="Maximum chars for summary (~2.5k tokens)")
    max_message_size: int = Field(default=300_000, description="Maximum chars per single message (~75k tokens)")

    # session state
    client: OpenAI = Field(default_factory=lambda: OpenAI(api_key=os.getenv("OPENAI_API_KEY")))
    T_current: int = Field(default=0, description="Current chars in context window")
    messages: list[Message] = Field(default_factory=list, description="All messages in conversation")
    summaries: list[Summary] = Field(default_factory=list, description="Summaries at various anchor points")
    current_anchor_idx: int | None = Field(default=None, description="Current anchor message index")
    last_response_id: str | None = Field(default=None, description="Last OpenAI response id for continuation")

    # async summarization state
    summarization_in_progress: bool = False
    draining: bool = False  # prevents new summarization during drain
    summarization_done: threading.Event = Field(default_factory=threading.Event)
    summarization_lock: threading.Lock = Field(default_factory=threading.Lock)
    executor: ThreadPoolExecutor = Field(default_factory=lambda: ThreadPoolExecutor(max_workers=1))

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def start_session(self, system_prompt: str) -> None:
        """Initialize a new session with a system prompt."""
        if len(system_prompt) > self.T_target // 2:
            raise ValueError("System prompt too long - must fit comfortably in target context")

        self.messages = [Message(role=MessageRole.SYSTEM, content=system_prompt)]
        self.T_current = len(system_prompt)
        self.summaries = []
        self.current_anchor_idx = None
        self.last_response_id = None

        summary_logger.info(
            f"[SESSION] Started new session | system_prompt={len(system_prompt):,} chars | "
            f"T_drain={self.T_drain:,} | T_max={self.T_max:,} | T_target={self.T_target:,}"
        )

    def get_response(self, user_message: str) -> str:
        """
        Get a response from the LLM for the user message.
        Handles context management automatically.

        Raises:
            ValueError: If message exceeds max_message_size
        """
        # enforce max message size - must fit in T_max with room for response
        max_message_size = self.max_message_size
        if len(user_message) > max_message_size:
            raise ValueError(
                f"Message too large: {len(user_message):,} chars exceeds limit of {max_message_size:,} chars. "
                f"Please split into smaller messages or summarize the content."
            )

        # add user message
        self.messages.append(Message(role=MessageRole.USER, content=user_message))
        self.T_current += len(user_message)

        # check if we need to drain BEFORE calling LLM
        if self.T_current > self.T_max:
            self._drain_context()

        # build input and call LLM
        llm_input = self._build_llm_input()

        if self.last_response_id is not None:
            # continuation mode - use responses API with previous_response_id
            response = self.client.responses.create(
                model=self.chat_model,
                previous_response_id=self.last_response_id,
                input=llm_input
            )
        else:
            # fresh context - use responses API without previous_response_id
            response = self.client.responses.create(
                model=self.chat_model,
                input=llm_input
            )

        # extract response content (responses API format)
        assistant_content = response.output_text
        self.last_response_id = response.id

        # add assistant message to history
        self.messages.append(Message(role=MessageRole.ASSISTANT, content=assistant_content))
        self.T_current += len(assistant_content)

        # check if we need to start async summarization (above drain line)
        if self.T_current > self.T_drain:
            self._maybe_start_async_summarization()

        return assistant_content

    def _build_llm_input(self) -> list[dict]:
        """Build the input messages for the LLM based on current state."""
        # fresh session - send all messages
        if self.last_response_id is None and self.current_anchor_idx is None:
            return [{"role": m.role.value, "content": m.content} for m in self.messages]

        # we have a last_response_id - just send the new user message
        if self.last_response_id is not None:
            # only send the latest user message (continuation mode)
            return [{"role": self.messages[-1].role.value, "content": self.messages[-1].content}]

        # context was drained (last_response_id is None) but we have an anchor
        # need to rebuild: system + summary + messages after anchor
        input_messages = []

        # always include system prompt
        assert self.messages[0].role == MessageRole.SYSTEM
        input_messages.append({"role": "system", "content": self.messages[0].content})

        # add summary as context
        if self.current_anchor_idx is not None:
            summary_text = self._get_summary_for_anchor(self.current_anchor_idx)
            if summary_text:
                summary_context = (
                    f"<conversation_summary>\n{summary_text}\n</conversation_summary>\n\n"
                    "The above is a summary of our conversation so far. "
                    "Continue naturally without explicitly referencing this summary."
                )
                input_messages.append({"role": "system", "content": summary_context})

            # add messages after anchor
            for msg in self.messages[self.current_anchor_idx + 1:]:
                input_messages.append({"role": msg.role.value, "content": msg.content})
        else:
            # no anchor, just add all messages after system
            for msg in self.messages[1:]:
                input_messages.append({"role": msg.role.value, "content": msg.content})

        return input_messages

    def force_drain(self) -> None:
        """Public method to force a context drain regardless of current size."""
        self._drain_context()

    def _calculate_drain_anchor(self) -> tuple[int, int, int]:
        """
        Calculate where to set the anchor during drain.

        Returns:
            tuple of (anchor_idx, overhead, accumulated_size)
        """
        system_prompt_size = len(self.messages[0].content)
        summary_size = len(self._get_summary_for_anchor(len(self.messages) - 1) or "")
        overhead = system_prompt_size + summary_size + 500  # buffer for summary wrapper

        available = self.T_target - overhead
        accumulated = 0
        new_anchor_idx = len(self.messages) - 1

        # walk backwards to find how many recent messages we can keep
        for i in range(len(self.messages) - 1, 0, -1):  # skip system prompt at 0
            msg_size = len(self.messages[i].content)
            if accumulated + msg_size > available:
                new_anchor_idx = i
                break
            accumulated += msg_size
            new_anchor_idx = i - 1

        return max(new_anchor_idx, 1), overhead, accumulated

    def _drain_context(self) -> None:
        """
        Drain the context when T_current > T_max.
        Reset last_response_id and update anchor to keep context below T_target.
        """
        pre_drain_size = self.T_current
        summary_logger.warning(
            f"[DRAIN] Starting drain | T_current={self.T_current:,} > T_max={self.T_max:,} | "
            f"target={self.T_target:,} | msgs={len(self.messages)}"
        )

        # set draining flag - this signals any in-progress summarization to stop early
        with self.summarization_lock:
            self.draining = True
            was_in_progress = self.summarization_in_progress

        if was_in_progress:
            # Don't wait - the draining flag will cause the worker to stop early
            # We'll use whatever summary is already in self.summaries
            summary_logger.info("[DRAIN] Async summarization was in progress - will use existing summary")

        try:
            # First calculate where we'd drain to with current summary
            tentative_anchor, _, _ = self._calculate_drain_anchor()

            # Check if existing summary covers up to where we need to drain
            last_summary_anchor = self.summaries[-1].anchor_message_idx if self.summaries else -1

            if last_summary_anchor < tentative_anchor:
                # Existing summary doesn't cover what we're about to delete - need to update it
                # This prevents losing messages between last_summary_anchor and tentative_anchor
                summary_logger.warning(
                    f"[DRAIN] Summary anchor ({last_summary_anchor}) < drain anchor ({tentative_anchor}) - "
                    f"forcing sync summary to avoid losing messages"
                )
                self._generate_summary_sync(force=True)
            else:
                summary_logger.info(
                    f"[DRAIN] Existing summary (anchor={last_summary_anchor}) covers drain target ({tentative_anchor})"
                )

            # Recalculate final anchor (summary size may have changed)
            new_anchor_idx, overhead, accumulated = self._calculate_drain_anchor()

            # update state
            self.current_anchor_idx = new_anchor_idx
            self.last_response_id = None  # force fresh context on next call

            # mark drained messages as [deleted] to free memory but preserve indices
            deleted_count = 0
            for i in range(1, self.current_anchor_idx + 1):
                self.messages[i] = Message(role=self.messages[i].role, content="[deleted]")
                deleted_count += 1

            # recalculate T_current based on what we'll actually send
            self.T_current = overhead + accumulated

            summary_logger.warning(
                f"[DRAIN] Complete | {pre_drain_size:,} → {self.T_current:,} chars "
                f"(freed {pre_drain_size - self.T_current:,}) | "
                f"deleted {deleted_count} msgs | new_anchor={new_anchor_idx}"
            )

        finally:
            # clear draining flag
            with self.summarization_lock:
                self.draining = False

    def _maybe_start_async_summarization(self) -> None:
        """Start async summarization if not already running or draining."""
        with self.summarization_lock:
            if self.summarization_in_progress:
                summary_logger.debug("[SUMMARIZE] Skipping - already in progress")
                return
            if self.draining:
                summary_logger.debug("[SUMMARIZE] Skipping - drain in progress")
                return
            self.summarization_in_progress = True
            self.summarization_done.clear()  # reset event for new summarization

        summary_logger.info("[SUMMARIZE] Starting async summarization in background thread...")
        # run in background thread
        self.executor.submit(self._async_summarization_worker)

    def _async_summarization_worker(self) -> None:
        """Background worker for summarization."""
        import time
        start_time = time.time()
        summary_logger.info("[SUMMARIZE] Background worker started")
        try:
            self._generate_summary_sync()
            elapsed = time.time() - start_time
            summary_logger.info(f"[SUMMARIZE] Background worker completed in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - start_time
            summary_logger.error(f"[SUMMARIZE] Background worker failed after {elapsed:.1f}s: {e}", exc_info=True)
        finally:
            with self.summarization_lock:
                self.summarization_in_progress = False
            self.summarization_done.set()  # signal completion to any waiting threads

    def _generate_summary_sync(self, force: bool = False) -> None:
        """Generate a summary synchronously, with progressive updates and early exit on drain.

        Args:
            force: If True, bypass the draining check (used when drain itself needs a summary)
        """
        mode = "FORCED" if force else "ASYNC"
        summary_logger.info(f"[SUMMARY-GEN] Starting ({mode} mode)")

        # check if drain requested before even starting (unless forced by drain itself)
        if self.draining and not force:
            summary_logger.debug("[SUMMARY-GEN] Drain in progress, skipping")
            return

        # determine what to summarize
        if self.summaries:
            # summarize from AFTER last summary's anchor (avoid re-summarizing anchor message)
            last_summary = self.summaries[-1]
            start_idx = last_summary.anchor_message_idx + 1  # +1 to avoid overlap
            previous_summary = last_summary.summary
            summary_logger.info(
                f"[SUMMARY-GEN] Updating existing summary | "
                f"prev_anchor={last_summary.anchor_message_idx} | prev_size={len(previous_summary):,} chars"
            )
        else:
            # first summary - summarize from start (skip system prompt)
            start_idx = 1
            previous_summary = None
            summary_logger.info("[SUMMARY-GEN] Creating first summary")

        end_idx = len(self.messages) - 1

        # nothing new to summarize
        if end_idx <= start_idx:
            summary_logger.debug(f"[SUMMARY-GEN] Nothing to summarize: end_idx={end_idx}, start_idx={start_idx}")
            return

        # build messages to summarize (keep as structured list, not text blob)
        messages_to_summarize = self.messages[start_idx:end_idx + 1]
        total_chars = sum(len(m.content) for m in messages_to_summarize)

        summary_logger.info(
            f"[SUMMARY-GEN] Processing {len(messages_to_summarize)} messages ({total_chars:,} chars) | "
            f"range=[{start_idx}:{end_idx}]"
        )

        # use configured max summary size
        max_summary_chars = self.T_summary_max

        # pass structured messages so LLM clearly sees who said what
        summary_logger.info(f"[SUMMARY-GEN] Calling LLM to generate summary (max={max_summary_chars:,} chars)...")
        summary_text, summary_response_id = self._call_summary_llm(messages_to_summarize, previous_summary, max_summary_chars)
        summary_logger.info(f"[SUMMARY-GEN] LLM returned {len(summary_text):,} chars")

        # immediately store/update summary - always have something usable
        self._upsert_summary(end_idx, summary_text)
        summary_logger.info(f"[SUMMARY-GEN] Stored summary (anchor={end_idx}, size={len(summary_text):,} chars)")

        # iteratively shrink if summary is too large (with early exit on drain)
        # uses continuation mode from the summary call - shrinks just say "too long, shrink it"
        shrink_attempts = 0
        max_shrink_attempts = 3
        current_response_id = summary_response_id  # continue from summary session

        if len(summary_text) > max_summary_chars:
            summary_logger.warning(
                f"[SUMMARY-GEN] Summary exceeds max ({len(summary_text):,} > {max_summary_chars:,}) - starting shrink loop"
            )

        while len(summary_text) > max_summary_chars and shrink_attempts < max_shrink_attempts:
            # check for drain before each shrink attempt (unless forced by drain itself)
            if self.draining and not force:
                summary_logger.info(f"[SUMMARY-GEN] Drain requested, stopping shrink early (size={len(summary_text):,} chars)")
                break

            shrink_attempts += 1
            prev_len = len(summary_text)
            reduction_needed = prev_len - max_summary_chars
            reduction_pct = (reduction_needed / prev_len) * 100
            summary_logger.info(
                f"[SUMMARY-GEN] Shrink attempt {shrink_attempts}/{max_shrink_attempts} | "
                f"need to cut {reduction_needed:,} chars ({reduction_pct:.0f}%)"
            )
            target_chars = max_summary_chars - 100  # aim slightly under

            summary_text, current_response_id = self._shrink_summary(
                summary_text, target_chars, current_response_id
            )
            summary_logger.info(f"[SUMMARY-GEN] After shrink: {len(summary_text):,} chars (was {prev_len:,})")

            # if LLM failed to shrink (same size or bigger), hard truncate and stop
            if len(summary_text) >= prev_len:
                summary_logger.warning(f"[SUMMARY-GEN] LLM failed to shrink - hard truncating")
                summary_text = self._hard_truncate_summary(summary_text, target_chars)
                self._upsert_summary(end_idx, summary_text)
                break

            # update summary in place after each shrink
            self._upsert_summary(end_idx, summary_text)

        # final fallback: hard truncate if still too large
        # (skip if draining asynchronously triggered this, but do it if force=True from drain)
        if len(summary_text) > max_summary_chars and (force or not self.draining):
            summary_logger.error(f"[SUMMARY-GEN] Final fallback - hard truncating to {max_summary_chars - 100:,} chars")
            summary_text = self._hard_truncate_summary(summary_text, max_summary_chars - 100)
            self._upsert_summary(end_idx, summary_text)

        summary_logger.info(
            f"[SUMMARY-GEN] Complete | final_size={len(summary_text):,} chars | "
            f"anchor={end_idx} | shrink_attempts={shrink_attempts}"
        )

    def _upsert_summary(self, anchor_idx: int, summary_text: str) -> None:
        """Insert or update a summary for the given anchor index."""
        # check if we already have a summary for this anchor
        for i, s in enumerate(self.summaries):
            if s.anchor_message_idx == anchor_idx:
                self.summaries[i] = Summary(summary=summary_text, anchor_message_idx=anchor_idx)
                return
        # no existing summary for this anchor, append new one
        self.summaries.append(Summary(summary=summary_text, anchor_message_idx=anchor_idx))

    def _get_summary_system_prompt(self, current_timestamp: str) -> str:
        """Return the system prompt for summary generation."""
        return f"""You are a THIRD-PARTY OBSERVER summarizing a conversation between a USER and an AI ASSISTANT.

CRITICAL: You are NOT the assistant in this conversation. You are a separate summarization model.
- The "user" messages you see are from the HUMAN USER
- The "assistant" messages you see are from a DIFFERENT AI (the main chat assistant)
- Your job is to create a summary document that the main assistant can use later to remember what happened

Think of yourself as a note-taker watching someone else's conversation and writing up meeting notes.

CURRENT TIMESTAMP: {current_timestamp}

## Document Structure (STRICT)

```markdown
# Session Memory

## Objectives
<!-- User's goals, updated as understanding evolves -->
- [timestamp] objective description

## User Preferences
<!-- Communication style, technical level, tool preferences -->
- [timestamp] preference

## Technical Context
<!-- Languages, frameworks, file paths, function names, error messages, specific values -->
- [timestamp] detail

## Implementation Details
<!-- IMPORTANT code/implementations written by the ASSISTANT -->
<!-- Include: function signatures, key classes, critical snippets, algorithms -->
<!-- Format: brief description + code block -->
- [timestamp] description
  ```language
  code here
  ```

## Bugs & Issues
<!-- Known bugs, errors encountered, issues to fix -->
<!-- Include: error messages, stack traces, reproduction steps -->
- [timestamp] bug description (status: open|investigating|fixed)

## Decisions & Conclusions
<!-- Explicit choices made, problems solved, approaches agreed upon -->
- [timestamp] decision

## Conversation Flow
<!-- Chronological record of topics discussed -->
- [timestamp] topic → outcome

## Active Plan
<!-- Current short-term tasks being worked on -->
- [timestamp] task (status: pending|in_progress|done)

## Backlog
<!-- Longer-term items, future work, things to revisit -->
- [timestamp] item

## Open Questions
<!-- Unresolved items needing user input or further investigation -->
- [timestamp] question
```

## Update Operations
When updating the document, use these operations:
- **ADD**: New item with current timestamp [{current_timestamp}]
- **UPDATE**: Modify existing item, update its timestamp to [{current_timestamp}]
- **REMOVE**: Delete items that are obsolete, resolved, or no longer relevant (no trace needed)
- **PROMOTE**: Move item from Backlog to Active Plan when work begins
- **DEMOTE**: Move item from Active Plan to Backlog if deprioritized
- **RESOLVE**: Move from Open Questions to Decisions when answered

## Rules
1. Every item MUST have a timestamp in [YYYY-MM-DD HH:MM] format
2. Preserve technical details EXACTLY (code, paths, names, values, errors)
3. Keep items concise - one line per item when possible
4. Remove stale/obsolete items aggressively - this is a living document
5. Conversation Flow should capture the narrative arc, not every message
6. Active Plan should have max 5-7 items (move excess to Backlog)
7. Output the COMPLETE updated document, not just changes
8. Implementation Details: preserve important code the ASSISTANT wrote - include function names, key logic, but abbreviate very long code
9. Bugs & Issues: track bugs with status (open/investigating/fixed), include error messages exactly
10. IMPORTANT: Only include sections that have relevant content! Leave out empty sections entirely. Not every conversation needs every section."""

    def _call_summary_llm(self, messages: list[Message], previous_summary: str | None, max_chars: int) -> tuple[str, str]:
        """
        Call LLM to generate or update a structured summary.

        Uses structured message input so the LLM clearly sees who (USER vs ASSISTANT) said what.

        Returns:
            tuple of (summary_text, response_id) for continuation in shrink loop
        """
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Build structured input: replay the conversation as actual messages
        # This makes it crystal clear who said what (no confusion about USER vs ASSISTANT)
        llm_input = []

        if previous_summary:
            # First message: provide existing summary as context
            llm_input.append({
                "role": "user",
                "content": f"""## Current Session Memory
{previous_summary}

---
Below is a transcript of NEW messages from the conversation between the USER and the AI ASSISTANT.
Remember: you are an EXTERNAL OBSERVER - these are not messages to you, they are messages you're summarizing.
After reviewing the transcript, output the UPDATED Session Memory document."""
            })
            llm_input.append({
                "role": "assistant",
                "content": "Understood. I'm an external observer summarizing their conversation. Show me the transcript and I'll update the Session Memory."
            })

        # Add transcript start marker
        llm_input.append({
            "role": "user",
            "content": "=== BEGIN TRANSCRIPT OF USER/ASSISTANT CONVERSATION ==="
        })

        # Add the actual conversation messages - LLM sees real USER/ASSISTANT structure
        # These are presented AS-IS from the original conversation
        for msg in messages:
            # Prefix each message to reinforce it's from the transcript
            prefix = "[TRANSCRIPT - USER SAID]:" if msg.role == MessageRole.USER else "[TRANSCRIPT - ASSISTANT SAID]:"
            llm_input.append({
                "role": msg.role.value,
                "content": f"{prefix}\n{msg.content}"
            })

        # Final instruction to generate summary
        if previous_summary:
            final_instruction = f"""=== END TRANSCRIPT ===

Now, as the external observer, update the Session Memory document based on the transcript above.

Remember:
- The USER in the transcript is the human
- The ASSISTANT in the transcript is a different AI (not you)
- You are summarizing THEIR conversation for future reference

Operations to perform:
- ADD new items with timestamp [{current_timestamp}] for new information
- UPDATE existing items (change timestamp to [{current_timestamp}]) if they evolved
- REMOVE items that are now obsolete, resolved, or irrelevant
- PROMOTE items from Backlog → Active Plan if work started
- RESOLVE items from Open Questions → Decisions if answered

Be aggressive about removing stale information. This is a living document, not an append-only log.

Output the COMPLETE updated Session Memory document. Target: {max_chars} chars max."""
        else:
            final_instruction = f"""=== END TRANSCRIPT ===

Now, as the external observer, create a new Session Memory document from the transcript above.

Remember:
- The USER in the transcript is the human
- The ASSISTANT in the transcript is a different AI (not you)
- You are summarizing THEIR conversation for future reference

Use timestamp [{current_timestamp}] for all items.

Extract and organize:
- User's objectives and goals
- User preferences (communication style, technical level)
- Technical details (paths, functions, errors, values - preserve exactly)
- Decisions made by the user and assistant together
- Conversation flow (narrative arc, not every message)
- Active tasks being worked on
- Future items / backlog
- Open questions needing answers

Output ONLY the Session Memory document. Target: {max_chars} chars max."""

        llm_input.append({
            "role": "user",
            "content": final_instruction
        })

        total_chars = sum(len(m["content"]) for m in llm_input)
        summary_logger.debug(f"Calling summary LLM (model={self.summary_model}, input_msgs={len(llm_input)}, total_chars={total_chars})")
        try:
            response = self.client.responses.create(
                model=self.summary_model,
                instructions=self._get_summary_system_prompt(current_timestamp),
                input=llm_input
            )
            summary_logger.debug(f"Summary LLM response received (id={response.id})")
            return response.output_text, response.id
        except Exception as e:
            summary_logger.error(f"Summary LLM call failed: {e}", exc_info=True)
            raise

    def _shrink_summary(self, summary: str, target_chars: int, previous_response_id: str) -> tuple[str, str]:
        """
        Ask LLM to shrink summary using continuation mode.
        Always continues from previous response (summary or prior shrink).

        Returns:
            tuple of (shrunk_summary, response_id) for continuation
        """
        current_size = len(summary)
        reduction_needed = current_size - target_chars
        reduction_pct = (reduction_needed / current_size) * 100

        # determine urgency level and strategy based on reduction percentage
        if reduction_pct <= 25:
            urgency = "LIGHT"
            strategy = (
                "Minor trim needed. Remove 1-2 oldest/least relevant items per section. "
                "Slightly shorten verbose descriptions. Keep all sections intact."
            )
        elif reduction_pct <= 50:
            urgency = "MODERATE"
            strategy = (
                "Significant reduction needed. Remove older items aggressively. "
                "Consolidate similar items into single lines. Shorten all descriptions to essentials. "
                "Keep section headers but allow fewer items per section."
            )
        elif reduction_pct <= 75:
            urgency = "HEAVY"
            strategy = (
                "Major compression required. Keep ONLY the most critical items in each section. "
                "Merge related items. Use terse, telegram-style descriptions. "
                "Preserve exact technical details (paths, values, errors) but remove all fluff."
            )
        else:
            urgency = "EXTREME"
            strategy = (
                "Emergency compression! Keep only ESSENTIAL items - 2-3 per section max. "
                "Remove entire sections if they're low priority (Backlog, older Conversation Flow). "
                "Preserve: current objectives, active tasks, critical technical context, open blockers. "
                "Cut everything else ruthlessly."
            )

        prompt = [
            {
                "role": "user",
                "content": (
                    f"Your output was {current_size:,} chars but must be under {target_chars:,} chars.\n"
                    f"Reduction needed: {reduction_needed:,} chars ({reduction_pct:.0f}%)\n"
                    f"Urgency: {urgency}\n\n"
                    f"Strategy: {strategy}\n\n"
                    f"Output ONLY the compressed Session Memory markdown."
                )
            }
        ]

        # system instructions to reinforce the task
        instructions = """You are compressing a Session Memory document.
Output ONLY the markdown document - no explanations, no meta-commentary, no preamble.
Keep the same structure (## headers), preserve technical details exactly, but make it shorter."""

        summary_logger.debug(f"Calling shrink LLM (target={target_chars})")
        try:
            response = self.client.responses.create(
                model=self.summary_model,
                instructions=instructions,
                previous_response_id=previous_response_id,
                input=prompt
            )
            summary_logger.debug(f"Shrink LLM response received (id={response.id})")
            return response.output_text, response.id
        except Exception as e:
            summary_logger.error(f"Shrink LLM call failed: {e}", exc_info=True)
            raise

    def _hard_truncate_summary(self, summary: str, target_chars: int) -> str:
        """
        Hard truncate summary to fit target size.
        Tries to cut at section boundaries if possible.
        """
        if len(summary) <= target_chars:
            return summary

        # try to find a good cut point (end of a section)
        truncated = summary[:target_chars]

        # look for last complete section (## header followed by content)
        last_section_end = truncated.rfind("\n\n##")
        if last_section_end > target_chars // 2:
            # found a section boundary in the second half, cut there
            truncated = truncated[:last_section_end]
        else:
            # no good section boundary, cut at last newline
            last_newline = truncated.rfind("\n")
            if last_newline > target_chars - 200:
                truncated = truncated[:last_newline]

        # add truncation marker
        truncated += "\n\n[...truncated due to size limit...]"

        summary_logger.debug(f"Hard truncated: {len(summary)} -> {len(truncated)} chars")
        return truncated

    def _get_summary_for_anchor(self, anchor_idx: int) -> str | None:
        """Get the best summary for a given anchor point."""
        if not self.summaries:
            return None

        # find the most recent summary at or before the anchor
        best_summary = None
        for summary in self.summaries:
            if summary.anchor_message_idx <= anchor_idx:
                best_summary = summary.summary
            else:
                break

        return best_summary

    def get_stats(self) -> dict:
        """Get current context manager stats."""
        return {
            "T_current": self.T_current,
            "T_drain": self.T_drain,
            "T_max": self.T_max,
            "T_target": self.T_target,
            "T_summary_max": self.T_summary_max,
            "max_message_size": self.max_message_size,
            "message_count": len(self.messages),
            "summary_count": len(self.summaries),
            "current_anchor_idx": self.current_anchor_idx,
            "has_response_id": self.last_response_id is not None,
            "summarization_in_progress": self.summarization_in_progress,
        }

    # --- Agent integration methods ---
    # These methods allow external agents to use the context manager
    # while handling their own LLM calls (e.g., with tools, parsing, etc.)

    def add_user_message(self, content: str) -> None:
        """
        Add a user message to the context.
        Checks for drain if context exceeds T_max.

        Use this when you're managing LLM calls externally but want
        the context manager to handle message history and summarization.
        """
        max_message_size = self.max_message_size
        if len(content) > max_message_size:
            raise ValueError(
                f"Message too large: {len(content):,} chars exceeds limit of {max_message_size:,} chars."
            )

        self.messages.append(Message(role=MessageRole.USER, content=content))
        self.T_current += len(content)

        # log context status
        pct = (self.T_current / self.T_max) * 100
        summary_logger.info(
            f"[CONTEXT] +USER msg ({len(content):,} chars) → "
            f"T_current={self.T_current:,}/{self.T_max:,} ({pct:.1f}%) | "
            f"msgs={len(self.messages)} | summaries={len(self.summaries)}"
        )

        # check if we need to drain
        if self.T_current > self.T_max:
            summary_logger.warning(f"[CONTEXT] T_current ({self.T_current:,}) > T_max ({self.T_max:,}) - DRAIN REQUIRED")
            self._drain_context()

    def add_assistant_message(self, content: str, response_id: str | None = None) -> None:
        """
        Add an assistant message to the context.
        Optionally stores the response_id for continuation mode.
        Triggers async summarization if context exceeds T_drain.

        Use this after receiving an LLM response when managing calls externally.
        """
        self.messages.append(Message(role=MessageRole.ASSISTANT, content=content))
        self.T_current += len(content)

        if response_id is not None:
            self.last_response_id = response_id

        # log context status
        pct = (self.T_current / self.T_max) * 100
        drain_pct = (self.T_current / self.T_drain) * 100 if self.T_drain > 0 else 0
        summary_logger.info(
            f"[CONTEXT] +ASST msg ({len(content):,} chars) → "
            f"T_current={self.T_current:,}/{self.T_max:,} ({pct:.1f}%) | "
            f"drain_threshold={drain_pct:.1f}% | msgs={len(self.messages)}"
        )

        # check if we need to start async summarization
        if self.T_current > self.T_drain:
            summary_logger.info(f"[CONTEXT] T_current ({self.T_current:,}) > T_drain ({self.T_drain:,}) - triggering async summarization")
            self._maybe_start_async_summarization()

    def get_llm_input(self) -> tuple[list[dict], str | None]:
        """
        Get the input messages and previous_response_id for an LLM call.

        Returns:
            tuple of (input_messages, previous_response_id)
            - If previous_response_id is not None, input_messages contains only the last message
            - If previous_response_id is None, input_messages contains full context
        """
        llm_input = self._build_llm_input()

        # log what mode we're using
        if self.last_response_id is not None:
            summary_logger.debug(
                f"[LLM_INPUT] Continuation mode | sending {len(llm_input)} msg(s) | "
                f"has_response_id=True"
            )
        elif self.current_anchor_idx is not None:
            summary_logger.debug(
                f"[LLM_INPUT] Post-drain mode | sending {len(llm_input)} msg(s) | "
                f"anchor={self.current_anchor_idx} | has_summary={len(self.summaries) > 0}"
            )
        else:
            summary_logger.debug(
                f"[LLM_INPUT] Fresh context mode | sending {len(llm_input)} msg(s)"
            )

        return llm_input, self.last_response_id

    def set_response_id(self, response_id: str) -> None:
        """
        Set the last response ID without adding a message.
        Useful when the response content is tracked elsewhere.
        """
        self.last_response_id = response_id
