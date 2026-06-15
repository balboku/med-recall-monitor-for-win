import re

html_text = "Some text Published ISO 8601-1:2019/Amd 1:2022 other text..."
base_number = "ISO 8601-1"
escaped_base = re.escape(base_number)
amd_pattern = rf'{escaped_base}:(\d{{4}}[/\+]Amd\s*\d+:\d{{4}})'
amd_matches = re.findall(amd_pattern, html_text, re.IGNORECASE)

print("Matches:", amd_matches)
