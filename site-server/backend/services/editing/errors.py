"""Errors shared by the editing modules (kept in a leaf module so `titles`, `color`, `timeline` … can all raise the
same Persian-worded exception without importing each other)."""


class TimelineError(Exception):
    """Something about the arrangement cannot be rendered, said in Persian."""
