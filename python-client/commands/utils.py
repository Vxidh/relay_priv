import os
import unicodedata

def normalize_path(path):
    """
    Normalizes user-provided file paths to avoid Unicode errors, invisible characters,
    and directory traversal vulnerabilities.
    """
    if not isinstance(path, str):
        return path
    normalized = unicodedata.normalize("NFKC", path)
    sanitized = normalized.replace('\x00', '')  # Strip null bytes
    return os.path.normpath(sanitized)
