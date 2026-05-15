#!/usr/bin/env python
"""Fix Unicode encoding issues in model script."""

import os
import sys

script_path = r"c:\Users\kushw\Downloads\test\Srilanka_Landslide_Prediction\Srilanka_Landslide_Prediction\APP\Prediction Script\landslide_model_v2_filtered.py"

# Read the file with UTF-8 encoding
with open(script_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace Unicode box-drawing and arrow characters with ASCII equivalents
replacements = {
    '▶': '>',
    '◀': '<',
    '█': '#',
    '═': '=',
    '─': '-',
    '┌': '+',
    '┐': '+',
    '└': '+',
    '┘': '+',
    '├': '|',
    '┤': '|',
    '┬': '+',
    '┴': '+',
    '─': '-',
    '║': '|',
    '…': '...',
    '•': '*',
    '✓': 'OK',
    '✗': 'FAIL',
    '→': '->',
    '←': '<-',
}

for unicode_char, ascii_char in replacements.items():
    if unicode_char in content:
        print(f"Replacing '{unicode_char}' with '{ascii_char}'")
        content = content.replace(unicode_char, ascii_char)

# Write back with UTF-8 encoding (Python should handle encoding properly)
with open(script_path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\n✓ Fixed {script_path}")
print("All Unicode characters replaced with ASCII equivalents")
