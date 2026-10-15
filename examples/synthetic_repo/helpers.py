"""Synthetic protected code for Milestone 1 demos (not real proprietary code)."""


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


class Widget:
    def spin(self, degrees):
        total = degrees % 360
        return total
