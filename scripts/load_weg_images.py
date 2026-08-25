"""Provision the full-resolution WEG image set into a geo-agent deployment.

The 11,476 ODIN live originals never ride git or the docker image — they load
into the deployment's object store (MinIO primary inside the backend
container, mirrored per the artifact-storage direction) through the ingest
endpoint, keyed exactly as the seed's images_index paths.

  python3 scripts/load_weg_images.py <images_dir> [--base http://localhost:9845/api/v1]

--base is the deployment's API ROOT: http://localhost:9845/api/v1 on a box,
https://<host>/geo-api/v1 through a consumer proxy.

<images_dir> is a directory of image files whose names ARE the odin/ object
names (the assembly output backend/app/data/weg_images/odin, or any copy of
it). Resumable: presence is tracked by a local ledger file next to the
source dir.
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request


def put(base, name, path, token=None):
    url = base.rstrip("/") + "/equipment/images/odin/" + urllib.parse.quote(name)
    ctype = mimetypes.guess_type(name)[0] or "image/jpeg"
    with open(path, "rb") as fh:
        body = fh.read()
    headers = {"Content-Type": ctype}
    if token:
        headers["X-Provisioning-Token"] = token
    req = urllib.request.Request(url, data=body, method="PUT",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images_dir")
    ap.add_argument("--base", default="http://localhost:9845/api/v1")
    ap.add_argument("--token", default=os.environ.get("WEG_IMAGES_INGEST_TOKEN"))
    args = ap.parse_args()

    ledger_path = os.path.join(os.path.dirname(os.path.abspath(args.images_dir)),
                               "weg_images_upload_ledger.json")
    done = set()
    if os.path.exists(ledger_path):
        done = set(json.load(open(ledger_path)))

    names = sorted(os.listdir(args.images_dir))
    todo = [n for n in names if n not in done and not n.startswith(".")]
    print(f"objects: {len(names)} | already uploaded: {len(done)} | to upload: {len(todo)}",
          flush=True)
    ok = fail = 0
    for i, name in enumerate(todo, 1):
        try:
            status = put(args.base, name, os.path.join(args.images_dir, name), token=args.token)
            if status == 200:
                ok += 1
                done.add(name)
            else:
                fail += 1
                print(f"  {name}: HTTP {status}", flush=True)
        except Exception as exc:
            fail += 1
            print(f"  {name}: {exc}", flush=True)
        if i % 500 == 0 or i == len(todo):
            json.dump(sorted(done), open(ledger_path, "w"))
            print(f"[{i}/{len(todo)}] ok={ok} fail={fail}", flush=True)
    json.dump(sorted(done), open(ledger_path, "w"))
    print(f"DONE ok={ok} fail={fail}", flush=True)
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
