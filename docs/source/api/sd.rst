Scraper Definitions (sd)
========================

The ``sd`` package contains scraper implementations for specific courts using
the new scraper-driver architecture.

Each state's scrapers are organized by domain and contain:

- ``models.py`` - Pydantic data models (subclasses of :class:`~juriscraper.scraper_driver.common.models.base.ConsumerModel`)
- ``scraper.py`` - :class:`~juriscraper.scraper_driver.data_types.BaseScraper` implementations

.. contents:: State Scrapers
   :local:
   :depth: 2

Package Overview
----------------

.. automodule:: juriscraper.sd
   :members:
   :undoc-members:

Alabama
-------

.. automodule:: juriscraper.sd.state.alabama.publicportal_alappeals_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.alabama.publicportal_alappeals_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Alaska
------

.. automodule:: juriscraper.sd.state.alaska.appellate_records_courts_alaska_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.alaska.appellate_records_courts_alaska_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Arizona
-------

.. automodule:: juriscraper.sd.state.arizona.azcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.arizona.azcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Arkansas
--------

.. automodule:: juriscraper.sd.state.arkansas.opinions_arcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.arkansas.opinions_arcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

California
----------

.. automodule:: juriscraper.sd.state.california.courts_ca_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.california.courts_ca_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Colorado
--------

.. automodule:: juriscraper.sd.state.colorado.coloradojudicial_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.colorado.coloradojudicial_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Connecticut
-----------

.. automodule:: juriscraper.sd.state.connecticut.jud_ct_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.connecticut.jud_ct_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Delaware
--------

.. automodule:: juriscraper.sd.state.delaware.courts_delaware_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.delaware.courts_delaware_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

.. Florida
.. -------
..
.. (Florida scraper has import errors - commented out until fixed)
..
.. .. automodule:: juriscraper.sd.state.florida.flcourts_gov.models
..    :members:
..    :undoc-members:
..    :show-inheritance:
..
.. .. automodule:: juriscraper.sd.state.florida.flcourts_gov.scraper
..    :members:
..    :undoc-members:
..    :show-inheritance:

Georgia
-------

.. automodule:: juriscraper.sd.state.georgia.ga_appellate.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.georgia.ga_appellate.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Hawaii
------

.. automodule:: juriscraper.sd.state.hawaii.courts_state_hi_us.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.hawaii.courts_state_hi_us.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Idaho
-----

.. automodule:: juriscraper.sd.state.idaho.isc_idaho_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.idaho.isc_idaho_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Illinois
--------

.. automodule:: juriscraper.sd.state.illinois.illinoiscourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.illinois.illinoiscourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Indiana
-------

.. automodule:: juriscraper.sd.state.indiana.public_courts_in_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.indiana.public_courts_in_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Iowa
----

.. automodule:: juriscraper.sd.state.iowa.iowacourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.iowa.iowacourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Kansas
------

.. automodule:: juriscraper.sd.state.kansas.kscourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.kansas.kscourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Kentucky
--------

.. automodule:: juriscraper.sd.state.kentucky.appellatepublic_kycourts_net.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.kentucky.appellatepublic_kycourts_net.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Louisiana
---------

.. automodule:: juriscraper.sd.state.louisiana.lasc_org.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.louisiana.lasc_org.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Maine
-----

.. automodule:: juriscraper.sd.state.maine.courts_maine_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.maine.courts_maine_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Maryland
--------

.. automodule:: juriscraper.sd.state.maryland.courts_state_md_us.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.maryland.courts_state_md_us.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Massachusetts
-------------

.. automodule:: juriscraper.sd.state.massachusetts.mass_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.massachusetts.mass_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Michigan
--------

.. automodule:: juriscraper.sd.state.michigan.courts_michigan_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.michigan.courts_michigan_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Minnesota
---------

.. automodule:: juriscraper.sd.state.minnesota.mncourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.minnesota.mncourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Mississippi
-----------

