# Pytho LiveEditor — runtime graphic enumeration via UNO.
#
# Called from the host page via PostMessage:
#
#   { MessageId: "CallPythonScript",
#     ScriptFile: "pytho_graphics.py",
#     Function:   "get_graphic_objects",
#     Values:     {} }
#
# Returns (via CallPythonScript-Result postMessage from the editor) a JSON
# array of graphics in the currently-open document. Each entry carries the
# graphic's name, alt-text (Title + Description per UNO API), and its
# bounding box in twips. The host page uses the alt-text to join entries
# to the map_embeds.json sidecar (we set alt-text at write time to
# `pytho-map:<map_id>`), then converts twips → viewport pixels via
# app.map._docLayer._twipsToLatLng and overlays the Edit Map button on
# each map's bottom-right corner.
#
# IMPORTANT REQUIREMENT: this script depends on the Collabora packages
# `collaboraofficebasis-python-script-provider` and
# `collaboraofficebasis-pyuno`, which are NOT installed in the
# `collabora/code` base image. patch-editor.sh installs them at container
# start. Without them every CallPythonScript fails with
# `ScriptFrameworkErrorException: invalid attempt to assign an empty
# interface of type com.sun.star.script.provider.XScriptProvider!`.
#
# Position-resolution strategy for Writer documents:
#   Writer inline images (AnchorType=AS_CHARACTER) have NO `Position`
#   property — their place on the page is determined at layout time by
#   text flow. The only reliable way to read the runtime layout position
#   is to programmatically `controller.select(graphic)`, then read the
#   view cursor's Position (doc-cumulative 1/100 mm coordinates), and
#   immediately deselect to avoid leaving a visible selection on the
#   user's screen.
#
# UNO coordinate units:
#   - getViewCursor().Position.X / .Y are in 1/100 mm, doc-cumulative
#   - Size.Width / .Height are in 1/100 mm
#   - twips = (1/100 mm) * 1440 / 2540
#     (1 inch = 2540 1/100-mm = 1440 twips)

import json

_TWIPS_PER_100_MM = 1440.0 / 2540.0


def _to_twips(uno_units_100th_mm):
    return int(round(uno_units_100th_mm * _TWIPS_PER_100_MM))


def _read_alt(g):
    """Pull alt-text (Title + Description) off a TextGraphicObject."""
    title = ""
    desc = ""
    try:
        info = g.getPropertySetInfo()
        if info and info.hasPropertyByName("Title"):
            title = g.getPropertyValue("Title") or ""
        if info and info.hasPropertyByName("Description"):
            desc = g.getPropertyValue("Description") or ""
    except Exception:
        pass
    return title, desc


def _resolve_position(controller, g):
    """Select the graphic so Writer commits its layout position, read
    the view cursor, then deselect. Returns (page, x_twips, y_twips) or
    (None, None, None) on failure. Deselect runs even on the failure
    branch to avoid leaving an analyst staring at a stale selection."""
    if controller is None:
        return None, None, None
    try:
        controller.select(g)
        vc = controller.getViewCursor()
        page = None
        try:
            page = vc.Page
        except Exception:
            pass
        pos = vc.Position  # com.sun.star.awt.Point, 1/100 mm
        x = _to_twips(pos.X)
        y = _to_twips(pos.Y)
        try:
            controller.select(None)
        except Exception:
            pass
        return page, x, y
    except Exception:
        try:
            controller.select(None)
        except Exception:
            pass
        return None, None, None


