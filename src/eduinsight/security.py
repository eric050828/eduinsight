"""Streaming HTTP limits and safe client error responses."""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from .config import settings
from .db import is_locked

logger = logging.getLogger(__name__)
CHUNK_BYTES = 64 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def upload_limit(path: str, method: str) -> int | None:
    if method != "POST":
        return None
    if re.fullmatch(r"/courses/[^/]+/materials/?", path):
        return settings.max_material_bytes
    if re.fullmatch(r"/lectures/[^/]+/upload/?", path):
        return settings.max_lecture_bytes
    if path.rstrip("/") == "/import":
        return settings.max_import_bytes
    if re.fullmatch(r"/assignments/[^/]+/submission/files/?", path):
        from .submission_files import MAX_FILE_BYTES
        return MAX_FILE_BYTES
    return None


def too_large() -> HTTPException:
    return HTTPException(413, "payload_too_large")


class BodyLimitMiddleware:
    """Reject on receive, before Starlette can spool an entire upload.

    Count actual multipart file bytes as well as the total wire body. Content
    type alone never exempts a route from the ordinary body limit. Chunked
    requests receive the same protection as requests with Content-Length.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        file_limit = upload_limit(scope["path"], scope["method"])
        body_limit = (file_limit + MULTIPART_OVERHEAD_BYTES
                      if file_limit is not None else settings.max_body_bytes)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await JSONResponse({"detail": "invalid_content_length"}, 400)(scope, receive, send)
            return
        if length > body_limit:
            await JSONResponse({"detail": "payload_too_large"}, 413)(scope, receive, send)
            return

        parser = None
        if file_limit is not None:
            content_type, options = parse_options_header(headers.get(b"content-type", b""))
            if content_type == b"multipart/form-data" and b"boundary" in options:
                file_size = 0
                is_file = False
                field = bytearray()
                value = bytearray()

                def part_begin():
                    nonlocal file_size, is_file
                    file_size, is_file = 0, False

                def header_field(data, start, end):
                    if len(field) + end - start > MULTIPART_OVERHEAD_BYTES:
                        raise too_large()
                    field.extend(data[start:end])

                def header_value(data, start, end):
                    if len(value) + end - start > MULTIPART_OVERHEAD_BYTES:
                        raise too_large()
                    value.extend(data[start:end])

                def header_end():
                    nonlocal is_file
                    if field.lower() == b"content-disposition":
                        _, params = parse_options_header(bytes(value))
                        is_file = b"filename" in params
                    field.clear()
                    value.clear()

                def part_data(data, start, end):
                    nonlocal file_size
                    if is_file:
                        file_size += end - start
                        if file_size > file_limit:
                            raise too_large()

                parser = MultipartParser(options[b"boundary"], {
                    "on_part_begin": part_begin,
                    "on_header_field": header_field,
                    "on_header_value": header_value,
                    "on_header_end": header_end,
                    "on_part_data": part_data,
                })

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received += len(body)
                try:
                    if received > body_limit:
                        raise too_large()
                    if parser is not None:
                        parser.write(body)
                except HTTPException:
                    if parser is not None:
                        # Starlette closes already-spooled parts on this exception.
                        # Its Request converts it to 400; our HTTP handler restores 413.
                        raise MultiPartException("payload_too_large") from None
                    raise
            return message

        await self.app(scope, limited_receive, send)


async def stage_upload(file: UploadFile, limit: int, *, suffix: str = "") -> tuple[str, int]:
    """Copy bounded chunks to disk and clean partial files on any failure."""
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as out:
            path = out.name
            size = 0
            while chunk := await file.read(CHUNK_BYTES):
                size += len(chunk)
                if size > limit:
                    raise too_large()
                out.write(chunk)
        return path, size
    except BaseException:
        if path is not None:
            Path(path).unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def safe_error(exc: BaseException, code: str = "invalid_request") -> str:
    """Keep exception details in logs; propagate SQLite contention to its handler."""
    if is_locked(exc):
        raise exc
    logger.error("%s", code, exc_info=(type(exc), exc, exc.__traceback__))
    return code


async def database_error_handler(request, exc):
    if is_locked(exc):
        logger.warning("SQLite database busy", exc_info=exc)
        return JSONResponse({"detail": "database_busy"}, 503, headers={"Retry-After": "1"})
    return await server_error_handler(request, exc)


async def server_error_handler(request, exc):
    logger.error("Unhandled request error", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse({"detail": "internal_server_error"}, 500)


async def http_error_handler(request, exc: StarletteHTTPException):
    status = 413 if exc.detail == "payload_too_large" else exc.status_code
    return JSONResponse({"detail": exc.detail}, status, headers=exc.headers)
