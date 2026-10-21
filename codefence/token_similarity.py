"""Token-based shingle fingerprints, exact Jaccard, and MinHash (Milestone 2B)."""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import Iterable, Iterator

# Documented defaults (experimental; not production security thresholds).
DEFAULT_SHINGLE_SIZE = 5
DEFAULT_MINHASH_PERM = 128
# Fixed seed for reproducible MinHash signatures across runs.
MINHASH_SEED = 42

SequenceLike = tuple[str, ...] | list[str]

# Tokens omitted from fingerprint sequences (formatting / comments only).
_SKIP_TOKEN_TYPES = frozenset(
    {
        tokenize.ENCODING,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.COMMENT,
        tokenize.ENDMARKER,
    }
)


@dataclass(frozen=True)
class TokenFingerprint:
    """Normalized token shingles for one function body."""

    ok: bool
    normalized_tokens: tuple[str, ...]
    shingles: frozenset[str]
    minhash_hashvalues: tuple[int, ...]
    unsupported_reason: str | None = None


def _canonical_token_string(tok_type: int, string: str) -> str | None:
    if tok_type in _SKIP_TOKEN_TYPES:
        return None
    if tok_type == tokenize.NAME:
        return f"NAME:{string}"
    if tok_type == tokenize.NUMBER:
        return f"NUMBER:{string}"
    if tok_type == tokenize.STRING:
        return f"STRING:{string}"
    if tok_type == tokenize.OP:
        return f"OP:{string}"
    if tok_type == tokenize.FSTRING_START:
        return "FSTRING:START"
    if tok_type == tokenize.FSTRING_MIDDLE:
        return f"FSTRING:{string!r}"
    if tok_type == tokenize.FSTRING_END:
        return "FSTRING:END"
    # KEYWORD and others
    return f"TOK:{string}"


def normalize_token_strings(source: str) -> tuple[str, ...] | None:
    """
    Tokenize Python source without executing it.

    Preserves identifier names, literals, operators, and keywords.
    Strips comments and whitespace-only tokens.
    """
    try:
        tokens: list[str] = []
        reader = io.BytesIO(source.encode("utf-8")).readline
        for tok in tokenize.tokenize(reader):
            canonical = _canonical_token_string(tok.type, tok.string)
            if canonical is not None:
                tokens.append(canonical)
        return tuple(tokens)
    except tokenize.TokenError as exc:
        return None


def build_shingles(tokens: SequenceLike, *, shingle_size: int) -> frozenset[str]:
    """Build contiguous token shingles (joined with a delimiter unlikely in tokens)."""
    if shingle_size < 1:
        raise ValueError("shingle_size must be at least 1")
    if len(tokens) < shingle_size:
        return frozenset()
    delim = "\x1f"
    shingles: set[str] = set()
    for index in range(len(tokens) - shingle_size + 1):
        window = tokens[index : index + shingle_size]
        shingles.add(delim.join(window))
    return frozenset(shingles)


def exact_jaccard(set_a: frozenset[str], set_b: frozenset[str]) -> float:
    """|A ∩ B| / |A ∪ B|; empty union returns 0.0."""
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / len(union)


def datasketch_available() -> bool:
    try:
        import datasketch  # noqa: F401
    except ImportError:
        return False
    return True


def minhash_from_shingles(
    shingles: Iterable[str],
    *,
    num_perm: int = DEFAULT_MINHASH_PERM,
    seed: int = MINHASH_SEED,
) -> tuple[int, ...]:
    """Deterministic MinHash signature (hashvalues tuple) for a shingle set."""
    if not datasketch_available():
        return ()
    from datasketch import MinHash

    signature = MinHash(num_perm=num_perm, seed=seed)
    for shingle in sorted(shingles):
        signature.update(shingle.encode("utf-8"))
    return tuple(int(value) for value in signature.hashvalues)


