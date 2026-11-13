from email import policy
from email.parser import BytesParser
from pathlib import Path

from fastapi import Request
from pydantic import ValidationError

from rowsetta.api.errors import ApiError
from rowsetta.api.schemas import DemoInput
from rowsetta.core.errors import FileTooLargeError
from rowsetta.core.table import MAX_FILE_BYTES

# Permit multipart headers in addition to the CSV byte budget.
MULTIPART_OVERHEAD_BYTES = 65_536


async def table_upload(request: Request) -> tuple[bytes, str]:
    """Read a bounded request and decode one multipart CSV without extra dependencies."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FILE_BYTES + MULTIPART_OVERHEAD_BYTES:
            raise FileTooLargeError(size, MAX_FILE_BYTES)
        chunks.append(chunk)
    body = b"".join(chunks)
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", maxsplit=1)[0] == "application/json":
        try:
            DemoInput.model_validate_json(body)
        except ValidationError as error:
            msg = "Choose the bundled penguins demo."
            raise ApiError(msg, status_code=422) from error
        path = Path(__file__).parents[1] / "datasets" / "penguins.csv"
        return path.read_bytes(), path.name
    if not content_type.startswith("multipart/form-data;"):
        msg = "Upload a multipart CSV or select the penguins demo."
        raise ApiError(msg, status_code=415)
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    parts = list(message.walk())[1:]
    if message.defects or len(parts) != 1 or parts[0].get_content_disposition() != "form-data":
        msg = "Upload exactly one CSV file."
        raise ApiError(msg)
    part = parts[0]
    name = part.get_filename()
    payload = part.get_payload(decode=True)
    if not name or not isinstance(payload, bytes) or part.defects:
        msg = "The CSV upload is incomplete."
        raise ApiError(msg)
    return payload, Path(name).name
