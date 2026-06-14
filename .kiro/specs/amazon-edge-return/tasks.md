# Implementation Plan: Amazon Edge-Return

## Overview

This plan converts the Amazon Edge-Return design into incremental, code-only steps. The stack is fixed by the design: a **FastAPI** (async ASGI) backend with **PostgreSQL** (SQLAlchemy async + asyncpg) and a **Redis** geospatial demand index, plus a **Next.js** (App Router, React, TailwindCSS) frontend. Property-based tests use **Hypothesis** (Python) for the backend pure cores and **fast-check** (TypeScript) for frontend pure utilities, each at 100+ iterations, one property per test, tagged `Feature: amazon-edge-return, Property {n}: ...`.

The build follows the design's phased order: Phase 1 (DB schema, infra wiring, seed), Phase 2 (pure decision cores + service/API engine + continuous scanner + matching + pricing), Phase 3 (Amazon-fidelity frontend shell + auth/session context), Phase 4 (seller orders + return scan workflow), Phase 4.5 (P2P resale marketplace + Split-Trust feed), Phase 5 (buyer product/cart + delayed match notification popup), Phase 6 (admin operations dashboard).

### Prototype scope: real vs mocked logic

Per the user directive, the demonstrable core paths are implemented for real: auth/session, demand-signal recording into Redis, return initiation + 48h scanner pool, the continuous match creation that powers the Flow 18 delayed-match demo, resale list/feed with Split-Trust images, the return lifecycle state machine + auto-routing, and the admin dashboard read endpoints. The harder estimation/analytics math and AI scans are explicitly **mocked/hardcoded** behind the same function/interface signatures so frontends stay visually end-to-end demonstrable. Each affected task calls out its mock-vs-real choice.

- **Mocked/hardcoded backend stand-ins:** estimated reverse-logistics cost & logistics savings inputs, delivery-time-saved and carbon-avoided estimates, admin metric aggregation values (Reverse Logistics Saved, Carbon Offset Index, NGO CSR Credits, cache total), the AI item-verification scan and AI grading result. These return plausible deterministic values via small seams so they can later be swapped for real implementations.
- **Real implementations:** the pure decision cores (state machine, matching selection, scoring, discount clamp/rounding, validation, countdown formatting), Redis GEOADD/GEOSEARCH demand index, the 48h scanner pool + expiry sweep, MatchCandidate creation + lifecycle cascade, resale persistence + feed joins, and all admin read/dispatch endpoint wiring.

---

## Tasks

### Phase 1 — Database, Infrastructure, and Seed

