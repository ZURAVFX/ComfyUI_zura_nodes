"""Check relative Markdown file links without fetching external websites."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
errors = []
# Check repository-owned files only, including historical guides.
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '*.md'], cwd=ROOT).decode('utf-8').split('\0')
for name in sorted(set(filter(None, files))):
    path = ROOT / name
    if not path.is_file():
        continue
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    # Angle brackets allow filenames with spaces and parentheses.
    for match in re.finditer(r'\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)', text):
        target = match[1].strip('<>')
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        destination = ROOT / unquote(parsed.path.lstrip('/')) if parsed.path.startswith('/') else path.parent / unquote(parsed.path)
        if not destination.exists():
            line = text.count('\n', 0, match.start()) + 1
            errors.append(f'{name}:{line}: missing {target}')
if errors:
    raise SystemExit('\n'.join(errors))
print('Relative Markdown file links passed.')
