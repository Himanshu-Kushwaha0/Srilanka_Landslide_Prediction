#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fix Unicode encoding issues in model script."""

import os

script_path = r"c:\Users\kushw\Downloads\test\Srilanka_Landslide_Prediction\Srilanka_Landslide_Prediction\APP\Prediction Script\landslide_model_v2_filtered.py"

# Read the file with UTF-8 encoding
with open(script_path, 'rb') as f:
    raw_bytes = f.read()

# Decode with UTF-8
try:
    content = raw_bytes.decode('utf-8')
except:
    content = raw_bytes.decode('utf-8', errors='replace')

# List of problematic characters and their replacements
replacements = [
    ('▶', '>>'),
    ('◀', '<<'),
    ('█', '#'),
    ('═', '='),
    ('─', '-'),
    ('┌', '+'),
    ('┐', '+'),
    ('└', '+'),
    ('┘', '+'),
    ('├', '|'),
    ('┤', '|'),
    ('┬', '+'),
    ('┴', '+'),
    ('║', '|'),
    ('…', '...'),
    ('•', '*'),
    ('✓', '[OK]'),
    ('✗', '[X]'),
    ('→', '->'),
    ('←', '<-'),
    ('≤', '<='),
    ('≥', '>='),
]

count = 0
for unicode_char, ascii_char in replacements:
    old_content = content
    content = content.replace(unicode_char, ascii_char)
    if content != old_content:
        count += len(old_content) - len(content)
        print(f"Replaced '{repr(unicode_char)}' with '{ascii_char}'")

# Write back as UTF-8
with open(script_path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\n[OK] Fixed {script_path}")
print(f"Total replacements: {count}")
