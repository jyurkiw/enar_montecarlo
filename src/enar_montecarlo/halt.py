"""Stub :class:`HaltException` until ``enar_eventchain`` ships.

The eventchain library will define and own this class; the framework
just needs a name to import and ensure-not-swallow. The framework's
contract is:

* It does **not** catch :class:`HaltException` -- the eventchain
  library catches it at hook-loop boundaries to signal "stop running
  further hooks on this phase".
* If ``HaltException`` escapes the eventchain into the framework
  (e.g. a sim raises it directly inside ``run()``), it propagates
  out of :func:`enar_montecarlo.lifecycle.execute_run` like any
  other exception and triggers the run row's ``terminated_reason
  = 'error'`` cleanup path.

When ``enar_eventchain`` ships, this module re-exports the upstream
class instead of defining its own.
"""


class HaltException(Exception):
    """Signal the current hook phase should stop running further hooks.

    Raised by hooks; caught by the eventchain library; never caught by
    the framework.
    """
