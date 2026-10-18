#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def force_utf8_output():
    """Never let a Persian log line kill a management command.

    Everything this project prints to the operator - job errors, the selftest
    report, migration notices - is Persian. When stdout is a pipe or a file
    (`manage.py selftest > log.txt`, or any wrapper that captures output)
    Python falls back to the Windows ANSI code page and a single Persian
    character raises UnicodeEncodeError, killing the command mid-run.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # already-wrapped or non-reconfigurable stream: leave it alone


def main():
    force_utf8_output()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
