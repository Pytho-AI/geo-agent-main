"""WOPI host + editor viewer plumbing — the pattern is PORTED from the
IBL implementation (pytho-app origin/ibl app/app/handlers/wopi.py +
ui/src/components/LiveEditor.tsx), adapted to this engine's storage
(MinIO objects instead of the uploads/ tree) and lifecycle law.

The load-bearing IBL lessons, kept intact here:

- WOPISrc is keyed by the STABLE artifact_id, never by a minted token.
  A per-mint token in the URL made every open a "new" document URL, so
  coolwsd paid a docbroker/kit cold-start per refresh — and every
  viewer got a PRIVATE document session, which silently breaks shared
  editing. The token rides the access_token query param instead, which
  coolwsd passes back on every WOPI request per spec.
- Per-user identity claims in the token (user_id, display name) make
  the editor render distinct collaborator cursors per analyst.
- CheckFileInfo carries the cache contract: SupportsUpdate,
  SupportsLocks=False (the editor's collab session is the concurrency
  primitive — no WOPI-side locks), Version; GetFile/PutFile answer
  X-WOPI-ItemVersion; PutFile answers LastModifiedTime.
- Every save fires an editor.save analyst event with a structural
  fingerprint diff — editor activity is never invisible to telemetry.

Tokens, honestly: artifact-scoped, expiring, HMAC-signed — they
prevent casual URL sharing and stale-link reuse under the platform's
advisory-identity status quo; they are NOT access control.

Write rule = the lifecycle law, nothing else: drafts are shared-
editable (PutFile persists the bytes onto the draft's MinIO object in
place), and writes lock on final/approved FOREVER — PutFile refuses
them at write time. The world-model read-back from edited drafts is
the loops-phase agentic loop; the file bytes always keep analyst
work."""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.analyst_event import AnalystEvent
from app.models.products import ProductRecord

log = logging.getLogger(__name__)
router = APIRouter()

EDITOR = os.environ.get("EDITOR_URL", "http://127.0.0.1:9980").rstrip("/")
# The editor runs under service_root=/geo-api/v1/editor (its asset
# URLs are absolute and must route back through this proxy); forward
# the FULL prefixed path.
EDITOR_PREFIX = "/geo-api/v1/editor"
_SECRET = os.environ.get(
    "WOPI_TOKEN_SECRET", "geo-agent-wopi-dev-secret").encode()
TOKEN_TTL_S = int(os.environ.get("WOPI_TOKEN_TTL_S", "604800"))  # 7 days


def _sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode(),
                    hashlib.sha256).hexdigest()[:32]


def mint_token(record_id: str, artifact_id: str,
               user_id: str, user_name: str) -> str:
    body = json.dumps({"r": record_id, "a": artifact_id,
                       "u": user_id, "n": user_name,
                       "exp": int(time.time()) + TOKEN_TTL_S})
    b = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return f"{b}.{_sign(b)}"


def read_token(token: str) -> dict:
    try:
        b, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(b)):
            raise ValueError("bad signature")
        body = json.loads(base64.urlsafe_b64decode(
            b + "=" * (-len(b) % 4)))
        if body["exp"] < time.time():
            raise ValueError("expired")
        return body
    except Exception as e:
        raise HTTPException(401, f"invalid wopi token: {e}")


def _verify_access(artifact_id: str, access_token: str | None) -> dict:
    """The IBL access pattern: the stable artifact_id is the path key;
    the token authenticates via the access_token query param and must
    match the path."""
    if not access_token:
        raise HTTPException(401, "access_token query param required")
    t = read_token(access_token)
    if str(t.get("a")) != str(artifact_id):
        raise HTTPException(403, "access_token artifact mismatch")
    return t


async def _artifact(db, record_id: str, artifact_id: str):
    r = await db.get(ProductRecord, UUID(record_id))
    if r is None:
        raise HTTPException(404, "no such record")
    art = next((a for a in (r.artifacts or [])
                if a.get("artifact_id") == artifact_id), None)
    if art is None:
        raise HTTPException(404, "no such artifact")
    return r, art


