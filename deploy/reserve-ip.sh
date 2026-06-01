#!/bin/bash
set -e

MAC="bc:24:11:d7:79:32"
IP="10.1.0.29"
NAME="spool"
UNIFI_USER="${UNIFI_USER:-claude}"
UNIFI_PASS="${UNIFI_PASS:?Defina UNIFI_PASS antes de rodar}"

echo "==> Login Unifi..."
CSRF=$(curl -sk -c /tmp/uc -D - \
  -X POST https://10.1.1.254/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$UNIFI_USER\",\"password\":\"$UNIFI_PASS\"}" \
  | grep -i 'x-csrf-token:' | tr -d '\r' | awk '{print $2}')

echo "==> Buscando device por MAC $MAC..."
ID=$(curl -sk -b /tmp/uc \
  'https://10.1.1.254/proxy/network/api/s/default/rest/user' \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
match = [c for c in data if c.get('mac') == '$MAC']
print(match[0]['_id'] if match else 'NOT_FOUND')
")

if [ "$ID" = "NOT_FOUND" ]; then
  echo "ERRO: MAC $MAC não encontrado no Unifi. A LXC ainda não apareceu na rede?"
  exit 1
fi

echo "==> Reservando IP $IP para $NAME (ID: $ID)..."
RESULT=$(curl -sk -b /tmp/uc -H "x-csrf-token: $CSRF" \
  -X PUT "https://10.1.1.254/proxy/network/api/s/default/rest/user/$ID" \
  -H 'Content-Type: application/json' \
  -d "{\"fixed_ip\":\"$IP\",\"use_fixedip\":true,\"name\":\"$NAME\"}")

echo "$RESULT" | python3 -c "
import sys, json
r = json.load(sys.stdin)
if r.get('meta',{}).get('rc') == 'ok':
    ip = r['data'][0].get('fixed_ip','?')
    print(f'OK — IP {ip} reservado para $NAME')
else:
    print('ERRO:', r)
"
