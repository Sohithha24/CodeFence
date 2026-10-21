"""Synthetic token-similarity evaluation pairs (characterization only, not accuracy claims)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Relationship = Literal[
    "exact_copy",
    "renamed_copy",
    "added_statement",
    "removed_statement",
    "small_modification",
    "hard_negative",
]


@dataclass(frozen=True)
class TokenEvalPair:
    name: str
    protected: str
    outgoing: str
    relationship: Relationship
    expect_candidate: bool


EVAL_PAIRS: tuple[TokenEvalPair, ...] = (
    TokenEvalPair(
        name="exact_clamp",
        protected="""
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
""",
        outgoing="""
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
""",
        relationship="exact_copy",
        expect_candidate=True,
    ),
    TokenEvalPair(
        name="renamed_clamp",
        protected="""
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
""",
        outgoing="""
def bound(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
""",
        relationship="renamed_copy",
        expect_candidate=False,
    ),
    TokenEvalPair(
        name="added_log_line",
        protected="""
def compute(x, y):
    total = x + y
    return total
""",
        outgoing="""
def compute(x, y):
    total = x + y
    audit = total
    return audit
""",
        relationship="added_statement",
        expect_candidate=True,
    ),
    TokenEvalPair(
        name="removed_line",
        protected="""
def compute(x, y):
    total = x + y
    return total
""",
        outgoing="""
def compute(x, y):
    return x + y
""",
        relationship="removed_statement",
        expect_candidate=False,
    ),
    TokenEvalPair(
        name="modified_literal",
        protected="""
def scale(v):
    return v * 10
""",
        outgoing="""
def scale(v):
    return v * 99
""",
        relationship="small_modification",
        expect_candidate=False,
    ),
    TokenEvalPair(
        name="utility_add_hard_negative",
        protected="""
def add(a, b):
    return a + b
""",
        outgoing="""
def multiply(a, b):
    return a * b
""",
        relationship="hard_negative",
        expect_candidate=False,
    ),
    TokenEvalPair(
        name="similar_arithmetic_negative",
        protected="""
def alpha(x, y):
    return x * y + 1
""",
        outgoing="""
def beta(a, b):
    return a - b + 1
""",
        relationship="hard_negative",
        expect_candidate=False,
    ),
    TokenEvalPair(
        name="boilerplate_getter_negative",
        protected="""
class Account:
    def get_balance(self):
        return self.balance
""",
        outgoing="""
class Wallet:
    def read_funds(self):
        return self.funds
""",
        relationship="hard_negative",
        expect_candidate=False,
    ),
)