def minhash_jaccard_estimate(
    hashvalues_a: tuple[int, ...],
    hashvalues_b: tuple[int, ...],
    *,
    num_perm: int = DEFAULT_MINHASH_PERM,
    seed: int = MINHASH_SEED,
) -> float:
    """Estimated Jaccard from two MinHash signatures."""
    if not hashvalues_a or not hashvalues_b or not datasketch_available():
        return 0.0
    from datasketch import MinHash

    sig_a = MinHash(num_perm=num_perm, seed=seed, hashvalues=hashvalues_a)
    sig_b = MinHash(num_perm=num_perm, seed=seed, hashvalues=hashvalues_b)
    return float(sig_a.jaccard(sig_b))


def fingerprint_function_tokens(
    module_source: str,
    function_node: ast.AST,
    *,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    num_perm: int = DEFAULT_MINHASH_PERM,
) -> TokenFingerprint:
    """Extract token shingles for one ``FunctionDef`` / ``AsyncFunctionDef``."""
    if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return TokenFingerprint(
            ok=False,
            normalized_tokens=(),
            shingles=frozenset(),
            minhash_hashvalues=(),
            unsupported_reason="Token fingerprinting applies only to function definitions.",
        )

    segment = ast.get_source_segment(module_source, function_node, padded=True)
    if segment is None:
        return TokenFingerprint(
            ok=False,
            normalized_tokens=(),
            shingles=frozenset(),
            minhash_hashvalues=(),
            unsupported_reason="Could not extract function source for tokenization.",
        )

    normalized = normalize_token_strings(segment)
    if normalized is None:
        return TokenFingerprint(
            ok=False,
            normalized_tokens=(),
            shingles=frozenset(),
            minhash_hashvalues=(),
            unsupported_reason="Unsupported or invalid token stream for this function.",
        )

    shingles = build_shingles(normalized, shingle_size=shingle_size)
    if not shingles:
        hashvalues: tuple[int, ...] = ()
    else:
        hashvalues = minhash_from_shingles(shingles, num_perm=num_perm)

    return TokenFingerprint(
        ok=True,
        normalized_tokens=normalized,
        shingles=shingles,
        minhash_hashvalues=hashvalues,
    )


def literal_token_multiset(tokens: tuple[str, ...]) -> frozenset[str]:
    """Literal NUMBER/STRING tokens preserved for false-positive filtering."""
    return frozenset(
        token for token in tokens if token.startswith("NUMBER:") or token.startswith("STRING:")
    )


def describe_literal_evidence(
    protected_literals: frozenset[str],
    outgoing_literals: frozenset[str],
) -> tuple[bool, str]:
    """
    Summarize literal-token differences without exposing literal values.

    Literal differences are evidence for review, not proof of leakage.
    """
    if protected_literals == outgoing_literals:
        return False, "Literal token multiset matches (numeric/string categories only)."

    def _counts(multiset: frozenset[str]) -> tuple[int, int]:
        numbers = sum(1 for item in multiset if item.startswith("NUMBER:"))
        strings = sum(1 for item in multiset if item.startswith("STRING:"))
        return numbers, strings

    prot_num, prot_str = _counts(protected_literals)
    out_num, out_str = _counts(outgoing_literals)
    parts: list[str] = ["Literal token multiset differs"]
    if prot_num != out_num:
        parts.append(
            f"numeric literal token count protected={prot_num} outgoing={out_num}"
        )
    if prot_str != out_str:
        parts.append(
            f"string literal token count protected={prot_str} outgoing={out_str}"
        )
    if len(parts) == 1:
        parts.append("literal categories changed without count summary")
    return True, "; ".join(parts) + "."


def passes_token_candidate_filters(
    *,
    token_count: int,
    shingle_count: int,
    min_tokens: int,
    min_shingles: int,
) -> bool:
    """Conservative filters to reduce boilerplate / short-function false positives."""
    return token_count >= min_tokens and shingle_count >= min_shingles
