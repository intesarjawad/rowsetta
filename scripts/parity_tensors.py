"""Native tensor boundaries for the browser parity bisect (never used by the teacher)."""

from collections.abc import Callable
from typing import Protocol

import numpy as np
import pandas as pd
import torch
from numpy.typing import NDArray

from rowsetta.teachers.tabicl import Classifier


class Encoder(Protocol):
    """Fitted upstream category encoder."""

    def transform(self, x: pd.DataFrame) -> NDArray[np.float64]:
        """Encode the fitted table."""
        ...


class Ensemble(Protocol):
    """Upstream preprocessing and permutation boundaries."""

    ensemble_configs_: dict[str, list[tuple[NDArray[np.int64], NDArray[np.int64]]]]

    def transform(
        self, x: NDArray[np.float64]
    ) -> dict[str, tuple[NDArray[np.float64], NDArray[np.float64]]]:
        """Construct train-first ensemble tensors."""
        ...


class ParityClassifier(Classifier, Protocol):
    """Additional upstream surfaces used only by the diagnostic harness."""

    X_encoder_: Encoder
    ensemble_generator_: Ensemble
    model_: torch.nn.Module
    inference_config_: object


def tensor_trace(
    model: ParityClassifier, train: pd.DataFrame, test: pd.DataFrame
) -> list[dict[str, object]]:
    """Capture network inputs, boundary rows and logits without modifying predictions."""
    stages: dict[str, object] = {}

    def capture(name: str) -> Callable[[torch.nn.Module, tuple[object, ...], torch.Tensor], None]:
        def hook(
            _module: torch.nn.Module, _inputs: tuple[object, ...], output: torch.Tensor
        ) -> None:
            # Copy before the next module can replace the reserved CLS slots in place.
            value = output[:, [0, -1]].detach().cpu()
            stages[name] = {
                "shape": list(value.shape),
                "data": np.asarray(value, dtype=np.float32).ravel().tolist(),
            }

        return hook

    handles = [
        model.model_.get_submodule(module).register_forward_hook(capture(name))
        for module, name in (("col_embedder", "columns"), ("row_interactor", "rows"))
    ]
    ensemble = model.ensemble_generator_
    traces: list[dict[str, object]] = []
    try:
        for norm, (x, y) in ensemble.transform(model.X_encoder_.transform(test)).items():
            with torch.no_grad():
                logits = model.model_(
                    torch.tensor(x, dtype=torch.float32),
                    torch.tensor(y, dtype=torch.float32),
                    inference_config=model.inference_config_,
                )
            traces.append(
                {
                    "norm": norm,
                    "group": [
                        {"feat": [int(v) for v in feat], "cls": [int(v) for v in cls]}
                        for feat, cls in ensemble.ensemble_configs_[norm]
                    ],
                    "encoded": model.X_encoder_.transform(train).T.tolist(),
                    "X": x.astype(np.float32).ravel().tolist(),
                    "dims": list(x.shape),
                    "y": y.ravel().tolist(),
                    "logits": logits.flatten().tolist(),
                    "logitDims": list(logits.shape),
                    "stages": dict(stages),
                }
            )
    finally:
        for handle in handles:
            handle.remove()
    return traces
