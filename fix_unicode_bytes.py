#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fix Unicode encoding issues at byte level."""

import os

script_path = r"c:\Users\kushw\Downloads\test\Srilanka_Landslide_Prediction\Srilanka_Landslide_Prediction\APP\Prediction Script\landslide_model_v2_filtered.py"

# Read the file as bytes
with open(script_path, 'rb') as f:
    content = f.read()

# UTF-8 byte sequences for problematic characters
replacements = [
    (b'\xe2\x96\xba', b'>>'),       # ▶
    (b'\xe2\x96\xb0', b'<<'),       # ◀
    (b'\xe2\x88\xa4', b'<='),       # ≤
    (b'\xe2\x88\xa5', b'>='),       # ≥
]

original_size = len(content)
for old_bytes, new_bytes in replacements:
    if old_bytes in content:
        print(f"Replacing {old_bytes} with {new_bytes}")
        content = content.replace(old_bytes, new_bytes)

# Write back
with open(script_path, 'wb') as f:
    f.write(content)

new_size = len(content)
print(f"\n[OK] Fixed {script_path}")
print(f"Size: {original_size} -> {new_size} bytes")
