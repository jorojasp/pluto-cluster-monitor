import re
import iio

SERIAL_RE = re.compile(r"serial=([A-Za-z0-9]+)")

contexts = iio.scan_contexts()

print("Available IIO contexts:\n")
for uri, description in contexts.items():
    match = SERIAL_RE.search(description)
    serial = match.group(1) if match else "UNKNOWN"
    print(f"URI:         {uri}")
    print(f"Description: {description}")
    print(f"Serial:      {serial}")
    print("-" * 60)