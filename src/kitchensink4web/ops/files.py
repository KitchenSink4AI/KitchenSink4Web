"""The `files` pack: downloads and uploads (DESIGN 2.2).

DEMAND: downloads are literally unserved by all four surveyed servers and
chronically broken in the incumbents (a bare UUID with no extension, a
completion callback that never fires, an issue open with zero comments
since 2025-10). It is also the only row a single-purpose competitor
structurally cannot match, because a downloaded xlsx is what KS4XL consumes.

Both tools mutate (a download writes a file, an upload sets a file input),
so both are absent under read-only mode and both pass the policy choke
point. Downloads and uploads touch the filesystem, so every path is checked
against KS4WEB_ALLOWED_ROOTS, and a download to disk and a file upload are
gated action classes that fail closed until a human confirms.

The download lifecycle is explicit, which is the fix for the incumbent's
"callback never fired": trigger the download by acting, WAIT for it with a
real timeout, and report the saved path with the extension preserved from
the suggested filename, never a bare UUID.
"""

from __future__ import annotations

import asyncio
import os

from ..errors import BadParams, ModalBlocked, TargetNotFound, Timeout
from ..policy import engine as _policy
from ..policy import sandbox
from . import act as _act
from . import common


def _pending(sess) -> list:
    store = getattr(sess, "_downloads", None)
    if store is None:
        store = sess._downloads = []
    return store


async def download(
    page: str,
    action: str = "wait",
    location: dict | None = None,
    url: str | None = None,
    path: str | None = None,
    timeout_ms: int = 30000,
    request_id: str | None = None,
) -> dict:
    """Handle the download lifecycle explicitly, which is the fix for the
    incumbents' silent breakage. 'click' arms a download listener and then
    clicks the located trigger; 'goto' navigates to a direct file URL;
    'wait' blocks for a download to finish; 'list' reports what has
    completed. The saved file keeps the extension from its suggested name
    rather than becoming a bare UUID, and saving to disk is a gated action
    that fails closed until a human confirms. Returns the saved path, the
    suggested filename, and the byte count. Files land in the scoped
    downloads directory unless a path is named.
    """
    actions = ("click", "goto", "wait", "list")
    if action not in actions:
        raise BadParams(
            f"unknown download action {action!r}: the actions are "
            f"{list(actions)}.")
    sess, record = common.locate(page)
    store = _pending(sess)

    if action == "list":
        return {"page": record.handle, "session": sess.session_id,
                "downloads": [{k: d[k] for k in
                               ("suggested", "saved_to", "bytes")}
                              for d in store]}

    # The download-to-disk gate (DESIGN 5.4) rides on the policy choke point
    # via action_class below, so it is asked ONLY on a path that actually
    # writes and, with no MRTR wiring in this build, FAILS CLOSED there.
    if action in ("click", "goto"):
        async with record.page.expect_download(
                timeout=timeout_ms) as info:
            if action == "click":
                if not location:
                    raise BadParams(
                        "download(action='click') needs a location naming "
                        "the download trigger.")
                resolved = await _act.resolve(sess, record, location,
                                              tool="download")
                _policy.approve(_policy.ActionRequest(
                    tool="download", kind="download",
                    session=sess.session_id, page=record.handle,
                    url=record.page.url, target=resolved["descriptor"],
                    action_class="download_to_disk",
                    args={"action": "click"},
                    summary=f"download via {resolved['descriptor'].get('name')}"
                            f" on {record.handle}"))
                await resolved["handle"].click(timeout=timeout_ms)
            else:
                if not url:
                    raise BadParams(
                        "download(action='goto') needs the file url.")
                _policy.approve(_policy.ActionRequest(
                    tool="download", kind="download",
                    session=sess.session_id, page=record.handle, url=url,
                    action_class="download_to_disk",
                    args={"action": "goto", "url": url},
                    summary=f"download {url} on {record.handle}"))
                try:
                    await record.page.goto(url, timeout=timeout_ms)
                except Exception:
                    pass  # a download URL aborts the navigation by design
            download_obj = await info.value
        return await _finish(sess, record, download_obj, path)

    # action == "wait": a download armed by some other action.
    try:
        download_obj = await asyncio.wait_for(
            record.page.wait_for_event("download"),
            timeout=timeout_ms / 1000)
    except asyncio.TimeoutError as exc:
        raise Timeout(
            f"no download started within {timeout_ms} ms. Arm one with "
            f"download(action='click', location=...) in the same call, or "
            f"trigger it and then wait; a download that never starts is "
            f"usually a click that hit the wrong element.") from exc
    _policy.approve(_policy.ActionRequest(
        tool="download", kind="download", session=sess.session_id,
        page=record.handle, action_class="download_to_disk",
        args={"action": "wait"},
        summary=f"save the download on {record.handle}"))
    return await _finish(sess, record, download_obj, path)


