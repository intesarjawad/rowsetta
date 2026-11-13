import errno
import os
import shlex
import socket
import sys
import webbrowser
from argparse import ArgumentParser, ArgumentTypeError, Namespace
from ipaddress import IPv4Address
from pathlib import Path
from typing import get_args
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI

from rowsetta.api.routes import ExportFormat
from rowsetta.api.security import SessionSecurity
from rowsetta.app import LaunchCsv, create_app, local_teacher
from rowsetta.core.errors import BYTES_PER_MB, FileTooLargeError, UserError
from rowsetta.core.export.sql import Dialect
from rowsetta.core.table import MAX_FILE_BYTES
from rowsetta.core.teacher import Teacher
from rowsetta.doctor import doctor, fetch_checkpoint
from rowsetta.headless import export_session

DATASETS = Path(__file__).parent / "datasets"
DEMOS = ("penguins", "bank", "adult")
MAX_PORT = 65535


def main() -> None:
    """Run one command; expected failures print `error:` and `Next:` lines and exit 1."""
    parser = _parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    try:
        if args.command == "export":
            output = export_session(args.session, export_format=args.format, dialect=args.dialect)
            sys.stdout.write(output)
        elif args.command == "doctor":
            doctor(fix=args.fix)
        else:
            _serve(parser, args)
    except UserError as error:
        sys.stderr.write(f"error: {error.what}\nNext: {error.next_step}\n")
        raise SystemExit(1) from error


def _port(value: str) -> int:
    message = "must be an integer in 1..65535"
    try:
        port = int(value)
    except ValueError as error:
        raise ArgumentTypeError(message) from error
    if not 1 <= port <= MAX_PORT:
        raise ArgumentTypeError(message)
    return port


def _parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="rowsetta",
        description="Rowsetta: local tabular labelling and rule export.",
    )
    commands = parser.add_subparsers(dest="command")
    open_csv = commands.add_parser("open", help="Label a local CSV in the browser app")
    open_csv.add_argument("path", type=Path)
    open_csv.add_argument(
        "--max-file-mb",
        type=_positive_int,
        default=MAX_FILE_BYTES // BYTES_PER_MB,
        help="raise the file size limit (default %(default)s MB)",
    )
    open_csv.add_argument(
        "--columns", type=_column_names, help="keep only these comma-separated columns"
    )
    demo = commands.add_parser("demo", help="Label a bundled dataset in the browser app")
    demo.add_argument("name", nargs="?", choices=DEMOS, default="penguins")
    for command in (open_csv, demo):
        command.add_argument("--host", default="127.0.0.1")
        command.add_argument("--port", type=_port, default=8787)
        command.add_argument("--no-browser", action="store_true")
        command.add_argument(
            "--offline",
            action="store_true",
            help="fail instead of downloading the model when it is not cached",
        )
    export = commands.add_parser("export", help="Refit a saved session and print its rule")
    export.add_argument("session", type=Path)
    export.add_argument("--format", choices=get_args(ExportFormat.__value__), default="sql")
    export.add_argument("--dialect", choices=get_args(Dialect.__value__), default="duckdb")
    check = commands.add_parser("doctor", help="Check the model runtime and checkpoint")
    check.add_argument(
        "--fix",
        action="store_true",
        help="delete a checkpoint that fails its checksum and download it again",
    )
    return parser


def _serve(parser: ArgumentParser, args: Namespace) -> None:
    try:
        security = SessionSecurity.for_host(args.host)
    except ValueError as error:
        parser.error(str(error))
    if args.command == "open":
        csv = LaunchCsv(
            args.path,
            session_beside=True,
            max_bytes=args.max_file_mb * BYTES_PER_MB,
            columns=args.columns,
        )
        app = _open(csv, security, offline=args.offline)
        loaded = str(args.path)
    else:
        csv = LaunchCsv(DATASETS / f"{args.name}.csv", session_beside=False)
        app = create_app(teacher=_teacher(offline=args.offline), security=security, csv=csv)
        loaded = csv.path.name
    with _listen(args) as listener:
        browser_host = "127.0.0.1" if args.host == str(IPv4Address(0)) else args.host
        url = f"http://{browser_host}:{args.port}/?{urlencode({'token': security.token})}"
        # Flushed before the server blocks, so a pipe sees the address immediately.
        sys.stdout.write(f"Loaded {loaded}\nOpen {url}\nPress Ctrl+C to stop.\n")
        sys.stdout.flush()
        if not args.no_browser:
            webbrowser.open(url)
        server = uvicorn.Server(
            uvicorn.Config(app, host=args.host, port=args.port, access_log=False)
        )
        try:
            server.run(sockets=[listener])
        except KeyboardInterrupt:
            return


def _listen(args: Namespace) -> socket.socket:
    try:
        return socket.create_server((args.host, args.port))
    except OSError as error:
        message = f"Could not bind {args.host}:{args.port}: {error.strerror}."
        if error.errno != errno.EADDRINUSE:
            raise UserError(message, "rowsetta demo --host 127.0.0.1") from error
        with socket.create_server((args.host, 0)) as alternative:
            port = alternative.getsockname()[1]
        retry = ["rowsetta", *sys.argv[1:]]
        if "--port" in retry:
            retry[retry.index("--port") + 1] = str(port)
        else:
            retry = [part for part in retry if not part.startswith("--port=")]
            retry.extend(["--port", str(port)])
        raise UserError(message, shlex.join(retry)) from error


def _open(csv: LaunchCsv, security: SessionSecurity, *, offline: bool) -> FastAPI:
    try:
        size = csv.path.stat().st_size
    except OSError as error:
        raise _unreadable(csv.path, error) from error
    # Checked before reading, so an oversized file never enters memory.
    if size > csv.max_bytes:
        raise FileTooLargeError(size, csv.max_bytes, file_name=str(csv.path))
    teacher = _teacher(offline=offline)
    try:
        return create_app(teacher=teacher, security=security, csv=csv)
    except OSError as error:
        raise _unreadable(csv.path, error) from error


def _teacher(*, offline: bool) -> Teacher:
    # The fake teacher has no weights, so tests and the states gallery never download.
    if os.environ.get("ROWSETTA_TEACHER") != "fake":
        fetch_checkpoint(offline=offline, retry=shlex.join(["rowsetta", *sys.argv[1:]]))
    return local_teacher()


def _unreadable(path: Path, error: OSError) -> UserError:
    message = f"Could not read `{path}`: {error.strerror}."
    return UserError(message, "rowsetta open <path to a readable CSV>")


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        message = f"expected a whole number of megabytes, got {value!r}"
        raise ArgumentTypeError(message) from error
    if number <= 0:
        message = f"expected a positive number of megabytes, got {value}"
        raise ArgumentTypeError(message)
    return number


def _column_names(value: str) -> tuple[str, ...]:
    names = tuple(value.split(","))
    if not all(names):
        message = f"expected comma-separated column names, got {value!r}"
        raise ArgumentTypeError(message)
    return names
