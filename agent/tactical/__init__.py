"""Tactical override layer (Issue #43). A reversible overlay on top of the immutable Frozen Quant v1.

Nothing here changes Quant v1: the frozen constructor always runs first; `hook.py` only replaces its result for the
dates named in the pinned spec (config/tactical/*.yaml) or for an open sleeve that must be unwound.
"""
