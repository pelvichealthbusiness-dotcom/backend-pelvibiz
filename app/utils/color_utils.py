"""
WCAG 2.1 color contrast utilities for carousel text overlay.
Ported from pelvi-ai-hub/api/_lib/color-utils.ts
"""


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    n = int(h, 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def relative_luminance(r: int, g: int, b: int) -> float:
    components = []
    for c in (r, g, b):
        s = c / 255
        components.append(s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * components[0] + 0.7152 * components[1] + 0.0722 * components[2]


def contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = relative_luminance(*hex_to_rgb(hex1))
    l2 = relative_luminance(*hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def is_light(hex_color: str) -> bool:
    return relative_luminance(*hex_to_rgb(hex_color)) > 0.179


def ensure_contrast(fg: str, bg: str, min_ratio: float = 4.5) -> str:
    if contrast_ratio(fg, bg) >= min_ratio:
        return fg
    target = '#000000' if is_light(bg) else '#FFFFFF'
    f_r, f_g, f_b = hex_to_rgb(fg)
    t_r, t_g, t_b = hex_to_rgb(target)
    t = 0.05
    while t <= 1.0:
        r = round(f_r + (t_r - f_r) * t)
        g = round(f_g + (t_g - f_g) * t)
        b = round(f_b + (t_b - f_b) * t)
        blended = '#{:02x}{:02x}{:02x}'.format(r, g, b)
        if contrast_ratio(blended, bg) >= min_ratio:
            return blended
        t += 0.05
    return target


def pick_best_background(
    palette: list[str],
    primary: str,
    secondary: str,
) -> str:
    candidates = [c for c in palette if c.lower() != primary.lower() and c.lower() != secondary.lower()]
    best_color = ''
    best_min_contrast = 0.0
    for color in candidates:
        min_c = min(contrast_ratio(color, primary), contrast_ratio(color, secondary))
        if min_c > best_min_contrast:
            best_min_contrast = min_c
            best_color = color
    if best_min_contrast >= 3.0:
        return best_color
    white_c = min(contrast_ratio('#FFFDF5', primary), contrast_ratio('#FFFDF5', secondary))
    dark_c = min(contrast_ratio('#1A1A2E', primary), contrast_ratio('#1A1A2E', secondary))
    return '#FFFDF5' if white_c >= dark_c else '#1A1A2E'
