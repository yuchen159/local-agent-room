"""Add a human-facing request to the local room without exposing its token."""
import argparse
import json
import re
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--text', required=True)
parser.add_argument('--priority', choices=('required', 'optional'), default='optional')
parser.add_argument('--owner', choices=('user', 'agents'), default='user')
args = parser.parse_args()
base = 'http://127.0.0.1:8765'
with urllib.request.urlopen(base + '/', timeout=5) as response:
    html = response.read().decode('utf-8')
token = re.search(r'<meta name="room-token" content="([^"]+)"', html).group(1)
payload = json.dumps(vars(args), ensure_ascii=False).encode('utf-8')
request = urllib.request.Request(base + '/api/request-add', data=payload, headers={'Content-Type':'application/json','X-Room-Token':token})
with urllib.request.urlopen(request, timeout=5) as response:
    print(response.read().decode('utf-8'))
