"""Run the browser-test server with an error log checked by Playwright teardown."""

import logging
import os

from rowsetta.cli import main

if __name__ == "__main__":
    errors = logging.FileHandler(os.environ["ROWSETTA_E2E_ERROR_LOG"])
    errors.setLevel(logging.ERROR)
    logging.getLogger().addHandler(errors)
    main()