- [x] 1. Scaffold backend project, configuration, and store gateways
  - [x] 1.1 Create FastAPI project skeleton and dependency manifest
    - Create the backend package layout (`app/`, `app/api/`, `app/services/`, `app/core/`, `app/models/`, `app/db/`, `tests/`) and the FastAPI application entrypoint with health route.
    - Pin dependencies: `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `redis`, `pydantic`, `passlib`/`bcrypt`, `itsdangerous` (signed cookies), `hypothesis`, `pytest`, `pytest-asyncio`.
    - Add settings module reading DB URL, Redis URL, and session secret from environment.
    - _Requirements: 1.4_

  - [x] 1.2 Implement async PostgreSQL session/engine and Redis gateway
    - Wire SQLAlchemy async engine + session factory and a FastAPI dependency that yields a request-scoped session.
    - Implement a thin Redis gateway exposing `geo_add`, `geo_search`, `hset_ts`, `hget_ts`, and `flush_demand_keys`, wrapping native `GEOADD`/`GEOSEARCH` commands and surfacing failures as a typed error for Requirement 4.7.
    - _Requirements: 4.5, 4.7_

- [x] 2. Define the relational schema (SQLAlchemy models)
  - [x] 2.1 Implement core entity models with constraints
    - Create `User`, `Product`, `OrderHistory`, `ReturnOrder`, `MatchCandidate`, `ResaleListing`, `CartItem`, `Notification`, `MetricSnapshot`, and `Hub` models per the design ERD.
    - Enforce DB constraints: `Product` unique non-null `asin`, `price > 0`, `rating BETWEEN 0 AND 5`, `review_count >= 0`, non-null `image_url`, `estimated_reverse_logistics_cost >= 0`; `User.email` unique with `password_hash`; status enums for `ReturnOrder`, `MatchCandidate`, `ResaleListing`.
    - Add the partial unique index on `MatchCandidate(return_order_id, buyer_id) WHERE status='PENDING'` to enforce the duplicate guard.
    - _Requirements: 2.3, 2.4, 2.5, 6.9_

  - [ ]* 2.2 Write property test for product catalog invariants
    - **Feature: amazon-edge-return, Property 27: Product catalog invariants** — every product has a non-empty unique ASIN, non-empty name, price > 0, rating in [0.0, 5.0], review_count integer >= 0, and non-empty image_url.
    - Use a Hypothesis catalog strategy; 100+ iterations; one property per test.
    - **Validates: Requirements 2.5**

- [x] 3. Implement the seed script
  - [x] 3.1 Implement ordered drop → recreate → populate seeding with atomicity
    - Implement `seed.py` that drops all tables (idempotent), recreates schema from metadata, and populates data, aborting on any phase failure with a non-zero exit and the failed-phase name, committing no partial relational data.
    - Populate Priya Sharma (Seller, lat 12.9781, lon 77.6389), Rahul Verma (Buyer, lat 12.9352, lon 77.6271, empty cart), 5–50 valid products including "Sony WH-CH520 Wireless Headphones" and "Levi's T-Shirt", and >=2 past-dated OrderHistory rows for Priya referencing those two products.
    - Flush Redis demand keys so the Geospatial_Index starts with zero entries referencing only seeded ASINs; seed `Hub` rows and an initial `MetricSnapshot`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 3.2 Write integration smoke tests for the seed script
    - Run the seed against an empty DB and a pre-populated DB; assert success both times and zero demand entries after run.
    - Inject a per-phase failure and assert non-zero exit, failed-phase message, and no partial data committed.
    - _Requirements: 2.1, 2.2, 2.7_

- [x] 4. Checkpoint — schema and seed verified
  - Ensure all tests pass, ask the user if questions arise.

### Phase 2 — Pure Decision Cores, Matching Engine, Scanner, Pricing

- [x] 5. Implement the return lifecycle pure state machine
  - [x] 5.1 Implement the transition table and `transition()` core
    - Encode the exact transition relation (SCANNING→{MATCH_FOUND,EXPIRED,NGO_ROUTING,MICROWAREHOUSE}, MATCH_FOUND→BUYER_ACCEPTED, BUYER_ACCEPTED→LOCAL_DELIVERY, EXPIRED→{FC_TRANSIT,NGO_ROUTING,MICROWAREHOUSE}) with terminal states immutable.
    - Implement a pure `transition(source, target)` returning the new status or an `InvalidTransitionError` naming source and target, leaving status unchanged on rejection.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [x] 5.2 Implement expiry auto-routing decision (real) with mocked cost input
    - Implement the pure decision: on SCANNING→EXPIRED compute `Reverse_Transit_Threshold = estimated_reverse_logistics_cost + 150`, route to NGO_ROUTING when `price <= threshold` else MICROWAREHOUSE.
    - The routing comparison is **real**; `estimated_reverse_logistics_cost` is sourced from the seeded Product column (a **mocked/hardcoded** plausible value), keeping the seam swappable.
    - _Requirements: 10.9, 10.10, 10.11, 10.12_

  - [x]* 5.3 Write property test for state-machine legality
    - **Feature: amazon-edge-return, Property 19: State-machine legality matches the transition table** — a transition is permitted iff the (source,target) pair is in the table; permitted sets exactly the target, unpermitted (including terminal-source) is rejected unchanged with an invalid-transition error naming source and target.
    - Hypothesis strategy over the full status cross-product; 100+ iterations; one property per test.
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8**

  - [x]* 5.4 Write property test for expiry auto-routing
    - **Feature: amazon-edge-return, Property 20: Expiry auto-routing is total and threshold-driven** — threshold equals cost + ₹150 and the order routes to exactly one of NGO_ROUTING (price <= threshold) or MICROWAREHOUSE (price > threshold), including prices straddling the threshold.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 10.9, 10.10, 10.11, 10.12**

- [x] 6. Implement demand scoring and matching selection pure cores
  - [x] 6.1 Implement demand-score ranking function
    - Implement `score(signal)` (cart=100, buynow=90, wishlist=70, viewed=40) and `rank_signals(signals)` ordering by score descending then earliest timestamp.
    - _Requirements: 5.1, 5.2, 5.3_

  - [x]* 6.2 Write property test for demand ranking
    - **Feature: amazon-edge-return, Property 7: Demand signal ranking by score then timestamp** — ranking orders by score descending then earliest timestamp; first ranked has max score and earliest timestamp among max-score signals.
    - Hypothesis strategy over mixed intents/timestamps; 100+ iterations; one property per test.
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [x] 6.3 Implement haversine distance and nearest-candidate selection
    - Implement `haversine_km(a, b)` rounded to 2 decimals and a pure `select_match(candidates, buyer)` that filters to SCANNING, non-expired, matching ASIN, seller != buyer, within 20 km, selecting smallest distance with earliest `expires_at` as tie-break; returns none when nothing qualifies.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.8_

  - [x] 6.4 Write property test for distance computation
    - **Feature: amazon-edge-return, Property 8: Distance is the haversine distance rounded to two decimals** — computed distance_km equals haversine rounded to 2 dp.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 6.3**

  - [x] 6.5 Write property test for match selection
    - **Feature: amazon-edge-return, Property 9: Match selection picks the nearest eligible candidate** — only eligible candidates considered; nearest within 20 km selected, earliest expires_at tie-break, none when all beyond 20 km (include exactly 20.00 km boundary).
    - 100+ iterations; one property per test.
    - **Validates: Requirements 6.1, 6.2, 6.4, 6.8**

- [x] 7. Implement pricing / impact pure core (real clamp, mocked estimates)
  - [x] 7.1 Implement `local_discount` and `savings_summary`
    - Implement `local_discount(price, est_savings) = clamp_nonneg(min(est_savings, 0.15*price))` rounded to 2 dp with values < 0.01 → 0.00 — this clamp/rounding is **real**.
    - Implement `savings_summary` returning money_saved (= local_discount), delivery_time_saved_hours (whole hours >= 0), carbon_avoided_kg (1 dp >= 0) with an `include_carbon` flag false when < 0.1 kg. The `est_savings`, delivery-hours, and carbon inputs are **mocked/hardcoded** plausible deterministic values behind this seam.
    - _Requirements: 7.1, 7.2, 7.3_

  - [x]* 7.2 Write property test for local discount bound and rounding
    - **Feature: amazon-edge-return, Property 13: Local discount bound and rounding** — discount equals MIN(savings, 0.15×price) clamped non-negative, 2 dp, < 0.01 reported as 0.00, never exceeding savings or 15% of price (include discounts straddling 0.01).
    - 100+ iterations; one property per test.
    - **Validates: Requirements 7.1**

  - [x]* 7.3 Write property test for savings summary bounds and carbon suppression
    - **Feature: amazon-edge-return, Property 14: Savings summary field bounds and carbon suppression** — money saved = discount (2 dp), delivery hours whole >= 0, carbon >= 0 at 1 dp, carbon field omitted when < 0.1 kg (include exactly 0.1 kg boundary).
    - 100+ iterations; one property per test.
    - **Validates: Requirements 7.2, 7.3**

- [x] 8. Implement return service, scanner pool, and expiry sweep
  - [x] 8.1 Implement return initiation and scanner-pool membership
    - Implement `POST /api/returns/initiate` creating a ReturnOrder (status SCANNING, initiated_at=now, expires_at=now+172800s) bound to the seller id and product ASIN; reject with 403/422 when no session or product not in the user's OrderHistory.
    - Implement scanner-pool membership query (status SCANNING AND expires_at > now) used by matching and admin.
    - _Requirements: 3.1, 3.2, 3.3, 3.7_

  - [x]* 8.2 Write property test for return creation window
    - **Feature: amazon-edge-return, Property 1: Return creation sets SCANNING and a 48-hour window** — created order has SCANNING, seller id, product ASIN, and expires_at − initiated_at = 172800s exactly.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 8.3 Write property test for scanner-pool membership
    - **Feature: amazon-edge-return, Property 2: Scanner-pool membership invariant** — discoverable iff status SCANNING and expires_at strictly later than now; non-SCANNING never discoverable.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 3.3, 3.5**

  - [x] 8.4 Implement expiry sweep scheduler and lifecycle transition endpoint
    - Implement an asyncio background sweep (sub-second cadence) that finds SCANNING orders with expires_at <= now and no ACCEPTED candidate, transitions them to EXPIRED within 1s, then auto-routes (NGO_ROUTING/MICROWAREHOUSE) and expires sibling PENDING candidates.
    - Implement `POST /api/returns/{id}/transition` delegating to the state-machine core and returning the resulting status or `409 INVALID_TRANSITION`.
    - _Requirements: 3.4, 3.5, 9.4, 10.5, 10.7_

  - [ ]* 8.5 Write property test for expiry detection transition
    - **Feature: amazon-edge-return, Property 3: Expiry detection transitions unmatched scanning returns** — a SCANNING order with expires_at <= now and no ACCEPTED candidate is transitioned to EXPIRED by the sweep.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 3.4**

- [x] 9. Implement demand signal service and Redis index
  - [x] 9.1 Implement coordinate validation and demand recording
    - Implement `record_signal(intent, asin, buyer)` validating lon ∈ [-180,180], lat ∈ [-90,90] (reject absent/out-of-bounds with `400 INVALID_LOCATION`, no Redis write), then `GEOADD demand:{intent}:{asin}` (member = buyer id, overwrite) and `HSET demand_ts:{intent}:{asin}` for tie-break timestamps; return failure (`502 SIGNAL_NOT_RECORDED`) if GEOADD fails, never reporting success.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x]* 9.2 Write property test for demand key mapping
    - **Feature: amazon-edge-return, Property 4: Demand signals map to the correct key with buyer coordinates** — recording writes exactly key `demand:{type}:{asin}` with buyer id member at buyer (lon, lat).
    - 100+ iterations; one property per test.
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

  - [x]* 9.3 Write property test for per-buyer idempotence
    - **Feature: amazon-edge-return, Property 5: Demand recording is per-buyer idempotent (overwrite)** — after repeated signals from the same buyer to the same key, at most one entry exists with the most recent coordinates.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 4.5**

  - [x]* 9.4 Write property test for invalid-coordinate rejection
    - **Feature: amazon-edge-return, Property 6: Invalid buyer coordinates are rejected with no write** — out-of-bounds/absent coordinates rejected, no Geospatial_Index write, invalid-location error returned.
    - Hypothesis strategy producing in- and out-of-bounds coordinates; 100+ iterations; one property per test.
    - **Validates: Requirements 4.6**

- [x] 10. Implement matching engine I/O shell and match-creation flow
  - [x] 10.1 Wire matching engine into demand recording
    - On each successful signal, query candidate ReturnOrders, apply the `select_match` core, apply the duplicate guard (skip if PENDING (buyer, return) exists), then create one MatchCandidate (PENDING, distance_km, signal_source, cached deal impact from pricing core), increment the active-match count, and enqueue a notification — all in one transaction. Create nothing when no candidate qualifies.
    - _Requirements: 6.1, 6.5, 6.6, 6.7, 6.9, 6.10, 9.1_

  - [x] 10.2 Write property test for match creation and active-match count
    - **Feature: amazon-edge-return, Property 10: Match creation produces a PENDING candidate and bumps the active-match count** — creates exactly one PENDING candidate with distance_km and signal_source, increments active-match count by one.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 6.5, 6.7, 9.1**

  - [x] 10.3 Write property test for duplicate-candidate guard
    - **Feature: amazon-edge-return, Property 11: No duplicate PENDING candidates** — re-processing a signal for a (buyer, return) pair with an existing PENDING candidate creates no second candidate.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 6.9**

  - [x] 10.4 Write property test for no-eligible-candidate no-op
    - **Feature: amazon-edge-return, Property 12: No eligible candidate leaves match state unchanged** — no qualifying ReturnOrder ⇒ no MatchCandidate created and existing candidates unchanged.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 6.10**

- [x] 11. Implement match candidate lifecycle (accept/reject + cascade)
  - [x] 11.1 Implement accept/reject endpoints and cascade
    - Implement `POST /api/matches/{id}/accept` and `/reject`: ownership check (`403 NOT_AUTHORIZED`), PENDING-only check (`409 OFFER_UNAVAILABLE`); accept sets ACCEPTED, advances the return SCANNING→MATCH_FOUND→BUYER_ACCEPTED→LOCAL_DELIVERY, and expires all sibling PENDING candidates; reject sets REJECTED. Leaving SCANNING for any reason expires outstanding PENDING candidates.
    - _Requirements: 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [x] 11.2 Write property test for accept/reject transitions
    - **Feature: amazon-edge-return, Property 16: Candidate accept/reject transitions** — owning buyer accept ⇒ ACCEPTED, reject ⇒ REJECTED.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 9.2, 9.3**

  - [x] 11.3 Write property test for accept advancing the return path
    - **Feature: amazon-edge-return, Property 17: Accept advances the return along the local-delivery path** — an ACCEPTED candidate advances its return SCANNING→MATCH_FOUND→BUYER_ACCEPTED→LOCAL_DELIVERY.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 9.5**

  - [x] 11.4 Write property test for leaving-SCANNING cascade
    - **Feature: amazon-edge-return, Property 18: Leaving SCANNING expires outstanding PENDING candidates** — when a return leaves SCANNING, every other PENDING candidate becomes EXPIRED.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 9.4, 9.8**

- [x] 12. Checkpoint — backend engine verified
  - Ensure all tests pass, ask the user if questions arise.

### Phase 3 — Amazon-Fidelity Frontend Shell + Auth/Session Context

- [x] 13. Scaffold Next.js app, Tailwind theme, and design tokens
  - [x] 13.1 Create Next.js App Router project and Tailwind token theme
    - Scaffold the Next.js (App Router) app with TailwindCSS, Lucide React icons, and fast-check + a test runner (vitest/jest) configured.
    - Extend the Tailwind theme with `amazonNavy #232F3E`, `amazonDark #131921`, `amazonOrange #FF9900`, `amazonLink #007185`, `amazonBg #EAEDED`, `adminSlate #020617`; implement a `PrimaryButton` with 8px radius and `#FFD814→#F7CA00` top-to-bottom gradient.
    - Build the `NavBar` and shared layout applying customer-facing tokens.
    - _Requirements: 17.1, 17.2_

  - [x]* 13.2 Write snapshot/style and contrast tests for design tokens
    - Snapshot the NavBar and PrimaryButton; assert gradient/radius tokens and a ≥ 4.5:1 body-text contrast check on customer pages.
    - _Requirements: 17.1, 17.2, 17.4_

