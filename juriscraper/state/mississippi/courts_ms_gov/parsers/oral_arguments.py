"""Parser for the Mississippi oral-argument pane (``docket_type=oralarg``).

Either an empty pane or one or more ``<a>`` links (typically Vimeo URLs)
under a ``#archList`` table. Each link becomes an ``MsAppOralArgument``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jkent.common.deferred_validation import DeferredValidation
from jkent.common.parser import JKentParser
from jkent.data_types import XPath

from juriscraper.state.mississippi.courts_ms_gov.models import (
    MsAppOralArgument,
)

from ._common import strip

if TYPE_CHECKING:
    from jkent.common.page_element import PageElement


class OralArgumentsParser(JKentParser[MsAppOralArgument]):
    """Parse the oral-argument links into ``MsAppOralArgument`` records."""

    def __call__(
        self, page: PageElement
    ) -> list[DeferredValidation[MsAppOralArgument]]:
        oral_links = page.query(
            XPath("//table[@id='archList']//a"),
            "oral arg links",
            min_count=0,
        )
        out: list[DeferredValidation[MsAppOralArgument]] = []
        for link in oral_links:
            urls = link.query_strings(
                XPath("./@href"), "oral arg href", min_count=0, max_count=1
            )
            if not urls:
                continue
            label = strip(link.text_content())
            out.append(MsAppOralArgument.raw(url=urls[0], label=label or None))
        return out
