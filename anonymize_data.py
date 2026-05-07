#!/usr/bin/env python3
"""Create anonymized version of data.json for public repo."""

import json
from pathlib import Path

# Load real data
data_file = Path(__file__).parent / "docs" / "data.json"
with open(data_file, 'r') as f:
    data = json.load(f)

# Anonymize names - keep first name only
for i, contact in enumerate(data, 1):
    original_name = contact['name']

    # Extract first name (first word before space)
    if ' ' in original_name:
        first_name = original_name.split()[0]
    else:
        first_name = original_name

    contact['name'] = first_name
    contact['identifier'] = "[hidden]"

# Save anonymized version
output_file = Path(__file__).parent / "docs" / "data.sample.json"
with open(output_file, 'w') as f:
    json.dump(data, f, indent=2)

print(f"✓ Created anonymized sample data: {output_file}")
print(f"  {len(data)} contacts with first names only")
print("\nTo use in public repo:")
print("  1. Copy data.sample.json to data.json in docs/ folder")
print("  2. Commit and push")