- [x] 14. Implement auth/session context and login flow
  - [x] 14.1 Implement backend auth endpoints and session cookie
    - Implement `POST /api/auth/login` (verify email + password hash against seeded accounts, set signed HTTP-only session cookie, `401 AUTH_FAILED` on mismatch), `POST /api/auth/logout` (server-side invalidation), and `GET /api/auth/session` (resolve active user + `can_sell` flag from OrderHistory). Provide the FastAPI session-resolution dependency used by protected routes.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 14.2 Implement frontend login page and AuthSessionContext
    - Build `/login` listing seeded accounts with an auth form; on success store session context; on failure show an authentication-failed message.
    - Implement a global `AuthSessionContext` that, on user switch/logout, replaces all user-scoped content (cart, order history, match notifications) to reflect only the new session within 3 seconds.
    - _Requirements: 1.1, 1.3, 1.5, 1.6, 1.7_

  - [x] 14.3 Write unit tests for login and session replacement
    - Test successful/failed login, logout, and that switching users clears prior cart/orders/notifications.
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7_

- [x] 15. Checkpoint — frontend shell and auth verified
  - Ensure all tests pass, ask the user if questions arise.

### Phase 4 — Seller Orders + Return Scan Workflow

- [x] 16. Implement seller orders page and return scan workflow
  - [x] 16.1 Build orders page with return + resell gating
    - Build `/orders` rendering the seller's OrderHistory with a `ReturnButton`, and a `ResellButton` shown only when `purchased_at` is more than 7 days before now.
    - _Requirements: 1.5, 11.1_

  - [x] 16.2 Implement AI verification scan modal and return submission
    - Implement `AIVerificationScanModal` displaying the "Amazon AI Item Verification Scan" for 2s (±200ms) — a **mocked** AI scan — then submit `POST /api/returns/initiate` only after dismissal.
    - _Requirements: 3.6_

  - [x]* 16.3 Write unit test for AI scan modal timing and submit order
    - Use fake timers to assert the modal shows ~2s and the initiate request fires only after dismissal.
    - _Requirements: 3.6_

  - [x]* 16.4 Write property test for resale eligibility by age
    - **Feature: amazon-edge-return, Property 22: Resale eligibility by purchase age** — the "Resell via Amazon" action is available iff `purchased_at` is more than 7 days before now.
    - fast-check arbitrary over purchase timestamps; 100+ iterations; one property per test.
    - **Validates: Requirements 11.1**

