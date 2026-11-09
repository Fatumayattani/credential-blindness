# PRE-SPRINT: harness scaffolding (render, sign, tamper, credential views). No study data.
"""
Build document images and Content Credential views for one task.

Uses the C2PA reference SDK (c2pa-python, built on c2pa-rs) with a fictional
research certificate chain from scripts/make_certs.sh.

Usage:
    python scripts/build_sources.py data/tasks/example_task.json

Outputs to data/manifests/<task_id>/:
    <key>_plain.jpg     rendered source documents (T, P, F1, F2), unsigned
    T_signed.jpg        T with a valid credential
    P_signed.jpg        P with a valid credential (used to build the lookalike view)
    P_tampered.jpg      P_signed with one byte flipped after signing
    credentials.json    S1 raw view and S2 verifier verdict per variant
"""
import json
import sys
import textwrap
from pathlib import Path

import c2pa
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
CERTS = ROOT / "certs"
MANIFEST_DIR = ROOT / "data" / "manifests"
GENERATOR = "credential-blindness/0.1"
PUBLISHER_LABEL = "org.credentialblindness.publisher"


def verifier_name():
    return f"C2PA SDK (c2pa-rs {c2pa.sdk_version()})"


def make_signer():
    info = c2pa.C2paSignerInfo(
        b"es256",
        (CERTS / "chain.pem").read_bytes(),
        (CERTS / "signer.key").read_bytes(),
        None,
    )
    return c2pa.Signer.from_info(info)


def trust_context():
    return c2pa.Context.from_dict(
        {"verify": {"verify_trust": True}, "trust": {"user_anchors": (CERTS / "root.pem").read_text()}}
    )


def render(doc, path):
    font_title = ImageFont.load_default(size=26)
    font_body = ImageFont.load_default(size=18)
    lines = textwrap.wrap(doc["text"], width=70)
    height = 140 + 26 * len(lines)
    img = Image.new("RGB", (900, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((40, 30), doc["outlet"], font=font_body, fill=(90, 90, 90))
    d.text((40, 60), doc["title"], font=font_title, fill=(0, 0, 0))
    y = 110
    for line in lines:
        d.text((40, y), line, font=font_body, fill=(20, 20, 20))
        y += 26
    img.save(path, quality=92)


def manifest_def(doc):
    return {
        "claim_generator": GENERATOR,
        "title": doc["title"],
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
                        }
                    ]
                },
            },
            {"label": PUBLISHER_LABEL, "data": {"publisher": doc["outlet"]}},
        ],
    }


def sign(src, dst, doc, signer):
    builder = c2pa.Builder(json.dumps(manifest_def(doc)))
    with open(src, "rb") as s, open(dst, "w+b") as d:
        builder.sign(signer, "image/jpeg", s, d)


def tamper(src, dst):
    data = bytearray(Path(src).read_bytes())
    data[len(data) - 100] ^= 0xFF
    Path(dst).write_bytes(data)


def read_report(path, ctx):
    try:
        with open(path, "rb") as f:
            return json.loads(c2pa.Reader("image/jpeg", f, context=ctx).json())
    except c2pa.C2paError:
        return None  # no manifest in file


def raw_view(report):
    """S1: what the manifest says, with no validation result."""
    m = report["manifests"][report["active_manifest"]]
    assertions = {a["label"]: a.get("data") or {} for a in m.get("assertions", [])}
    actions = (assertions.get("c2pa.actions.v2") or assertions.get("c2pa.actions") or {}).get("actions", [])
    generator = m.get("claim_generator") or (m.get("claim_generator_info") or [{}])[0].get("name")
    sig = m.get("signature_info") or {}
    return {
        "standard": "C2PA Content Credentials",
        "claim_generator": generator,
        "title": m.get("title"),
        "publisher": assertions.get(PUBLISHER_LABEL, {}).get("publisher"),
        "actions": [a.get("action") for a in actions],
        "signature": {
            "alg": sig.get("alg"),
            "issuer": sig.get("issuer"),
            "common_name": sig.get("common_name"),
        },
    }


def verdict(report):
    """S2: what the verifier says after checking the file."""
    if report is None:
        return {"verifier": verifier_name(), "validation_state": "None", "result": "No Content Credentials found in file"}
    failures = [
        {"code": s.get("code"), "explanation": s.get("explanation")}
        for s in report.get("validation_status", [])
        if not str(s.get("code", "")).endswith(".trusted")
    ]
    return {"verifier": verifier_name(), "validation_state": report.get("validation_state"), "failures": failures}


def main(task_path):
    if not (CERTS / "root.pem").exists():
        sys.exit("No certs found. Run: bash scripts/make_certs.sh certs")

    task = json.loads(Path(task_path).read_text())
    out = MANIFEST_DIR / task["task_id"]
    out.mkdir(parents=True, exist_ok=True)
    src = task["sources"]
    signer = make_signer()
    ctx = trust_context()

    for key, doc in src.items():
        render(doc, out / f"{key}_plain.jpg")

    sign(out / "T_plain.jpg", out / "T_signed.jpg", src["T"], signer)
    sign(out / "P_plain.jpg", out / "P_signed.jpg", src["P"], signer)
    tamper(out / "P_signed.jpg", out / "P_tampered.jpg")

    rep_t = read_report(out / "T_signed.jpg", ctx)
    rep_ps = read_report(out / "P_signed.jpg", ctx)
    rep_pt = read_report(out / "P_tampered.jpg", ctx)
    rep_pl = read_report(out / "P_plain.jpg", ctx)
    if None in (rep_t, rep_ps, rep_pt):
        sys.exit("Verifier returned no manifest for a signed file. Check signing.")

    creds = {
        "T_valid": {"raw": raw_view(rep_t), "verdict": verdict(rep_t)},
        "P_tampered": {"raw": raw_view(rep_pt), "verdict": verdict(rep_pt)},
        # Lookalike: identical S1 view to a real credential, but the file itself carries none.
        "P_lookalike": {"raw": raw_view(rep_ps), "verdict": verdict(rep_pl)},
    }
    (out / "credentials.json").write_text(json.dumps(creds, indent=2))

    print(f"Task: {task['task_id']}  ({verifier_name()})")
    ok = True
    for k, want in {"T_valid": "Trusted", "P_tampered": "Invalid", "P_lookalike": "None"}.items():
        got = creds[k]["verdict"]["validation_state"]
        good = got == want
        ok &= good
        print(f"  [{'OK ' if good else 'BAD'}] {k:12s} expected {want:8s} got {got}")
    same = creds["P_tampered"]["raw"] == creds["P_lookalike"]["raw"]
    ok &= same
    print(f"  [{'OK ' if same else 'BAD'}] S1 raw views identical for P_tampered and P_lookalike")
    print("All checks passed." if ok else "Some checks failed.")
    print(f"Wrote {out / 'credentials.json'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/build_sources.py <task.json>")
    main(sys.argv[1])
