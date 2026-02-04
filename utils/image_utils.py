"""Small standalone image geometry utilities (aspect containment helper)."""

from typing import Tuple


def compute_contain_size(src_w: int, src_h: int, area_w: int, area_h: int, zoom: float = 1.0) -> Tuple[int, int]:
    """Compute target width/height to 'contain' the source inside a target area.

    The result is scaled by the zoom factor (1.0 = no zoom). The returned
    size is clamped to at least 2 pixels for safety.
    """
    if src_w <= 0 or src_h <= 0:
        return 2, 2
    base_ratio = min(area_w / src_w, area_h / src_h)
    ratio = max(0.001, base_ratio * zoom)
    w = max(2, int(src_w * ratio))
    h = max(2, int(src_h * ratio))
    return w, h
