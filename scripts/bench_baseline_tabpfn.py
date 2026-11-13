import argparse
import importlib
import os
from time import perf_counter

from bench_smoke import SEED, penguins_split


def main() -> None:
    """Probe the optional v2 baseline without selecting the gated default model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["v2"], required=True)
    parser.add_argument("--smoke", action="store_true", required=True)
    parser.parse_args()
    if os.environ.get("TABPFN_TOKEN"):
        message = "Unset TABPFN_TOKEN to verify the unauthenticated v2 smoke."
        raise SystemExit(message)

    tabpfn = importlib.import_module("tabpfn")
    constants = importlib.import_module("tabpfn.constants")

    train, test = penguins_split()
    classifier = tabpfn.TabPFNClassifier.create_default_for_version(
        constants.ModelVersion.V2, device="cpu", random_state=SEED
    )
    start = perf_counter()
    classifier.fit(train.drop(columns="species"), train["species"])
    predictions = classifier.predict(test.drop(columns="species"))
    accuracy = float((predictions == test["species"].to_numpy()).mean())
    print(
        f"TabPFN v2: labels={len(train)} rows={len(test)} accuracy={accuracy:.6f} "
        f"seconds={perf_counter() - start:.6f} TABPFN_TOKEN=unset"
    )


if __name__ == "__main__":
    main()
