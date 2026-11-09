# PRE-SPRINT: tooling notes (no tasks, data, or results)

c2patool 0.27.22, Ubuntu (glibc 2.39). Built-in test signing cert (es256).

Sign:      c2patool in.jpg -m manifest.json -f -o signed.jpg
Tamper:    flip one byte near end of JPEG scan data (len - 100)
Trust:     c2patool signed.jpg --certs > chain.pem ; keep first cert -> allowed.pem
Validate:  c2patool file.jpg trust --allowed_list allowed.pem

Verified states:
- unsigned:  "No claim found"
- valid:     signingCredential.trusted, assertion.dataHash.match, validation_state Trusted
- tampered:  signingCredential.trusted, assertion.dataHash.mismatch, validation_state Invalid