### Phase 4.5 — P2P Resale Marketplace + Split-Trust Feed

- [x] 17. Implement resale listing creation
  - [x] 17.1 Implement `POST /api/resale/list` with validation
    - Validate `condition_grade ∈ {"Like New","Good","Fair"}` (`422 UNSUPPORTED_GRADE`), require non-empty `condition_image_url` (`422 CONDITION_IMAGE_REQUIRED`), enforce `0 < resale_price <= product.price`; create ACTIVE ResaleListing with `listed_at=now`. The grading result and condition image come from a **mocked** AI grading capture.
    - _Requirements: 11.2, 11.3, 11.4, 11.6, 11.7_

  - [x] 17.2 Write property test for resale listing validation
    - **Feature: amazon-edge-return, Property 21: Resale listing validation** — a listing is created iff grade ∈ set, image URL non-empty, and 0 < price <= product price; on success status ACTIVE with provided fields and listed_at=now; otherwise no listing and the correct error.
    - Hypothesis strategy with grades inside/outside the set; 100+ iterations; one property per test.
    - **Validates: Requirements 11.2, 11.3, 11.4, 11.6, 11.7**

  - [x] 17.3 Build resale listing flow with mock grading scan modal
    - Build the `MockAIGradingScanModal` (2s) that produces a mock condition grade + image URL, then submits the resale listing.
    - _Requirements: 11.5_

  - [x]* 17.4 Write unit test for grading scan modal timing
    - Fake-timer test asserting the 2s mock scan precedes listing creation.
    - _Requirements: 11.5_

