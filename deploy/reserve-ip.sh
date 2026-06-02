#!/bin/bash
set -e

NEW_MAC="bc:24:11:97:c4:ca"
OLD_MAC="bc:24:11:d7:79:32"
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

# Liberar IP do MAC antigo se ainda estiver reservado
echo "==> Verificando reserva antiga (MAC $OLD_MAC)..."
OLD_ID=$(curl -sk -b /tmp/uc \
  'https://10.1.1.254/proxy/network/api/s/default/rest/user' \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
match = [c for c in data if c.get('mac') == '$OLD_MAC' and c.get('use_fixedip')]
print(match[0]['_id'] if match else 'NOT_FOUND')
")

if [ "$OLD_ID" != "NOT_FOUND" ]; then
  echo "==> Removendo reserva do MAC antigo (ID: $OLD_ID)..."
  curl -sk -b /tmp/uc -H "x-csrf-token: $CSRF" \
    -X PUT "https://10.1.1.254/proxy/network/api/s/default/rest/user/$OLD_ID" \
    -H 'Content-Type: application/json' \
    -d '{"use_fixedip":false,"fixed_ip":""}' > /dev/null
  echo "    Reserva antiga removida."
fi

# Reservar IP para o novo MAC
echo "==> Buscando novo device (MAC $NEW_MAC)..."
NEW_ID=$(curl -sk -b /tmp/uc \
  'https://10.1.1.254/proxy/network/api/s/default/rest/user' \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
match = [c for c in data if c.get('mac') == '$NEW_MAC']
print(match[0]['_id'] if match else 'NOT_FOUND')
")

if [ "$NEW_ID" = "NOT_FOUND" ]; then
  echo "ERRO: MAC $NEW_MAC não encontrado. A LXC ainda não apareceu na rede?"
  exit 1
fi

echo "==> Reservando IP $IP para $NAME (ID: $NEW_ID)..."
RESULT=$(curl -sk -b /tmp/uc -H "x-csrf-token: $CSRF" \
  -X PUT "https://10.1.1.254/proxy/network/api/s/default/rest/user/$NEW_ID" \
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
