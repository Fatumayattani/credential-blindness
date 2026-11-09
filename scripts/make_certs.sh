#!/usr/bin/env bash
# PRE-SPRINT: generate a fictional research certificate chain (root -> intermediate -> signer).
# For research use only. Not a real publisher identity.
set -euo pipefail
OUT="${1:-certs}"
mkdir -p "$OUT" && cd "$OUT"

cat > root.cnf << 'C'
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3
[dn]
CN = Valley Press Root CA
O = Valley Press Credentials Authority
C = XX
[v3]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
C

cat > inter.cnf << 'C'
[req]
distinguished_name = dn
prompt = no
[dn]
CN = Valley Press Issuing CA
O = Valley Press Credentials Authority
C = XX
[v3]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
C

cat > signer.cnf << 'C'
[req]
distinguished_name = dn
prompt = no
[dn]
CN = Valley Press Signing Service
O = Valley Press Credentials Authority
C = XX
[v3]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = emailProtection
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
C

openssl ecparam -name prime256v1 -genkey -noout -out root.key
openssl req -new -x509 -key root.key -sha256 -days 3650 -config root.cnf -out root.pem

openssl ecparam -name prime256v1 -genkey -noout -out inter.key
openssl req -new -key inter.key -config inter.cnf -out inter.csr
openssl x509 -req -in inter.csr -CA root.pem -CAkey root.key -CAcreateserial -sha256 -days 1825 \
  -extfile inter.cnf -extensions v3 -out inter.pem

openssl ecparam -name prime256v1 -genkey -noout -out signer.key.ec
openssl pkcs8 -topk8 -nocrypt -in signer.key.ec -out signer.key
openssl req -new -key signer.key -config signer.cnf -out signer.csr
openssl x509 -req -in signer.csr -CA inter.pem -CAkey inter.key -CAcreateserial -sha256 -days 365 \
  -extfile signer.cnf -extensions v3 -out signer.pem

cat signer.pem inter.pem > chain.pem
cp signer.pem allowed.pem
rm -f *.csr *.srl signer.key.ec
echo "Certificates written to $(pwd)"
