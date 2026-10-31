"""Group parsers for the METAR body.

Each ``parse_*`` function looks at the token under the cursor, returns the decoded value and consumes (and tags) the
tokens it used, or returns ``None`` without consuming anything. They never raise on text; the driver in
``decode/metar.py`` still wraps every call so a bug cannot escape.
"""