def get_graphic_objects():
    try:
        doc = XSCRIPTCONTEXT.getDocument()
    except Exception as e:
        return json.dumps({"error": "no document context: " + str(e), "graphics": []})
    controller = None
    try:
        controller = doc.getCurrentController()
    except Exception:
        pass

    out = []
    # Writer: GraphicObjects holds every embedded TextGraphicObject.
    # Calc / Impress surface shapes through DrawPages instead. Today
    # only Writer DOCX uses this code path for live-edit map overlays;
    # extend when wiring up Calc / Impress maps.
    if hasattr(doc, "getGraphicObjects"):
        try:
            gos = doc.getGraphicObjects()
            for name in gos.getElementNames():
                try:
                    g = gos.getByName(name)
                except Exception as e:
                    out.append({"name": name, "error": "fetch failed: " + str(e)})
                    continue
                title, desc = _read_alt(g)
                # Size is independent of layout — always queryable.
                try:
                    size = g.Size
                    w_twips = _to_twips(size.Width)
                    h_twips = _to_twips(size.Height)
                except Exception:
                    w_twips = h_twips = 0
                page, x_twips, y_twips = _resolve_position(controller, g)
                out.append({
                    "name": name,
                    "title": title,
                    "description": desc,
                    "page_index": (page - 1) if (page is not None and page > 0) else None,
                    "x_twips": x_twips,
                    "y_twips": y_twips,
                    "w_twips": w_twips,
                    "h_twips": h_twips,
                })
        except Exception as e:
            out.append({"error": "enum failed: " + str(e)})

    return json.dumps({"graphics": out})