async def _finish(sess, record, download_obj, path) -> dict:
    suggested = download_obj.suggested_filename or "download"
    if path:
        out = sandbox.check_path(path, "save download")
    else:
        # Keep the suggested extension; never a bare UUID (browser-use #1951).
        out = sandbox.check_path(
            str(common.downloads_dir() / suggested), "save download")
    await download_obj.save_as(out)
    size = os.path.getsize(out) if os.path.exists(out) else 0
    record_entry = {"suggested": suggested, "saved_to": out, "bytes": size}
    _pending(sess).append(record_entry)
    return {
        "page": record.handle, "session": sess.session_id,
        "saved_to": out, "suggested_filename": suggested, "bytes": size,
        "note": ("the suggested extension is preserved; the file is in the "
                 "sandbox-checked downloads directory. A downloaded "
                 "spreadsheet opens directly in Excel or KS4XL."),
    }


async def upload_file(
    page: str,
    location: dict,
    files: list,
    timeout_ms: int = 15000,
) -> dict:
    """Set files on a file input, addressed by any selector. Every path is
    read-checked against KS4WEB_ALLOWED_ROOTS (an upload exfiltrates file
    content to the site as surely as a read does), the file input is
    driven the way a real chooser would fill it, and uploading is a gated
    action that fails closed until a human confirms. For a page that uses a
    synthetic-DataTransfer dropzone rather than a real input, the refusal
    says so and names the input route. Returns which files were set and the
    input's own report of what it now holds, so a silently rejected upload
    is visible rather than assumed.
    """
    if not files or not isinstance(files, list):
        raise BadParams(
            "upload_file needs a non-empty list of file paths to set on "
            "the input.")
    checked = [sandbox.check_path(f, "upload file") for f in files]
    for f in checked:
        if not os.path.exists(f):
            raise TargetNotFound(
                f"the file to upload does not exist: {f}.")
    sess, record = common.locate(page)
    resolved = await _act.resolve(sess, record, location, tool="upload_file")
    unit = resolved["unit"]
    tag = (unit.get("tag") or "").upper()
    ftype = (unit.get("type") or "").lower()
    if not (tag == "INPUT" and ftype == "file"):
        raise ModalBlocked(
            "the located element is not a file input. A page using a "
            "synthetic-DataTransfer dropzone (a div that listens for drop "
            "events) has a hidden <input type=file> behind it in almost "
            "every case; address that input by css ('input[type=file]') "
            "instead of the dropzone, and KS4Web sets it directly.")
    _policy.approve(_policy.ActionRequest(
        tool="upload_file", kind="act", session=sess.session_id,
        page=record.handle, url=record.page.url,
        target=resolved["descriptor"], action_class="file_upload",
        args={"files": len(checked)},
        summary=f"upload {len(checked)} file(s) to the input on "
                f"{record.handle}"))
    await resolved["handle"].set_input_files(checked, timeout=timeout_ms)
    now = await record.page.evaluate(
        "(el) => Array.from(el.files || []).map(f => "
        "({name: f.name, bytes: f.size}))", resolved["handle"])
    return {
        "page": record.handle, "session": sess.session_id,
        "set": [os.path.basename(f) for f in checked],
        "input_reports": now,
    }


#: The pack roster, in DESIGN 2.2 order.
TOOLS = (download, upload_file)
