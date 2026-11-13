# 0002: A local web app, not a desktop wrapper

Status: accepted.

## Decision

`rowsetta open` and `rowsetta demo` start a FastAPI server on
`127.0.0.1` and open the Svelte page in the user's own browser. There is no
Electron, Tauri or other desktop shell.

## Why

- **One install line.** The Python package already carries the teacher, the
  core and the exporters. A wheel with the built page inside it installs with
  `uvx` on macOS, Linux and Windows; a desktop shell would add a signed binary
  per platform and its own update channel.
- **One UI for two runtimes.** The page reaches the server only through the
  frontend's `Backend` interface, so the static browser demo can put the same
  Python core, running in Pyodide, behind it without a second UI.
- **Headless use stays first class.** The CLI, the HTTP API and the library
  export (`docs/library.md`) need no window, so CI can re-export a rule from a
  saved session.

## Consequences

A local server is reachable by other processes and web pages on the same
machine, so it needs its own security model: [ADR 0010](0010-localhost-security.md).
The page cannot read files the user did not choose; CSVs arrive by upload or
by the path given to `rowsetta open`.
