"""Synthetic example with a nested function."""


def outer_factor(n):
    def inner_double(x):
        return x * n * 2

    return inner_double
