# `tests/fixtures/vfarms_profile.json` — field provenance

**Fixture-only.** These values are for **tests and live_llm eval**. They must **not** be published to production employee snapshots unless re-derived from the business website or operator-provided sources.

| Field | Value (summary) | Source |
|-------|-----------------|--------|
| `business.name` | V Farms Resort | **Regression corpus** — `tests/conversations/vfarms_regression.json`, production transcripts |
| `business.type` | resort | **Invented** (fixture typing) |
| `business.one_line_pitch` | Weekend resort near Medchal… | **Invented** (marketing line for tests) |
| `location.full_address` | Medchal, Telangana 501401 | **Partially corroborated** from regression facts + call handling; **PIN 501401 invented** |
| `location.area` | Medchal | **Regression** — vfarms_regression.json facts |
| `location.city` | Hyderabad | **Regression** — distance framing from facts |
| `location.state` | Telangana | **Regression** |
| `location.landmarks` | ORR Medchal exit | **Regression** — vfarms_regression.json |
| `location.distance_from` | 28 km, 45 min from Hyderabad | **Regression** — vfarms_regression.json |
| `location.maps_link` | (empty) | **Invented** placeholder |
| `contact.reception_phone` | 04045900002 | **Regression / test transcripts** — verify on live site before publish |
| `contact.whatsapp`, `email`, `hours` | empty | **Missing** — intentional gap for warning UI |
| `offerings[0]` Standard room | AC room, Rs 3500/night | **Regression** — vfarms_regression.json facts |
| `offerings[0].price_notes` | Weekday indicative… | **Invented** policy wording |
| `amenities` | Pool, indoor games | **Invented** (typical resort; not verified on URL) |
| `policies.check_in/out` | 2 PM / 11 AM | **Invented** (common resort default) |
| `offers`, `faqs`, `objection_handling` | empty | **Invented** empty structures |
| `unknown_policy` | callback | **Product default** |
| `sources` | seed / vfarms_fixture | **Fixture metadata** |

No PDF or crawl URL is tied to this file. For production, run **Website analyze** on the real V Farms URL and **publish** after operator review.