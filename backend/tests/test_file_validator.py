"""Tests for the public file_validator module (Fase 0.5)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.file_validator import (
    DEFAULT_MIN_BYTES, DEFAULT_MAX_BYTES, FileValidationError,
    FileValidatorPolicy, sniff_type, validate_file)


def _pad(prefix: bytes, size: int = DEFAULT_MIN_BYTES + 100) -> bytes:
    return prefix + b"\x00" * (size - len(prefix))


def test_accepts_jpeg():
    assert validate_file("a.jpg", _pad(b"\xff\xd8\xff\xe0")) == "jpeg"


def test_accepts_png():
    assert validate_file("a.png", _pad(b"\x89PNG\r\n\x1a\n")) == "png"


def test_accepts_pdf():
    assert validate_file("a.pdf", _pad(b"%PDF-1.4\n")) == "pdf"


def test_accepts_webp():
    body = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 200
    body = body + b"\x00" * (DEFAULT_MIN_BYTES - len(body) + 50)
    assert validate_file("a.webp", body) == "webp"


def test_accepts_heic():
    body = b"\x00\x00\x00\x18" + b"ftypheic" + b"\x00" * 200
    body = body + b"\x00" * (DEFAULT_MIN_BYTES - len(body) + 50)
    assert validate_file("a.heic", body) == "heic"


def test_rejects_exe_renamed_pdf():
    # MZ header — Windows PE. Renamed .pdf must NOT sneak past.
    payload = _pad(b"MZ\x90\x00")
    with pytest.raises(FileValidationError) as e:
        validate_file("looks_like.pdf", payload)
    assert e.value.code == "unsupported_type"


def test_rejects_zero_bytes():
    with pytest.raises(FileValidationError) as e:
        validate_file("empty.pdf", b"")
    assert e.value.code == "empty"


def test_rejects_oversize():
    body = _pad(b"%PDF-1.4\n", size=DEFAULT_MAX_BYTES + 1)
    with pytest.raises(FileValidationError) as e:
        validate_file("big.pdf", body)
    assert e.value.code == "too_large"


def test_rejects_too_small():
    # magic bytes correct but under min
    with pytest.raises(FileValidationError) as e:
        validate_file("tiny.pdf", b"%PDF" + b"\x00" * 100)
    assert e.value.code == "too_small"


def test_pdf_magic_but_corrupted_body_still_passes_size_and_magic():
    # A PDF with the correct magic bytes but garbage after — the
    # validator promises magic-bytes + size only. Semantic PDF parsing
    # is out of scope. Documenting behaviour so future changes don't
    # silently tighten it.
    body = _pad(b"%PDF-1.4\n") + b"\xde\xad\xbe\xef" * 50
    assert validate_file("corrupt.pdf", body) == "pdf"


def test_custom_policy_narrows_types():
    policy = FileValidatorPolicy(allowed=("pdf",))
    with pytest.raises(FileValidationError) as e:
        validate_file("a.jpg", _pad(b"\xff\xd8\xff\xe0"), policy)
    assert e.value.code == "unsupported_type"


def test_custom_policy_widens_size():
    policy = FileValidatorPolicy(min_bytes=10)
    assert validate_file("a.pdf", b"%PDF-1.4\n____", policy) == "pdf"


def test_sniff_type_returns_none_for_random_bytes():
    assert sniff_type(b"\x00\x01\x02\x03\x04garbage") is None