.. automodule:: juriscraper.sd.state.mississippi.courts_ms_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.mississippi.courts_ms_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Missouri
--------

.. automodule:: juriscraper.sd.state.missouri.courts_mo_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.missouri.courts_mo_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Montana
-------

.. automodule:: juriscraper.sd.state.montana.courts_mt_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.montana.courts_mt_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Nebraska
--------

.. automodule:: juriscraper.sd.state.nebraska.nebraska_gov_epub.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.nebraska.nebraska_gov_epub.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Nevada
------

.. automodule:: juriscraper.sd.state.nevada.nvcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.nevada.nvcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

New Hampshire
-------------

.. automodule:: juriscraper.sd.state.new_hampshire.courts_nh_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.new_hampshire.courts_nh_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

New Jersey
----------

.. automodule:: juriscraper.sd.state.new_jersey.njcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.new_jersey.njcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

New Mexico
----------

.. automodule:: juriscraper.sd.state.new_mexico.nmonesource_com.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.new_mexico.nmonesource_com.scraper
   :members:
   :undoc-members:
   :show-inheritance:

New York
--------

.. automodule:: juriscraper.sd.state.new_york.nycourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.new_york.nycourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

North Carolina
--------------

.. automodule:: juriscraper.sd.state.north_carolina.appellate_nccourts_org.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.north_carolina.appellate_nccourts_org.scraper
   :members:
   :undoc-members:
   :show-inheritance:

North Dakota
------------

.. automodule:: juriscraper.sd.state.north_dakota.ndcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.north_dakota.ndcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Ohio
----

.. automodule:: juriscraper.sd.state.ohio.supremecourt_ohio_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.ohio.supremecourt_ohio_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Oklahoma
--------

.. automodule:: juriscraper.sd.state.oklahoma.oscn_net.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.oklahoma.oscn_net.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Oregon
------

.. automodule:: juriscraper.sd.state.oregon.cdm17027_contentdm_oclc_org.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.oregon.cdm17027_contentdm_oclc_org.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Pennsylvania
------------

.. automodule:: juriscraper.sd.state.pennsylvania.pacourts_us.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.pennsylvania.pacourts_us.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Rhode Island
------------

.. automodule:: juriscraper.sd.state.rhode_island.courts_ri_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.rhode_island.courts_ri_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

South Carolina
--------------

.. automodule:: juriscraper.sd.state.south_carolina.sccourts_org.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.south_carolina.sccourts_org.scraper
   :members:
   :undoc-members:
   :show-inheritance:

South Dakota
------------

.. automodule:: juriscraper.sd.state.south_dakota.ujs_sd_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.south_dakota.ujs_sd_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Tennessee
---------

.. automodule:: juriscraper.sd.state.tennessee.tncourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.tennessee.tncourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Texas
-----

.. automodule:: juriscraper.sd.state.texas.txcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.texas.txcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Utah
----

.. automodule:: juriscraper.sd.state.utah.utcourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.utah.utcourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Vermont
-------

.. automodule:: juriscraper.sd.state.vermont.vermontjudiciary_org.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.vermont.vermontjudiciary_org.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Virginia
--------

.. automodule:: juriscraper.sd.state.virginia.vacourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.virginia.vacourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Washington
----------

.. automodule:: juriscraper.sd.state.washington.courts_wa_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.washington.courts_wa_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

West Virginia
-------------

.. automodule:: juriscraper.sd.state.westvirginia.courtswv_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.westvirginia.courtswv_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Wisconsin
---------

.. automodule:: juriscraper.sd.state.wisconsin.wicourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.wisconsin.wicourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:

Wyoming
-------

.. automodule:: juriscraper.sd.state.wyoming.wyocourts_gov.models
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: juriscraper.sd.state.wyoming.wyocourts_gov.scraper
   :members:
   :undoc-members:
   :show-inheritance:
