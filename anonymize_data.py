#!/usr/bin/env python3
"""Create anonymized version of data.json for public repo."""

import json
from pathlib import Path

# Load real data
data_file = Path(__file__).parent / "docs" / "data.json"
with open(data_file, 'r') as f:
    data = json.load(f)

# Anonymize names
for i, contact in enumerate(data, 1):
    contact['name'] = f"Contact {i}"
    contact['identifier'] = "[hidden]"

# Save anonymized version
output_file = Path(__file__).parent / "docs" / "data.sample.json"
with open(output_file, 'w') as f:
    json.dump(data, f, indent=2)

print(f"✓ Created anonymized sample data: {output_file}")
print(f"  {len(data)} contacts anonymized")
print("\nTo use in public repo:")
print("  1. Copy data.sample.json to data.json in docs/ folder")
print("  2. Commit and push")
