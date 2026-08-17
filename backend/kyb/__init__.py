"""Módulo KYB corporativo (Fase 1+, 2026).

Todo lo que vive acá está detrás de `KYB_MODULE_ENABLED` (default
false). Con el flag apagado: no se registran rutas, no se crean
índices y no se ejecuta ninguna migración.
"""
from .flags import kyb_enabled

__all__ = ["kyb_enabled"]