# -- WOPI protocol (the editor subprocess calls these) ---------------

@router.get("/products/wopi/files/{artifact_id}")
async def check_file_info(artifact_id: str,
                          access_token: str | None = Query(None),
                          db: AsyncSession = Depends(get_db)):
    t = _verify_access(artifact_id, access_token)
    record, art = await _artifact(db, t["r"], artifact_id)
    from app.services.products import artifacts as store
    size, version_ms = store.head_object(art["object_key"])
    # The lifecycle law IS the write rule: drafts are shared-editable,
    # final/approved are locked forever. PutFile re-checks at write
    # time — this answer only shapes the editor chrome.
    editable = record.lifecycle == "draft"
    return JSONResponse({
        "BaseFileName": art["filename"],
        "Size": size,
        "Version": str(version_ms),
        "OwnerId": "geo-agent",
        "UserId": t.get("u") or "analyst",
        "UserFriendlyName": t.get("n") or t.get("u") or "Analyst",
        "UserCanWrite": editable,
        "ReadOnly": not editable,
        "UserCanNotWriteRelative": True,
        "SupportsUpdate": True,
        "SupportsLocks": False,  # editor collab session handles co-edit
        "SupportsRename": False,
        "PostMessageOrigin": "*",
        "DisablePrint": False,
        "DisableExport": False,
        "DisableCopy": False,
        "EnableInsertRemoteImage": False,
        "HidePrintOption": False,
        "HideSaveOption": False,
        "HideExportOption": False,
    })


@router.get("/products/wopi/files/{artifact_id}/contents")
async def get_file_contents(artifact_id: str,
                            access_token: str | None = Query(None),
                            db: AsyncSession = Depends(get_db)):
    t = _verify_access(artifact_id, access_token)
    _, art = await _artifact(db, t["r"], artifact_id)
    from app.services.products import artifacts as store
    data, ctype = store.get_object(art["object_key"])
    _, version_ms = store.head_object(art["object_key"])
    return Response(content=data, media_type=ctype, headers={
        "X-WOPI-ItemVersion": str(version_ms)})


@router.post("/products/wopi/files/{artifact_id}/contents")
async def put_file_contents(artifact_id: str, request: Request,
                            access_token: str | None = Query(None),
                            db: AsyncSession = Depends(get_db)):
    """WOPI PutFile — the editor saving analyst edits. Bytes land on
    the draft's MinIO object in place (same artifact_id, same
    object_key — editing a draft is not a lifecycle event)."""
    t = _verify_access(artifact_id, access_token)
    record, art = await _artifact(db, t["r"], artifact_id)
    if record.lifecycle != "draft":
        # Lock-on-final, enforced at the write moment — a stale editor
        # session on a since-finalized record gets a refusal, not a
        # silent success.
        raise HTTPException(
            409, f"writes are locked: record is {record.lifecycle}")
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty PutFile body")
    from app.services.products import artifacts as store
    ctype = art.get("content_type", "application/octet-stream")
    prior = None
    try:
        prior, _ = store.get_object(art["object_key"])
    except Exception as e:
        log.warning("put_file: prior-bytes snapshot failed: %s", e)
    store.put_bytes(art["object_key"], body, ctype)
    _, version_ms = store.head_object(art["object_key"])
    # editor.save analyst event with the structural fingerprint diff —
    # best-effort: telemetry never breaks the save flow.
    try:
        fmt = os.path.splitext(art["filename"])[1].lstrip(".").lower()
        prior_fp = _structural_fingerprint(prior, fmt) if prior else None
        new_fp = _structural_fingerprint(body, fmt)
        now_ms = int(time.time() * 1000)
        db.add(AnalystEvent(
            occurred_at_ms=now_ms, received_at_ms=now_ms,
            user_id=t.get("u") or "", map_id=str(record.project_id),
            surface="editor", event_type="editor.save",
            detail={
                "record_id": str(record.id),
                "artifact_id": artifact_id,
                "product_type": record.product_type,
                "format": fmt,
                "bytes": len(body),
                "prior_bytes": len(prior) if prior else 0,
                "wopi_version": str(version_ms),
                "fingerprint": new_fp,
                "delta_vs_prior": _fingerprint_delta(prior_fp, new_fp),
            }))
        await db.commit()
    except Exception as e:
        log.warning("put_file: editor.save event failed: %s", e)
    return JSONResponse(
        {"LastModifiedTime": datetime.fromtimestamp(
            version_ms / 1000, tz=timezone.utc).isoformat()},
        headers={"X-WOPI-ItemVersion": str(version_ms)})