- [x] 18. Implement resale feed and Split-Trust gallery
  - [x] 18.1 Implement `GET /api/resale/feed` with joins and ordering
    - Return ACTIVE listings joined with Product and original OrderHistory purchase date, newest `listed_at` first, including both non-empty `image_url` and `condition_image_url`; empty collection when none; `503 STORE_UNAVAILABLE` with no partial set on store failure.
    - _Requirements: 12.1, 12.2, 12.3, 12.7_

  - [x]* 18.2 Write property test for resale feed shaping
    - **Feature: amazon-edge-return, Property 23: Resale feed is active-only, ordered, and fully joined** — returns exactly ACTIVE listings, newest-first, each with joined Product, original purchase date, and both non-empty image URLs.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 12.1, 12.7**

  - [x] 18.3 Build `/local-deals` grid with Split-Trust gallery
    - Build the "Amazon Local Verified Used Deals" grid (with empty state), each card showing the "✅ Amazon Verified Original Purchase" badge + Condition Grade and a `SplitTrustGallery` rendering the official Product image as primary and the condition image as a secondary thumbnail badged "Live Condition".
    - _Requirements: 12.4, 12.5, 12.6, 12.8_

  - [x]* 18.4 Write snapshot tests for deals grid and Split-Trust gallery
    - Snapshot populated and empty grids; assert verified badge, condition grade, primary/secondary images, and "Live Condition" label.
    - _Requirements: 12.4, 12.5, 12.6, 12.8_

