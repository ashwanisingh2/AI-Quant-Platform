"""Tiny terminal charts — dashboard banne se pehle ka maza. 📈"""

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 40) -> str:
    """Numbers → Unicode sparkline. e.g. [1,5,3,9,2] → '▁█▃█▁'"""
    if not values:
        return ""
    if len(values) > width:  # downsample
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BLOCKS[0] * len(values)
    return "".join(
        _BLOCKS[min(7, int((v - lo) / (hi - lo) * 7))] for v in values
    )
