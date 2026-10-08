"""Learn2Earn Lender — local equipment lending manager.

A standard-library-only CLI application for tracking equipment inventory and
lending activity within the Learn2Earn organization.

Architecture (see BUILD_PLAN.md):

* ``domain``     — entities, value objects and business errors.
* ``validators`` — reusable input validation primitives.
* ``storage``    — JSON persistence, the append-only event log, and the
                   projections rebuilt from it.
* ``services``   — workflow coordination and business rules.
* ``cli``        — argument parsing and rendering only.

The append-only event log under ``data/transactions/`` is the source of
truth. Everything in ``data/current/`` is a projection that can be deleted
and rebuilt at any time.
"""

__version__ = "0.1.0"
