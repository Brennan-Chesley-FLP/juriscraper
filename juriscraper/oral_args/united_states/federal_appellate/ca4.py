#  Scraper for Fourth Circuit of Appeals
# CourtID: ca4
# Court Short Name: ca4
# Author: Andrei Chelaru
# Reviewer: mlr
# Date created: 18 July 2014

from juriscraper.lib.string_utils import convert_date_string
from juriscraper.OralArgumentSite import OralArgumentSite


class Site(OralArgumentSite):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.court_id = self.__module__
        self.url = "http://www.ca4.uscourts.gov/oral-argument/listen-to-oral-arguments"

    def _get_download_urls(self):
        return list(
            self.html.xpath(  # ty: ignore[possibly-missing-attribute]
                "//tr/td[2]//a/@href"
            )  # ty: ignore[possibly-missing-attribute]
        )  # ty: ignore[possibly-missing-attribute]

    def _get_case_names(self):
        return self.text_from_cell(3)

    def _get_case_dates(self):
        return [convert_date_string(date) for date in self.text_from_cell(1)]

    def _get_judges(self):
        return self.text_from_cell(4)

    def _get_docket_numbers(self):
        return self.text_from_cell(2)

    def text_from_cell(self, cell_number):
        return [
            cell.text_content().strip()
            for cell in self.html.xpath(  # ty: ignore[possibly-missing-attribute]
                "//tr/td[%d]" % cell_number
            )  # ty: ignore[possibly-missing-attribute]
        ]