- [x] 19. Checkpoint — seller + resale flows verified
  - Ensure all tests pass, ask the user if questions arise.

### Phase 5 — Buyer Product/Cart + Delayed Match Notification Popup

- [x] 20. Implement buyer catalog, product detail, and cart with demand signals
  - [x] 20.1 Build home/catalog, product detail, and cart pages
    - Build `/` catalog grid (`ProductGrid`/`ProductCard`), `/product/[asin]` detail with `BuyBox` actions, and `/cart`. Fire `POST /api/view` on detail load and `POST /api/cart` / `POST /api/buynow` / `POST /api/wishlist` on the corresponding actions, all carrying the buyer's session.
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 20.2 Implement demand-signal endpoints wiring
    - Implement `POST /api/cart`, `/api/buynow`, `/api/wishlist`, `/api/view`, and `GET /api/cart`, each invoking `record_signal` (which triggers matching) and returning the documented status codes/errors.
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 21. Implement notification poller, popup, and notifications endpoint
  - [x] 21.1 Implement `GET /api/notifications` with deal enrichment
    - Return PENDING MatchCandidates for the active buyer enriched with headline, money_saved, time_saved_hours, and carbon_avoided_kg (omitted when < 0.1 kg), preserving PENDING until delivered or the return leaves SCANNING.
    - _Requirements: 7.4, 8.1, 8.6_

  - [x] 21.2 Build NotificationPoller (3s) and MatchNotificationPopup
    - Implement the global 3s short-poll; render `MatchNotificationPopup` with deal headline, money saved, delivery time saved, carbon avoided, and enabled "Claim Deal" / "Keep Original Delivery" actions; hide within 1s on either action; show nothing while no PENDING candidate exists. Wire the cart-add in-app nearby-return notification within 3s (Req 1.8).
    - _Requirements: 1.8, 7.4, 8.2, 8.3, 8.4, 8.5_

  - [x]* 21.3 Write property test for PENDING persistence under polling
    - **Feature: amazon-edge-return, Property 15: PENDING candidates persist while their return is SCANNING** — repeated polling of a PENDING candidate whose return stays SCANNING leaves it PENDING.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 8.6**

  - [x]* 21.4 Write unit tests for popup rendering and dismissal, plus Flow 18 demo
    - Test popup fields/actions and 1s dismissal; test the Req 18 scenario: return for Sony with no demand ⇒ 0 candidates; buyer in-radius cart-add ⇒ exactly one PENDING candidate (source cart) + "🔥 Local Open-Box Deal Found Near You" within 3s; buyer outside radius ⇒ no candidate, no notification.
    - _Requirements: 7.4, 8.2, 8.3, 8.4, 8.5, 18.1, 18.2, 18.3, 18.4_

