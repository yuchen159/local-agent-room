from pathlib import Path
import json

MAX_CHARS = 600

def read_config(path):
    try:
        with Path(path).open('r', encoding='utf-8-sig') as source:
            content = source.read(16385)
        if len(content) > 16384:
            return {}
        value = json.loads(content)
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}

def read_note(role, config):
    """Read one explicitly enabled role's note; never search peer paths."""
    entry = config.get(role)
    if not isinstance(entry, dict) or entry.get('enabled') is not True:
        return ''
    path = entry.get('path')
    if not isinstance(path, str) or not path:
        return ''
    try:
        with Path(path).open('r', encoding='utf-8-sig') as source:
            return source.read(MAX_CHARS).strip()
    except (OSError, UnicodeError, ValueError):
        return ''
