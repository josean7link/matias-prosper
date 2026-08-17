"""Public file-validation helper (Fase 0.5, Aug 2026).

Previously a private `_validate_file` in `services/andes_kyc.py`, used
only by the Andes KYC submission endpoint. Extracted here without
behaviour change so other modules (KYB, uploads, etc.) can reuse it.

The KYC production path continues to use these defaults unchanged.
Callers who need a different policy pass explicit `allowed_types` and
`max_bytes` arguments.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# --- Public defaults (match the legacy `_validate_file` behaviour) -----------
DEFAULT_MIN_BYTES = 1024               # 1 KB
DEFAULT_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
DEFAULT_ALLOWED = ("jpeg", "png", "pdf", "webp", "heic")


@dataclass
class FileValidatorPolicy:
    allowed: tuple[str, ...] = field(default_factory=lambda: DEFAULT_ALLOWED)
    min_bytes: int = DEFAULT_MIN_BYTES
    max_bytes: int = DEFAULT_MAX_BYTES


class FileValidationError(ValueError):
    """Raised when a file fails validation. Callers translate to HTTP."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sniff_type(content: bytes) -> str | None:
    """Return the type name (jpeg/png/pdf/webp/heic) or None."""
    head = content[:12]
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"%PDF":
        return "pdf"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftyphevc",
                        b"ftypmif1"):
        return "heic"
    return None


def validate_file(name: str, content: bytes,
                    policy: FileValidatorPolicy | None = None) -> str:
    """Validate `content` against `policy`. Returns the sniffed type.

    Raises `FileValidationError` on any of:
      * empty / < min_bytes
      * > max_bytes
      * magic bytes not in the allowed set

    Never accepts a file solely by extension — the file is opened and
    the first bytes matched.
    """
    p = policy or FileValidatorPolicy()
    n = len(content)
    if n == 0:
        raise FileValidationError(
            "empty",
            f"El archivo '{name}' está vacío.")
    if n < p.min_bytes:
        raise FileValidationError(
            "too_small",
            f"El archivo '{name}' es muy pequeño (<{p.min_bytes} bytes). "
            f"Revisá la captura.")
    if n > p.max_bytes:
        mb = p.max_bytes // (1024 * 1024)
        raise FileValidationError(
            "too_large",
            f"El archivo '{name}' supera {mb} MB.")
    kind = sniff_type(content)
    if kind is None or kind not in p.allowed:
        raise FileValidationError(
            "unsupported_type",
            f"Formato de '{name}' no soportado. "
            f"Permitidos: {', '.join(p.allowed).upper()}.")
    return kind
