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
| `citizen` | Citizenship of applicant | retained at aggregation, see below |
| `sex` | Sex of applicant | aggregated out (we sum over it) |
| `applicant` | Type of applicant | filtered to `FRST` (first-time applicants) |
| `age` | Age band | aggregated out (we sum over it) |
| `geo` | Reporting Member State | filtered to EU-27 |

The numeric value associated with each tuple is the count of asylum
applications recorded for that month, country, citizenship and
applicant type.

### What we keep

The harvester filters to `applicant = FRST` and the EU-27 geographic
codes, then aggregates within each chunk by destination country
(`geo`), summing across all citizenships, ages and sexes. The
aggregated row is stored with `citizen_code = 'TOTAL'` and
`applicant_type = 'FRST'` in the `asylum_data` table.

This means the database currently exposes **first-time applications
per Member State per month**, regardless of nationality. The schema
preserves the `citizen_code` column so a future iteration can land
the per-nationality breakdown without a migration.

### What we don't keep (yet)

- **Subsequent applicants** (`applicant = SBSQ`).
- **Citizenship breakdown** — the harvester collapses it to `TOTAL` to
  keep volumes manageable at the current aggregation level.
- **Age and sex breakdowns** — same reason.
- **Geographic granularity below NUTS-0** — the source dataset is at
  Member-State level and the project follows suit; sub-national
  patterns are not represented.

## Data quality notes

- **Missing values.** Eurostat publishes special markers (e.g. `:`,
  `p`, `e`) for missing, provisional, or estimated values. The
  harvester strips non-numeric characters and coerces the result to
  an integer; missing values therefore arrive as zero. The predictor
  drops the most recent month for a country if its value is zero
  while the prior month was substantial (`prev > 100`), as this
  pattern almost always indicates a country that has not yet
  reported for the current reference month.
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