- [x] 22. Checkpoint — buyer flow and delayed match demo verified
  - Ensure all tests pass, ask the user if questions arise.

### Phase 6 — Admin Operations Dashboard

- [x] 23. Implement admin metrics endpoint and KPIGrid
  - [x] 23.1 Implement `GET /api/admin/metrics` (real reads, mocked aggregates)
    - Return Cache Storage Capacity `{used, total}` (used = MICROWAREHOUSE/CACHED count — **real** read; total — **mocked/hardcoded** capacity), Reverse Logistics Saved, Carbon Offset Index, and NGO CSR Credits as **mocked/hardcoded** plausible non-negative aggregates behind a swappable seam; all-or-nothing on retrieval failure (`503 METRICS_UNAVAILABLE`).
    - _Requirements: 13.1, 13.3_

  - [x]* 23.2 Write property test for admin metric bounds
    - **Feature: amazon-edge-return, Property 24: Admin metric bounds** — 0 <= used <= total, total >= 1, and non-negative Reverse Logistics Saved, Carbon Offset Index, and NGO CSR Credits.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 13.1**

  - [x] 23.3 Build admin dark-mode shell and KPIGrid
    - Build `/admin/operations` with full-viewport slate-950 background and a four-column `KPIGrid`: Cache Storage Capacity progress bar (used/total/percentage), Reverse Logistics Saved (currency 2 dp), Carbon Offset Index (kg 1 dp), NGO CSR Credits (currency 2 dp), rendering zero values as "0"/"0.00"/"0.0".
    - _Requirements: 13.2, 13.4, 17.3_

  - [x]* 23.4 Write unit/snapshot tests for KPIGrid and admin dark mode
    - Assert four-column formatting, zero-value rendering, and slate-950 background.
    - _Requirements: 13.2, 13.4, 17.3_