# -- The viewer/editor entry (the record page opens this) ------------

@router.get("/products/records/{record_id}/artifacts/{artifact_id}/view")
async def open_viewer(record_id: UUID, artifact_id: str,
                      request: Request,
                      user_id: str = Query("analyst"),
                      user_name: str = Query("Analyst"),
                      db: AsyncSession = Depends(get_db)):
    """Minimal page hosting the editor iframe. URL shape follows IBL's
    LiveEditor: /editor/browser/dist/cool.html (the dist path is
    stable — no discovery round-trip) with WOPISrc keyed by the stable
    artifact_id and the token in access_token. Everything rides this
    service's own public surface."""
    record, _ = await _artifact(db, str(record_id), artifact_id)
    token = mint_token(str(record_id), artifact_id, user_id, user_name)
    # The public base: honor the proxy's forwarded headers (nginx
    # rewrites /geo-api/* -> /api/* before the backend sees it, and
    # terminates TLS — request.base_url lies on both axes). The
    # externally-reachable prefix is ALWAYS /geo-api/v1: consumers
    # route it, and the backend serves it natively in standalone.
    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host",
                               request.headers.get("host", ""))
    base = f"{scheme}://{host}/geo-api/v1"
    # The browser never fetches WOPISrc — the EDITOR calls it back, so
    # it must be an origin the editor's container can reach (the
    # Docker-internal one), never the external hairpin. Env-driven per
    # deployment; the unified image defaults to loopback.
    internal = os.environ.get(
        "WOPI_INTERNAL_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
    wopi_src = f"{internal}/api/v1/products/wopi/files/{artifact_id}"
    permission = ("edit" if record.lifecycle == "draft"
                  else "readonly")
    params = (f"WOPISrc={wopi_src}&access_token={token}"
              f"&permission={permission}"
              "&ui_defaults=compactMode%3Dtrue%3BTextRuler%3Dfalse%3B"
              "PresentationStatusbar%3Dfalse&closebutton=0")
    cool = f"{base}/editor/browser/dist/cool.html?{params}"
    return HTMLResponse(
        "<!doctype html><html><head><title>Product document"
        "</title><style>html,body,iframe{margin:0;height:100%;"
        "width:100%;border:0}</style></head><body>"
        f'<iframe src="{cool}" allow="clipboard-read; '
        'clipboard-write"></iframe></body></html>')


# -- Proxy: editor statics + WebSocket through the one surface -------

@router.api_route("/editor/{path:path}",
                  methods=["GET", "POST", "HEAD"])
async def editor_proxy(path: str, request: Request):
    # the FULL prefixed path it expects.
    url = f"{EDITOR}{EDITOR_PREFIX}/{path}"
    # The editor builds the CLIENT-FACING URLs (its WebSocket, image
    # bases) from the Host + X-Forwarded-* it sees — forward the
    # original public host or the browser gets wss://127.0.0.1.
    public_host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", ""))
    fwd = {k: v for k, v in request.headers.items()
           if k.lower() in ("content-type", "accept",
                            "accept-encoding")}
    fwd["Host"] = public_host
    fwd["X-Forwarded-Host"] = public_host
    fwd["X-Forwarded-Proto"] = request.headers.get(
        "x-forwarded-proto", "https")
    async with httpx.AsyncClient(timeout=60) as cx:
        upstream = await cx.request(
            request.method, url,
            params=dict(request.query_params),
            content=await request.body(),
            headers=fwd)
    drop = {"transfer-encoding", "connection", "content-encoding",
            "content-length"}
    out_headers = {k: v for k, v in upstream.headers.items()
                   if k.lower() not in drop}
    # This editor build's own CSP omits 'unsafe-inline' from
    # style-src and then blocks its own cool.html inline style
    # (observed raw in the console). The backend fronts it — patch
    # the policy here, scoped to the /editor path only.
    csp = out_headers.get("content-security-policy")
    if csp and "style-src  'self'" in csp:
        out_headers["content-security-policy"] = csp.replace(
            "style-src  'self'", "style-src  'self' 'unsafe-inline'")
    return Response(
        content=upstream.content, status_code=upstream.status_code,
        headers=out_headers)


@router.websocket("/editor/{path:path}")
async def editor_ws(websocket: WebSocket, path: str):
    """Bidirectional WebSocket pump to the editor on loopback."""
    import asyncio
    import websockets as wslib
    await websocket.accept(
        subprotocol=websocket.headers.get("sec-websocket-protocol"))
    # The {path:path} param arrives percent-DECODED, but the editor's
    # session path embeds a fully-encoded WOPISrc URL — decoding turns
    # http%3A%2F%2F into http:// and path normalization collapses the
    # slashes, so the upstream rejects the session with HTTP 400.
    # Rebuild the upstream target from the RAW request path so the
    # encoding crosses the bridge byte-for-byte.
    raw_path = (websocket.scope.get("raw_path") or b"").decode("latin-1")
    _, _, raw_tail = raw_path.partition("/editor/")
    qs = str(websocket.url.query)
    target = (f"{EDITOR.replace('http', 'ws', 1)}"
              f"{EDITOR_PREFIX}/{raw_tail or path}"
              + (f"?{qs}" if qs else ""))
    try:
        # compression=None: the in-container editor's handshake parser
        # rejects the client library's permessage-deflate extension
        # offer with a bare HTTP 400 (isolated by probe matrix
        # 2026-07-27); the browser leg never negotiates compression
        # with us either, so the bridge stays uncompressed end to end.
        async with wslib.connect(target, max_size=None,
                                 compression=None) as upstream:
            async def down():
                async for msg in upstream:
                    if isinstance(msg, bytes):
                        await websocket.send_bytes(msg)
                    else:
                        await websocket.send_text(msg)

            async def up():
                while True:
                    m = await websocket.receive()
                    if m.get("type") == "websocket.disconnect":
                        break
                    if m.get("bytes") is not None:
                        await upstream.send(m["bytes"])
                    elif m.get("text") is not None:
                        await upstream.send(m["text"])

            done, pending = await asyncio.wait(
                [asyncio.create_task(down()),
                 asyncio.create_task(up())],
                return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception as e:
        log.info("editor ws closed: %s", e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# -- Structural fingerprint + diff (ported from IBL wopi.py) ---------

def _structural_fingerprint(blob, fmt: str) -> dict:
    """Coarse structural fingerprint of a saved file — per-cell /
    per-paragraph snapshots so consecutive saves diff into the analyst
    activity record. Lazy per-format imports; {} on parse failure
    (best-effort, exactly like the IBL original)."""
    if not blob:
        return {}
    try:
        if fmt == "pptx":
            import io
            from pptx import Presentation  # type: ignore
            pres = Presentation(io.BytesIO(blob))
            slides = []
            for si, slide in enumerate(pres.slides):
                tables = []
                shapes = []
                for sh_i, sh in enumerate(slide.shapes):
                    sh_name = sh.name or ""
                    if sh.has_table:
                        tbl = sh.table
                        cells = [[(c.text_frame.text or "")
                                  for c in row.cells]
                                 for row in tbl.rows]
                        tables.append({
                            "shape_name": sh_name,
                            "rows": len(tbl.rows),
                            "cols": len(tbl.columns),
                            "cells": cells,
                        })
                    tf = getattr(sh, "text_frame", None)
                    if tf is not None:
                        shapes.append({
                            "shape_name": sh_name,
                            "shape_index": sh_i,
                            "paragraphs": [(p.text or "")
                                           for p in tf.paragraphs],
                        })
                slides.append({"slide_index": si, "tables": tables,
                               "shapes": shapes})
            return {"format": "pptx", "slides": slides,
                    "n_slides": len(slides)}
        if fmt == "xlsx":
            import io
            from openpyxl import load_workbook  # type: ignore
            wb = load_workbook(io.BytesIO(blob), data_only=True,
                               read_only=True)
            sheets = []
            for sn in wb.sheetnames:
                ws = wb[sn]
                rows = []
                max_r = min(ws.max_row or 0, 200)
                max_c = min(ws.max_column or 0, 50)
                for r in range(1, max_r + 1):
                    rows.append([
                        "" if ws.cell(row=r, column=c).value is None
                        else str(ws.cell(row=r, column=c).value)
                        for c in range(1, max_c + 1)])
                sheets.append({"sheet": sn, "rows": ws.max_row,
                               "cols": ws.max_column, "cells": rows})
            return {"format": "xlsx", "sheets": sheets,
                    "n_sheets": len(sheets)}
        if fmt == "docx":
            import io
            from docx import Document  # type: ignore
            doc = Document(io.BytesIO(blob))
            paragraphs = [(p.text or "") for p in doc.paragraphs]
            tables = []
            for ti, tb in enumerate(doc.tables):
                tables.append({
                    "table_index": ti,
                    "rows": len(tb.rows),
                    "cols": len(tb.columns),
                    "cells": [[(cell.text or "") for cell in row.cells]
                              for row in tb.rows],
                })
            return {"format": "docx",
                    "n_paragraphs": len(paragraphs),
                    "n_tables": len(tables),
                    "paragraphs": paragraphs,
                    "tables": tables}
    except Exception as e:
        log.warning("structural_fingerprint(%s) failed: %s", fmt, e)
        return {}
    return {}


def _fingerprint_delta(prior, new) -> dict:
    """Compact diff of two structural fingerprints (IBL original)."""
    if not prior or not new:
        return {"baseline": prior is None}
    delta: dict = {}
    fmt = new.get("format") or prior.get("format")
    delta["format"] = fmt
    if fmt == "docx":
        delta["paragraphs_before"] = prior.get("n_paragraphs")
        delta["paragraphs_after"] = new.get("n_paragraphs")
        delta["tables_before"] = prior.get("n_tables")
        delta["tables_after"] = new.get("n_tables")
        return delta
    if fmt == "xlsx":
        prior_sheets = prior.get("sheets") or []
        new_sheets = new.get("sheets") or []
        changes = []
        for si in range(max(len(prior_sheets), len(new_sheets))):
            p_s = prior_sheets[si] if si < len(prior_sheets) else {}
            n_s = new_sheets[si] if si < len(new_sheets) else {}
            if (p_s.get("rows") != n_s.get("rows")
                    or p_s.get("cols") != n_s.get("cols")):
                changes.append({
                    "sheet": n_s.get("sheet") or p_s.get("sheet"),
                    "rows_before": p_s.get("rows"),
                    "rows_after": n_s.get("rows"),
                    "cols_before": p_s.get("cols"),
                    "cols_after": n_s.get("cols")})
        delta["sheets_changed"] = changes
        return delta
    if fmt == "pptx":
        prior_slides = prior.get("slides") or []
        new_slides = new.get("slides") or []
        changed = []
        for si in range(max(len(prior_slides), len(new_slides))):
            p_sl = prior_slides[si] if si < len(prior_slides) else {}
            n_sl = new_slides[si] if si < len(new_slides) else {}
            if p_sl != n_sl:
                changed.append(si)
        delta["slides_changed"] = changed
        return delta
    return delta
