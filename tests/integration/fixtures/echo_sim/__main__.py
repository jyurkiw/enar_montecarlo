"""``python -m echo_sim`` entry point.

Python 3.13's ``python -m <pkg>`` requires a ``__main__`` submodule;
the if-name-main trick in ``__init__.py`` is not enough. Importing
the package and passing it explicitly to ``main()`` ensures the
framework discovers the sim attributes correctly regardless of how
the CLI was invoked.
"""

import echo_sim
from enar_montecarlo import main

if __name__ == "__main__":  # pragma: no cover
    main(sim_module=echo_sim)