- [x] 24. Implement admin returns table, live countdown, and dispatch
  - [x] 24.1 Implement `GET /api/admin/returns` with status filter + aliases
    - Return ReturnOrders joined with Product and User filtered by a recognized status or ALL (mapping aliases CACHED≡MICROWAREHOUSE, RTO_QUEUED≡EXPIRED, NGO_QUEUED≡NGO_ROUTING); empty array when none; `400 INVALID_STATUS` for unrecognized values.
    - _Requirements: 14.1, 14.2, 14.3_

  - [x]* 24.2 Write property test for admin returns filter
    - **Feature: amazon-edge-return, Property 25: Admin returns filter** — returns every order matching the requested status (all when ALL), each joined with Product and User, empty array when none.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 14.1, 14.2**

  - [x] 24.3 Build OperationsDataTable, StatusFilter, and LiveCountdownTimer
    - Build the `OperationsDataTable` (columns ID, Product thumbnail+ASIN, Source user+location, Status badge, Time Remaining, Actions), a `StatusFilter` dropdown with exactly All/SCANNING/CACHED/RTO_QUEUED/NGO_QUEUED, and the `LiveCountdownTimer` ticking once per second as zero-padded HH:MM:SS, red+blinking in (0, 7200) s, default color >= 7200 s, frozen "00:00:00" at <= 0.
    - _Requirements: 14.4, 14.5, 14.6, 14.7, 15.1, 15.2, 15.3, 15.4_

  - [x]* 24.4 Write property test for countdown formatting
    - **Feature: amazon-edge-return, Property 28: Countdown formatting** — renders zero-padded HH:MM:SS for the seconds decomposition when positive and exactly "00:00:00" when at or below zero.
    - fast-check arbitrary over remaining-time values; 100+ iterations; one property per test.
    - **Validates: Requirements 15.1, 15.4**

  - [x]* 24.5 Write unit/snapshot tests for table filtering and countdown styling
    - Test filter behavior (All vs specific), invalid-status handling, and red-blink vs default-color countdown styling.
    - _Requirements: 14.3, 14.6, 14.7, 15.2, 15.3_

  - [x] 24.6 Implement `POST /api/admin/dispatch` and DispatchButton
    - Validate supported action (`400 UNSUPPORTED_ACTION`) and non-empty hub id (`400 HUB_REQUIRED`); transition all RTO_QUEUED→FC_TRANSIT, return transitioned count (0 when none, no changes) and recalculated metrics; wire the `DispatchButton`.
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x]* 24.7 Write property test for batch dispatch
    - **Feature: amazon-edge-return, Property 26: Batch dispatch transitions all RTO_QUEUED returns** — transitions exactly RTO_QUEUED→FC_TRANSIT, leaves others unchanged, returns count equal to prior RTO_QUEUED (0 when none), and recalculated metrics satisfy the metric bounds.
    - 100+ iterations; one property per test.
    - **Validates: Requirements 16.1, 16.2, 16.5**

- [x] 25. Final checkpoint — full system wired and verified
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation sub-tasks are never optional.
- Each task references specific granular requirements for traceability and builds on prior tasks with no orphaned code — pure cores (Phase 2) are wired into services and endpoints, which the frontend (Phases 3–6) consumes.
- Property-based tests use Hypothesis (backend) and fast-check (frontend), 100+ iterations, one property per test, tagged `Feature: amazon-edge-return, Property {n}: ...`; example/integration/snapshot tests cover timing, visual tokens, and external-service wiring.
- Mock-vs-real choices are explicit: real for core demonstrable paths (auth, demand index, scanner pool, matching, resale, lifecycle, admin reads/dispatch) and mocked/hardcoded for harder estimation/analytics math and AI scans, all behind swappable seams.
- Checkpoints provide incremental validation at phase boundaries.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "5.1", "6.1", "6.3", "7.1"] },
    { "id": 3, "tasks": ["3.2", "5.2", "5.3", "5.4", "6.2", "6.4", "6.5", "7.2", "7.3", "8.1", "9.1"] },
    { "id": 4, "tasks": ["8.2", "8.3", "8.4", "9.2", "9.3", "9.4", "10.1"] },
    { "id": 5, "tasks": ["8.5", "10.2", "10.3", "10.4", "11.1"] },
    { "id": 6, "tasks": ["11.2", "11.3", "11.4", "13.1", "14.1", "17.1", "18.1", "23.1", "24.1", "24.6"] },
    { "id": 7, "tasks": ["13.2", "14.2", "16.1", "17.2", "18.2", "20.2", "21.1", "23.2", "24.2", "24.7"] },
    { "id": 8, "tasks": ["14.3", "16.2", "17.3", "18.3", "20.1", "21.2", "23.3"] },
    { "id": 9, "tasks": ["16.3", "16.4", "17.4", "18.4", "21.3", "21.4", "23.4", "24.3"] },
    { "id": 10, "tasks": ["24.4", "24.5"] }
  ]
}
```
