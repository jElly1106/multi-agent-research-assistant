"""Per-run admission budget; reservations are estimates, not provider billing."""
from __future__ import annotations

import json
from pathlib import Path

from .agents.reader import RecoverableAnalysisError


class BudgetExceeded(RecoverableAnalysisError):
    pass


def local_bpe_counter(path, *, pattern):
    """Explicit local tokenizer assets only; never downloads or guesses a model.

    Caller supplies a model-compatible .tiktoken rank file and regex pattern.
    Special-token-looking source text is treated as ordinary untrusted text.
    """
    import tiktoken
    from tiktoken.load import load_tiktoken_bpe
    source = Path(path)
    if not source.is_file():
        raise ValueError("A local tokenizer rank file is required")
    ranks = load_tiktoken_bpe(str(source.resolve()))
    encoding = tiktoken.Encoding(name="reader-local", pat_str=pattern,
                                 mergeable_ranks=ranks, special_tokens={})
    return lambda text: len(encoding.encode_ordinary(text))


class ReaderBudget:
    def __init__(self, *, context_tokens=16384, output_tokens=2048,
                 max_calls=50, max_reserved_tokens=200_000, overhead_tokens=512,
                 token_counter=None):
        for name, value in [("context_tokens", context_tokens), ("output_tokens", output_tokens),
                            ("max_calls", max_calls), ("max_reserved_tokens", max_reserved_tokens),
                            ("overhead_tokens", overhead_tokens)]:
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if output_tokens + overhead_tokens >= context_tokens:
            raise ValueError("Context must leave room for input")
        if token_counter is not None and not callable(token_counter):
            raise ValueError("token_counter must be callable")
        self.context_tokens = context_tokens
        self.output_tokens = output_tokens
        self.max_calls = max_calls
        self.max_reserved_tokens = max_reserved_tokens
        self.overhead_tokens = overhead_tokens
        self.counter = token_counter or (lambda text: len(text.encode("utf-8")))
        self.counter_mode = "supplied_tokenizer" if token_counter else "utf8_byte_estimate"
        self.calls = 0
        self.reserved = 0
        self.events = []

    def reserve(self, *, stage, title, messages, schema, chunk=None):
        # Include system prompt and structured schema, not just the paper text.
        payload = json.dumps({"messages": messages, "schema": schema.model_json_schema()},
                             ensure_ascii=False, separators=(",", ":"))
        count = self.counter(payload)
        if type(count) is not int or count < 0:
            raise ValueError("Token counter must return a nonnegative integer")
        input_tokens = count + self.overhead_tokens
        total = input_tokens + self.output_tokens
        reason = ("context_budget_exceeded" if total > self.context_tokens else
                  "call_budget_exceeded" if self.calls >= self.max_calls else
                  "batch_token_budget_exceeded" if self.reserved + total > self.max_reserved_tokens else None)
        event = {"stage": stage, "paper_title": title, "chunk": chunk,
                 "estimated_input_tokens": input_tokens, "reserved_output_tokens": self.output_tokens,
                 "admitted": reason is None, "code": reason}
        self.events.append(event)
        if reason:
            raise BudgetExceeded(reason)
        self.calls += 1
        self.reserved += total

    def report(self):
        return {"counter_mode": self.counter_mode, "admitted_calls": self.calls,
                "reserved_tokens": self.reserved, "events": self.events}
