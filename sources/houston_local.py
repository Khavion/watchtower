"""City of Houston + Harris County adapter.

Both portals are machine-unreachable for this system (verified 2026-07-24):

- City of Houston: Beacon Bid (beaconbid.com/solicitations/city-of-houston)
  WAF-blocks every non-browser request with HTTP 403, including robots.txt.
  No public API exists.
- Harris County: Bonfire (harriscountytx.bonfirehub.com) is a JS-rendered
  shell whose raw HTML contains no data, and robots.txt disallows all crawling.

The compliant path is vendor registration + NIGP-matched email alerts on both
platforms (TODO(zohaib) in sources.yaml). This adapter implements the source
contract honestly: disabled in config it returns nothing and run_all logs the
documented reason; force-enabled without a real access method it fails loudly
instead of pretending to cover the sources.
"""

from __future__ import annotations

import logging

from pipeline.models import RawSolicitation
from sources.base import SourceAdapter, SourceError

log = logging.getLogger(__name__)


class HoustonLocalAdapter(SourceAdapter):
    source_id = "houston_local"

    def fetch(self) -> list[RawSolicitation]:
        # Reaching fetch() means someone set enabled: true in sources.yaml.
        # There is still no machine-readable access method; refuse loudly
        # rather than silently returning nothing while claiming coverage.
        raise SourceError(
            "houston_local is enabled in sources.yaml but has no machine-readable "
            "access method (Beacon Bid WAF-403s non-browser clients; Harris County "
            "Bonfire is JS-only; verified 2026-07-24). Use the portals' email "
            "alerts instead, or add a real access method before enabling.")
