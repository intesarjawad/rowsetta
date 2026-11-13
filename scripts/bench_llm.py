import importlib
import json
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.request import OpenerDirector, Request

import pandas as pd
from pydantic import BaseModel, ConfigDict

MODEL = "qwen3.6:35b-a3b"
MODEL_DIGEST = "0ce5ff81f9ffdf89dd8192ca7b5d34cefd8996a875b3aaaaafaf5c4813569eba"
LLM_EVAL_ROWS = 200
REQUEST_TIMEOUT_SECONDS = 600


class Message(BaseModel):
    """The non-streaming assistant content returned by Ollama."""

    content: str


class ChatResponse(BaseModel):
    """Require completion rather than timing a partial generation."""

    message: Message
    done: bool


class Label(BaseModel):
    """Accept one class, with no commentary or extra fields."""

    model_config = ConfigDict(extra="forbid")
    label: str


class ModelTag(BaseModel):
    """Identify the local model artifact independently of its mutable tag."""

    name: str
    digest: str


class TagsResponse(BaseModel):
    """Validate the local model inventory before running the smoke."""

    models: list[ModelTag]


def row_text(row: pd.Series, columns: list[str]) -> str:
    """Preserve CSV column order in the shared prompt prefix."""
    return "; ".join(f"{column}={row[column]}" for column in columns)


def predict_label(
    opener: OpenerDirector,
    prompt: str,
    classes: list[str],
    *,
    seed: int = 7,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Constrain a local chat response to the known class names."""
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": seed},
        "format": {
            "type": "object",
            "properties": {"label": {"type": "string", "enum": classes}},
            "required": ["label"],
            "additionalProperties": False,
        },
    }
    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        result = ChatResponse.model_validate_json(response.read())
    if not result.done:
        message = "Ollama returned an incomplete generation."
        raise ValueError(message)
    label = Label.model_validate_json(result.message.content).label
    if label not in classes:
        message = f"Ollama returned an unknown class: {label}"
        raise ValueError(message)
    return label


def verify_model(opener: OpenerDirector) -> None:
    """Refuse missing or changed local artifacts before requesting a label."""
    with opener.open(
        "http://127.0.0.1:11434/api/tags", timeout=REQUEST_TIMEOUT_SECONDS
    ) as response:
        tags = TagsResponse.model_validate_json(response.read())
    matches = [model for model in tags.models if model.name == MODEL]
    if len(matches) != 1:
        message = f"Model missing; run: ollama pull {MODEL}"
        raise SystemExit(message)
    if matches[0].digest != MODEL_DIGEST:
        message = "Model digest changed; restore the artifact recorded in ADR 0011."
        raise SystemExit(message)


def main() -> None:
    """Run the cached local-LLM comparison on shared random-strategy label sets."""
    importlib.import_module("scripts.bench_llm_run").run()


if __name__ == "__main__":
    main()