def replace_picture(*pos_args, **kw_args):
    """Replace a picture (Impress slide or Writer page graphic) by its
    Name property OR by slide_index fallback with the bytes at
    `image_url`. Used by LiveEditor's Done-editing flow to swap a
    re-rendered map into the OPEN document without forcing the iframe
    to reload — the analyst stays on their current slide and skips
    Collabora's 15-45s parse-from-scratch.

    Wire shape: the host posts {map_id, image_url, slide_index} in
    CallPythonScript Values. Collabora's UNO bridge marshals that into
    positional args in insertion order. To be robust to any reorder
    or naming difference, we accept both *pos_args and **kw_args and
    resolve them by either route. When neither route gives us a
    workable url+map_id, we dump what arrived to aid debugging.

    Match order:
      1. shape.Name == "pytho-map:<map_id>"   (exporter stamps this on
         new renders; precise even when a slide carries multiple
         pictures)
      2. First Picture shape on slide_index   (fallback for older
         artifacts whose pictures don't have the join-key name yet)

    Args (resolved from pos_args[0..2] OR kw_args by name):
        map_id: join key. The PPTX exporter sets pic.name to
                "pytho-map:<map_id>".
        image_url: absolute file:// URL OR a bare path. The /uploads
                tree on docker-api is bind-mounted into the editor
                container read-only at /uploads, so a path like
                `/uploads/_autodraft/<aid>/<filename>.jpg` resolves.
        slide_index: 0-based slide index for the fallback match. Pass
                map_embeds.json entry.slide_index. None disables the
                fallback.

    Returns:
        JSON string {status, count, matched, error?}. status:
            "replaced"  → one or more shapes updated
            "not_found" → no shape matched name or slide_index
            "error"     → exception details in `error`
    """
    # Resolve args from positional OR keyword. Whichever wire shape
    # Collabora delivers, both routes get checked.
    try:
        if len(pos_args) >= 2:
            map_id = pos_args[0]
            image_url = pos_args[1]
            slide_index = pos_args[2] if len(pos_args) >= 3 else None
        else:
            map_id = kw_args.get("map_id")
            image_url = kw_args.get("image_url")
            slide_index = kw_args.get("slide_index")
    except Exception:
        map_id = image_url = slide_index = None
    if not image_url or not map_id:
        # Dump what arrived so the host log shows the actual wire shape.
        return json.dumps({
            "status": "error",
            "error": "could not resolve args (image_url or map_id missing)",
            "pos_count": len(pos_args),
            "pos_args_repr": [repr(a)[:200] for a in pos_args],
            "kw_keys": list(kw_args.keys()),
            "kw_args_repr": {k: repr(v)[:200] for k, v in kw_args.items()},
        })
    try:
        import uno  # noqa: F401  (registers the bridge)
        from com.sun.star.beans import PropertyValue
    except Exception as e:
        return json.dumps({"status": "error", "error": "uno import failed: " + str(e)})
    try:
        doc = XSCRIPTCONTEXT.getDocument()
    except Exception as e:
        return json.dumps({"status": "error", "error": "no document context: " + str(e)})
    try:
        ctx = XSCRIPTCONTEXT.getComponentContext()
        smgr = ctx.getServiceManager()
        gp = smgr.createInstanceWithContext(
            "com.sun.star.graphic.GraphicProvider", ctx)
    except Exception as e:
        return json.dumps({"status": "error", "error": "graphic provider unavailable: " + str(e)})
    # Normalize the URL. Bare paths get file:// prefix.
    if not image_url.startswith(("file://", "http://", "https://")):
        image_url = "file://" + image_url
    media_url = PropertyValue()
    media_url.Name = "URL"
    media_url.Value = image_url
    try:
        new_graphic = gp.queryGraphic((media_url,))
    except Exception as e:
        return json.dumps({"status": "error",
                            "error": "queryGraphic failed: " + str(e),
                            "url": image_url})
    if new_graphic is None:
        return json.dumps({"status": "error",
                            "error": "graphic not loadable",
                            "url": image_url})
    target_name = "pytho-map:" + str(map_id)
    replaced = 0
    matched_via = None

    def _swap_graphic_on(shape):
        # Swap the Graphic property in-place. Older LO releases used
        # GraphicURL; modern (LO 6.1+ / Collabora 22+) uses the Graphic
        # XGraphic object directly. Both are tried — whichever the build
        # supports wins.
        try:
            shape.Graphic = new_graphic
            return True
        except Exception:
            pass
        try:
            shape.setPropertyValue("Graphic", new_graphic)
            return True
        except Exception:
            pass
        try:
            shape.setPropertyValue("GraphicURL", image_url)
            return True
        except Exception:
            return False

    def _is_picture_shape(shape):
        # supportsService is the canonical way to check shape type.
        # Pictures expose com.sun.star.presentation.GraphicObjectShape OR
        # com.sun.star.drawing.GraphicObjectShape depending on context.
        try:
            return (shape.supportsService("com.sun.star.drawing.GraphicObjectShape")
                    or shape.supportsService("com.sun.star.presentation.GraphicObjectShape"))
        except Exception:
            return False

    try:
        if hasattr(doc, "getDrawPages"):
            pages = doc.getDrawPages()
            n_pages = pages.getCount()
            all_pages = [pages.getByIndex(i) for i in range(n_pages)]
        elif hasattr(doc, "DrawPage"):
            all_pages = [doc.DrawPage]
        else:
            return json.dumps({"status": "error", "error": "no draw pages on document"})

        # ─ Pass 1: match by Name ────────────────────────────────────
        for page in all_pages:
            try:
                n_shapes = page.getCount()
            except Exception:
                continue
            for j in range(n_shapes):
                shape = page.getByIndex(j)
                name = ""
                try:
                    name = shape.Name or ""
                except Exception:
                    pass
                if name != target_name:
                    continue
                if _swap_graphic_on(shape):
                    replaced += 1
                    matched_via = "name"
        if replaced > 0:
            return json.dumps({"status": "replaced", "count": replaced,
                                "matched_via": matched_via,
                                "url": image_url, "name": target_name})

        # ─ Pass 2: fallback to first Picture shape on slide_index ────
        # Frontend marshals slide_index<0 as the "no fallback" signal
        # because PropertyValue marshaling can't cleanly express None.
        try:
            si = int(slide_index) if slide_index is not None else -1
        except Exception:
            si = -1
        if 0 <= si < len(all_pages):
            page = all_pages[si]
            try:
                n_shapes = page.getCount()
            except Exception:
                n_shapes = 0
            for j in range(n_shapes):
                shape = page.getByIndex(j)
                if not _is_picture_shape(shape):
                    continue
                if _swap_graphic_on(shape):
                    replaced += 1
                    matched_via = "slide_index"
                    break
        if replaced > 0:
            return json.dumps({"status": "replaced", "count": replaced,
                                "matched_via": matched_via,
                                "url": image_url, "slide_index": si})
        return json.dumps({"status": "not_found", "name": target_name,
                            "slide_index": slide_index, "url": image_url})
    except Exception as e:
        return json.dumps({"status": "error", "error": "iter failed: " + str(e)})


g_exportedScripts = (get_graphic_objects, replace_picture)
