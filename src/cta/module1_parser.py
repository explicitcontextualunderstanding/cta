"""
Module 1: Trace Collection and Parsing
Extracts structured events from Claude Code execution logs
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from .data_models import Event, Trace, EventType, EventOutcome


class TraceParser:
    """
    Parses Claude Code conversation logs into structured event sequences.

    Expects a Claude Code JSON conversation log with alternating reasoning and tool_use blocks.
    """

    def __init__(self):
        self.event_id_counter = 0

    def parse_claude_log(self, log_data: Dict[str, Any], task_id: str, with_skill: bool = False) -> Trace:
        """
        Parse Claude Code conversation log into a Trace.

        Args:
            log_data: Claude Code JSON conversation output
            task_id: Task identifier
            with_skill: Whether skill was used in this execution

        Returns:
            Trace object with structured events
        """
        self.event_id_counter = 0
        trace_id = f"{task_id}_with_skill={with_skill}_{datetime.now().isoformat()}"

        events = []
        messages = log_data.get('messages', [])

        # Extract reasoning text and tool uses
        reasoning_buffer = ""

        for i, message in enumerate(messages):
            # Collect reasoning (text content)
            if message.get('role') == 'assistant':
                content = message.get('content', '')
                if isinstance(content, str):
                    reasoning_buffer += content + "\n"

                # Look for tool uses
                tool_uses = message.get('tool_uses', [])
                for tool_use in tool_uses:
                    event = self._parse_tool_use(
                        tool_use,
                        reasoning_buffer,
                        messages,
                        i
                    )
                    if event:
                        events.append(event)
                    reasoning_buffer = ""  # Reset after processing tool use

        # Calculate totals
        total_tokens = log_data.get('usage', {}).get('input_tokens', 0) + \
                       log_data.get('usage', {}).get('output_tokens', 0)

        duration_sec = 0.0
        if 'metadata' in log_data:
            created_at = log_data['metadata'].get('created_at')
            completed_at = log_data['metadata'].get('completed_at')
            if created_at and completed_at:
                start = datetime.fromisoformat(created_at)
                end = datetime.fromisoformat(completed_at)
                duration_sec = (end - start).total_seconds()

        final_outcome = log_data.get('final_outcome', False)

        return Trace(
            trace_id=trace_id,
            events=events,
            task_id=task_id,
            with_skill=with_skill,
            temperature=log_data.get('temperature', 0.0),
            run_number=log_data.get('run_number', 0),
            total_tokens=total_tokens,
            duration_sec=duration_sec,
            final_outcome=final_outcome
        )

    def _parse_tool_use(self, tool_use: Dict[str, Any], reasoning_before: str,
                       all_messages: List[Dict], current_msg_idx: int) -> Optional[Event]:
        """
        Parse a tool use block into an Event.

        Args:
            tool_use: Tool use dictionary from message
            reasoning_before: Reasoning text before this tool use
            all_messages: All messages in conversation (for output lookup)
            current_msg_idx: Current message index

        Returns:
            Event or None if parsing fails
        """
        tool_name = tool_use.get('name', '')
        tool_input = tool_use.get('input', {})
        tool_id = tool_use.get('id', '')

        # Determine event type
        event_type = self._map_tool_to_event_type(tool_name)
        if not event_type:
            return None

        # Extract tool output from subsequent user message
        tool_result = self._extract_tool_result(tool_id, current_msg_idx, all_messages)

        # Determine event outcome
        outcome = self._determine_outcome(event_type, tool_result, tool_input)

        # Extract content
        content = self._extract_content(event_type, tool_input, tool_result)
        target = self._extract_target(event_type, tool_input)

        self.event_id_counter += 1

        return Event(
            event_id=self.event_id_counter,
            type=event_type,
            target=target,
            content=content,
            reasoning=reasoning_before.strip(),
            outcome=outcome,
            token_count=self._estimate_token_count(content),
            timestamp=datetime.now().timestamp()
        )

    def _map_tool_to_event_type(self, tool_name: str) -> Optional[EventType]:
        """Map tool name to event type"""
        mapping = {
            'bash': EventType.EXECUTE,
            'read': EventType.READ,
            'write': EventType.WRITE,
            'grep': EventType.SEARCH,
            'glob': EventType.SEARCH,
        }
        return mapping.get(tool_name)

    def _extract_tool_result(self, tool_id: str, msg_idx: int,
                            messages: List[Dict]) -> str:
        """Extract tool result from subsequent messages"""
        # Look ahead for the tool result in user messages
        for i in range(msg_idx + 1, min(msg_idx + 10, len(messages))):
            msg = messages[i]
            if msg.get('role') == 'user':
                content = msg.get('content', '')
                if tool_id in content or isinstance(content, dict):
                    if isinstance(content, dict) and 'tool_result' in content:
                        return content['tool_result'].get('content', '')
                    elif isinstance(content, str) and len(content) > 0:
                        return content[:2000]  # Limit result size
        return ""

    def _determine_outcome(self, event_type: EventType, tool_result: str,
                          tool_input: Dict) -> EventOutcome:
        """Determine if event succeeded"""
        if event_type == EventType.EXECUTE:
            # Check exit code in result
            if 'exit_code' in tool_result or 'error' in tool_result.lower():
                if 'exit_code' in tool_result:
                    try:
                        # Extract exit code
                        match = re.search(r'exit_code["\']?:\s*(\d+)', tool_result)
                        if match and int(match.group(1)) != 0:
                            return EventOutcome.FAILURE
                    except:
                        pass
                if 'error' in tool_result.lower() and 'error' in tool_result.lower()[:100]:
                    return EventOutcome.FAILURE
            return EventOutcome.SUCCESS
        return EventOutcome.SUCCESS

    def _extract_content(self, event_type: EventType, tool_input: Dict,
                        tool_result: str) -> str:
        """Extract content based on event type"""
        if event_type == EventType.WRITE:
            # Extract file content being written
            content = tool_input.get('content', '')
            if isinstance(content, str):
                return content[:5000]  # Limit size
            return str(content)[:5000]
        elif event_type == EventType.READ:
            # File content that was read
            return tool_result[:3000]  # Limit size
        elif event_type == EventType.EXECUTE:
            # Command output
            return tool_result[:2000]  # Limit size
        else:
            return tool_result[:1000]  # Limit size

    def _extract_target(self, event_type: EventType, tool_input: Dict) -> str:
        """Extract target (file path, command, etc.)"""
        if event_type in (EventType.READ, EventType.WRITE):
            return tool_input.get('file_path', '')
        elif event_type == EventType.EXECUTE:
            return tool_input.get('command', '')[:200]
        elif event_type in (EventType.SEARCH, EventType.GLOB):
            return tool_input.get('pattern', '') or tool_input.get('query', '')
        return ""

    def _estimate_token_count(self, content: str) -> int:
        """Rough estimation of token count (1 token ≈ 4 chars)"""
        return max(1, len(content) // 4)

    def parse_trace_file(self, filepath: str) -> Trace:
        """
        Parse trace from a JSON file.

        Args:
            filepath: Path to trace JSON file

        Returns:
            Trace object
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        # Extract metadata
        task_id = data.get('task_id', 'unknown')
        with_skill = data.get('with_skill', False)

        trace = self.parse_claude_log(data, task_id, with_skill)
        return trace

    def batch_parse(self, log_dir: str) -> Dict[str, Trace]:
        """
        Parse all trace files in a directory.

        Args:
            log_dir: Directory containing trace JSON files

        Returns:
            Dictionary mapping trace_id to Trace objects
        """
        traces = {}
        log_path = Path(log_dir)

        for json_file in log_path.glob('*.json'):
            try:
                trace = self.parse_trace_file(str(json_file))
                traces[trace.trace_id] = trace
            except Exception as e:
                print(f"Error parsing {json_file}: {e}")
                continue

        return traces
