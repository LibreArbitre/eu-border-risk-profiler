# Data Card — `migr_asyappctzm`

This document describes the source dataset that the EU Border Risk
Profiler ingests, transforms, and predicts on. It complements the
[Model Card](MODEL_CARD.md) and follows the spirit of the Datasheets
for Datasets framework (Gebru et al., 2021).

## Source

- **Publisher:** Eurostat — the statistical office of the European
  Union.
- **Dataset code:** `migr_asyappctzm`
- **Title:** _Asylum applicants by type, citizenship, age and sex —
  monthly data_
- **Bulk download endpoint:**
  `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/migr_asyappctzm/?format=TSV&compressed=false`
- **License:** Eurostat data is freely re-usable under the terms of
  the Eurostat copyright notice — attribution to Eurostat is
  requested, redistribution is permitted, derivative works are
  permitted. See <https://ec.europa.eu/eurostat/about-us/policies/copyright>.
- **Cadence:** monthly, with revisions to prior months.
- **Reporting lag:** typically one to two months between the reference
  period and publication. Some Member States publish later than others
  in any given month.
- **Coverage in this project:** all 27 EU Member States plus
  EFTA/candidate countries reported by Eurostat. The pipeline filters
  to the EU-27 (`AT, BE, BG, CY, CZ, DE, DK, EE, EL, ES, FI, FR, HR,
  HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK`) before
  storage.

## What the dataset contains

Each row in the source TSV is keyed by a seven-dimension tuple:

| Dimension | Meaning | Values used here |
|-----------|---------|------------------|
| `freq` | Frequency | `M` (monthly) |
| `unit` | Unit | `PER` (persons) |
| `citizen` | Citizenship of applicant | ISO alpha-2 codes, plus Eurostat's own `TOTAL` |
| `sex` | Sex of applicant | filtered to `T` (total) |
| `applicant` | Type of applicant | filtered to `FRST` (first-time applicants) |
| `age` | Age band | filtered to `TOTAL` |
| `geo` | Reporting Member State | filtered to EU-27 |

The numeric value associated with each tuple is the count of asylum
applications recorded for that month, country, citizenship and
applicant type.

### What we keep

The harvester filters to `applicant = FRST`, the EU-27 geographic
codes, and the `sex = T` / `age = TOTAL` row of every combination.

That last filter matters. The bulk file lists the pre-aggregated rows
next to the detailed ones (`T` beside `M` and `F`, `TOTAL` beside every
age band, `Y_LT18` beside its two sub-bands). Summing all rows of a
country would count each applicant four to five times; only the
all-sexes, all-ages row is the published figure.

Two kinds of rows are stored in `asylum_data`, both with
`applicant_type = 'FRST'`:

- one per citizenship (`citizen_code` = ISO alpha-2 code), which feeds
  the per-nationality view of the dashboard;
- Eurostat's own `citizen_code = 'TOTAL'` row, the official
  country-level figure. It includes stateless and unknown
  citizenships, so it is slightly higher than the sum of the alpha-2
  rows, and it is what the score and the model use.

### Population

The score relates applications to population. The figures are the
resident population on 1 January 2026 from Eurostat table `tps00001`
(_Population on 1 January_), extracted on 16 November 2026 and kept as
a constant in `risk_predictor.POPULATION`. One reference year is
applied to the whole history; the table should be refreshed when a new
year is published.

### What we don't keep (yet)

- **Subsequent applicants** (`applicant = SBSQ`).
- **Age and sex breakdowns**: only the all-ages, all-sexes total is
  stored.
- **Citizenship aggregates other than `TOTAL`** (`EU27_2020`,
  `EXT_EU27_2020`, stateless, unknown...) as separate rows; they are
  only present through the `TOTAL`.
- **Geographic granularity below NUTS-0** — the source dataset is at
  Member-State level and the project follows suit; sub-national
  patterns are not represented.

## Data quality notes

- **Missing values.** Eurostat publishes special markers (e.g. `:`,
  `p`, `e`) for missing, provisional, or estimated values. The
  harvester strips the flags and keeps the number; a cell with no
  number (`:`) produces **no row at all**. A month a Member State has
  not reported yet is therefore absent from the database rather than
  stored as zero, and the latest available month differs between
  countries. As an extra guard, the predictor drops the most recent
  month for a country if its value is exactly zero while the prior
  month was substantial (`prev > 100`).
- **Revisions.** Eurostat revises previously published values when
  Member States submit corrections. Because the harvester replaces
  the production table atomically on every successful run, revisions
  are always reflected — with the side effect that historical risk
  scores derived from the calculated volume can change between
  successive harvests.
- **Definitional changes.** The methodology Eurostat uses to define
  "first-time applicant" is documented in the dataset's metadata
  and aligns with EU Regulation No 862/2007 on Community statistics
  on migration and international protection.

## What the dataset is _not_

- **Not a count of border crossings.** A first-time application is
  recorded when the procedure is filed with the destination Member
  State's authorities. People may cross a border weeks or months
  before applying, may transit through several Member States before
  applying, or may never apply at all.
- **Not a measure of migration to the EU.** Asylum is one channel
  among several (work permits, family reunification, study,
  irregular migration). The dataset captures the asylum channel
  only.
- **Not personal data.** Every published row is an aggregated count
  of at least the (citizenship, sex, age, applicant type) cell.
  Eurostat applies its own confidentiality rules before publication.
- **Not real-time.** The most recent month is published with a 1-2
  month lag and is subject to revision for several subsequent
  publications.

## Privacy and legal basis

The dataset contains no personal data within the meaning of GDPR. No
GDPR-legal-basis assessment is required for processing it. Re-use is
permitted under Eurostat's standard re-use policy; this project
identifies itself to the Eurostat HTTP service via a custom
`User-Agent` header in conformity with the API terms of use.

## Citation

When citing data derived from this project, please follow Eurostat's
recommended citation:

> Eurostat (year). _Asylum applicants by type, citizenship, age and
> sex — monthly data_ (online data code: `migr_asyappctzm`).
> European Commission. Accessed via the EU Border Risk Profiler at
> [date].
