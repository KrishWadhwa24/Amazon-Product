# Requirements Document

## Introduction

Amazon Edge-Return is a decentralized logistics, real-time return intercept, and peer-to-peer resale system. When a customer initiates a return, the returned item enters a 48-hour scanning pool where it remains discoverable to nearby buyers who express purchase intent for the same product. A continuous matching engine watches real-time demand signals (cart, buy-now, wishlist, and product views), correlates them against active return orders within a 20km radius, and surfaces instant "Local Open-Box Deal" notifications to buyers. Items that are not claimed within the window are routed to fulfillment centers, NGOs, or micro-warehouses. The system also supports an extended resale marketplace for previously purchased items.

This document specifies the requirements for a production-ready prototype spanning a Next.js frontend, a FastAPI backend, PostgreSQL relational storage, and a Redis geospatial demand index. The prototype must replicate the official Amazon web and mobile aesthetic and includes a seller flow, a buyer flow, a resale marketplace, and an operations admin dashboard.

## Glossary

- **System**: The complete Amazon Edge-Return application, including frontend, backend, relational database, and geospatial cache.
- **Frontend**: The Next.js (App Router) web client.
- **Backend_API**: The FastAPI (asynchronous ASGI) service exposing HTTP endpoints.
- **Relational_Store**: The PostgreSQL database accessed via SQLAlchemy and asyncpg.
- **Geospatial_Index**: The Redis store holding demand signals keyed by intent and ASIN, accessed via native Redis geospatial commands (GEOADD, GEOSEARCH).
- **Matching_Engine**: The backend component that correlates demand signals against active return orders and creates match candidates.
- **Return_Scanner_Pool**: The set of ReturnOrder records with status SCANNING and a non-expired window.
- **Notification_Service**: The component that delivers match notifications to buyers, using a 3-second short-polling loop or WebSocket notification endpoint.
- **Resale_Marketplace**: The component that lists and serves previously purchased items as verified used deals.
- **Admin_Dashboard**: The operations console at `/admin/operations`.
- **User**: A person represented by a User record with a name and geographic coordinates; acts as Seller (return initiator) or Buyer (demand signal source) depending on the action taken in the current session.
- **Seller**: A logged-in User who initiates a return or a resale listing; any User with OrderHistory may act as a Seller.
- **Buyer**: A logged-in User who expresses purchase intent through a demand signal.
- **Auth_Service**: The component that authenticates a User login and establishes an authenticated session context.
- **ASIN**: The Amazon Standard Identification Number, a unique product identifier.
- **Demand_Signal**: A buyer intent event of type cart, buy-now, wishlist, or view, recorded in the Geospatial_Index.
- **Demand_Score**: A numeric priority assigned to a demand signal source: Cart=100, Buy_Now=90, Wishlist=70, Recently_Viewed=40.
- **Match_Candidate**: A MatchCandidate record linking an active ReturnOrder to a Buyer with a computed distance and signal source.
- **Local_Discount**: The price reduction offered on a local open-box deal, equal to MIN(estimated_logistics_savings, 15% of product price).
- **Match_Radius**: The maximum geographic distance, 20 kilometers, within which a Buyer is eligible to match a ReturnOrder.
- **Return_Window**: The 48-hour interval between a ReturnOrder's initiated_at and expires_at timestamps.
- **Seed_Script**: The `seed.py` script that drops, recreates, and seeds the Relational_Store and Geospatial_Index.
- **Return_Lifecycle**: The state machine governing valid ReturnOrder status transitions.
- **ResaleListing**: A record representing a previously purchased Product offered for resale, with attributes status, condition_grade, resale_price, listed_at, and condition_image_url.
- **condition_image_url**: A non-empty URL string stored on a ResaleListing that references the mock camera capture of the item's live physical condition.
- **Estimated_Reverse_Logistics_Cost**: The system's estimated cost, expressed as a non-negative currency value in Indian Rupees (₹), of transporting a ReturnOrder's Product back through reverse transit to a fulfillment center.
- **Reverse_Transit_Threshold**: The decision threshold for reverse-transit financial viability, equal to the Estimated_Reverse_Logistics_Cost of a ReturnOrder's Product plus a fixed buffer of ₹150.
- **MICROWAREHOUSE**: The terminal ReturnOrder state representing local cache storage of an item; also referred to as CACHE_STORAGE. MICROWAREHOUSE is the canonical state name used throughout this document.

## Requirements

### Requirement 1: User Login and Session Context

**User Story:** As a user, I want to log in as a specific account, so that the application acts on my behalf as a seller or a buyer.

#### Acceptance Criteria

1. THE Frontend SHALL provide a login interface that displays the seeded User accounts and allows a User to select and authenticate as exactly one of them.
2. WHEN a User submits credentials that match a seeded account, THE Auth_Service SHALL establish exactly one authenticated session bound to that User's identifier.
3. IF a User submits credentials that do not match any seeded account, THEN THE Auth_Service SHALL reject the login attempt, establish no authenticated session, and the Frontend SHALL display an error message indicating that authentication failed.
4. WHILE an authenticated session is active, THE Backend_API SHALL associate every request that depends on user context with the logged-in User's identifier.
5. WHERE the logged-in User has at least one OrderHistory record, THE Frontend SHALL allow the logged-in User to act as a Seller and initiate returns or resale listings.
6. WHEN a User logs out, THE Auth_Service SHALL terminate the active authenticated session so that no subsequent request is associated with that User's identifier.
7. WHEN a User logs out and a different User logs in, THE Frontend SHALL replace all user-specific content (cart contents, order history, and match notifications) so that it reflects only the newly authenticated User's data within 3 seconds of the new session being established.
8. WHEN the logged-in User adds to the cart a Product that has an active SCANNING ReturnOrder matched to that User within the Match_Radius of 20 kilometers, THE Frontend SHALL display an in-app notification within 3 seconds indicating that another user has returned the same product nearby.

### Requirement 2: Catalog and Order History Data

**User Story:** As a demo operator, I want seeded users, products, and order history, so that the flows operate on realistic data.

#### Acceptance Criteria

1. WHEN the Seed_Script runs, THE Seed_Script SHALL drop all existing tables in the Relational_Store, recreate the schema, and populate the seed data in that order, completing successfully whether or not those tables exist prior to execution.
2. IF any phase of the Seed_Script (table drop, schema creation, or data population) fails, THEN THE Seed_Script SHALL abort the remaining phases, leave no partially populated seed data committed to the Relational_Store, and return a non-zero exit status with an error message identifying the failed phase.
3. WHEN the Seed_Script runs, THE Seed_Script SHALL create User Priya Sharma with role Seller, latitude 12.9781, and longitude 77.6389.
4. WHEN the Seed_Script runs, THE Seed_Script SHALL create User Rahul Verma with role Buyer, latitude 12.9352, and longitude 77.6271, and a cart containing zero items.
5. WHEN the Seed_Script runs, THE Seed_Script SHALL create a product catalog of between 5 and 50 Product records, where each Product record has an ASIN that is non-empty and unique across the catalog, a non-empty name, a price greater than 0.00, a rating between 0.0 and 5.0 inclusive, a review_count that is an integer of 0 or greater, and a non-empty image_url.
6. WHEN the Seed_Script runs, THE Seed_Script SHALL create at least 2 OrderHistory records for Priya Sharma that include "Sony WH-CH520 Wireless Headphones" and "Levi's T-Shirt", where each OrderHistory record references an existing Product in the seeded catalog and has a purchased_at timestamp earlier than the current time.
7. WHEN the Seed_Script runs, THE Seed_Script SHALL initialize the Geospatial_Index to contain zero Demand_Signal entries and to reference no ASIN that is absent from the seeded catalog.

### Requirement 3: Return Initiation and 48-Hour Scanner Pool

**User Story:** As a seller, I want to initiate a return that becomes discoverable to nearby buyers, so that my returned item can be resold locally instead of shipped back.

#### Acceptance Criteria

1. WHEN a Seller submits a return initiation request through `POST /api/returns/initiate` that references a Product present in the Seller's OrderHistory, THE Backend_API SHALL create a ReturnOrder with status SCANNING, initiated_at set to the current server time, and expires_at set to initiated_at plus exactly 48 hours (172,800 seconds).
2. WHEN a ReturnOrder is created, THE Backend_API SHALL associate the ReturnOrder with the initiating User's identifier and the returned Product's ASIN.
3. WHILE a ReturnOrder has status SCANNING and expires_at is later than the current time, THE Return_Scanner_Pool SHALL include the ReturnOrder as discoverable.
4. WHEN the current time reaches or passes a ReturnOrder's expires_at while the ReturnOrder status is SCANNING and no MatchCandidate for that ReturnOrder is ACCEPTED, THE Backend_API SHALL transition the ReturnOrder from SCANNING to status EXPIRED within 1 second of detection in accordance with the Return_Lifecycle.
5. WHEN a ReturnOrder transitions to EXPIRED, THE Backend_API SHALL remove the ReturnOrder from the Return_Scanner_Pool within 1 second so that it is no longer discoverable.
6. WHEN a Seller initiates a return through the Frontend, THE Frontend SHALL display an "Amazon AI Item Verification Scan" modal for 2 seconds (with a tolerance of plus or minus 200 milliseconds) and SHALL submit the return initiation request only after the modal is dismissed.
7. IF a return initiation request is submitted without an authenticated Seller session or references a Product that is not present in the requesting User's OrderHistory, THEN THE Backend_API SHALL reject the request, create no ReturnOrder, and return an error response indicating that return initiation is not permitted.

### Requirement 4: Real-Time Demand Index

**User Story:** As the system, I want to record buyer purchase intent with location data, so that the matching engine can find nearby demand for returned items.

#### Acceptance Criteria

1. WHEN a Buyer adds a product to the cart, THE Backend_API SHALL record a demand signal in the Geospatial_Index under the key `demand:cart:{asin}` using the Buyer's longitude, latitude, and identifier within 1 second of the action.
2. WHEN a Buyer selects buy-now for a product, THE Backend_API SHALL record a demand signal in the Geospatial_Index under the key `demand:buynow:{asin}` using the Buyer's longitude, latitude, and identifier within 1 second of the action.
3. WHEN a Buyer adds a product to the wishlist, THE Backend_API SHALL record a demand signal in the Geospatial_Index under the key `demand:wishlist:{asin}` using the Buyer's longitude, latitude, and identifier within 1 second of the action.
4. WHEN a Buyer views a product, THE Backend_API SHALL record a demand signal in the Geospatial_Index under the key `demand:viewed:{asin}` using the Buyer's longitude, latitude, and identifier within 1 second of the action.
5. THE Backend_API SHALL store each demand signal using the native Redis geospatial add operation with the Buyer's longitude and latitude as coordinates and the Buyer's identifier as the member, overwriting any existing entry with the same identifier under the same key so that at most one entry per Buyer exists per key.
6. IF the Buyer's coordinates are absent or fall outside the valid geographic bounds of -180 to 180 degrees longitude and -90 to 90 degrees latitude, THEN THE Backend_API SHALL reject the demand signal recording, make no write to the Geospatial_Index, and return an error indicating an invalid Buyer location.
7. IF the native Redis geospatial add operation fails, THEN THE Backend_API SHALL return an error indicating the demand signal was not recorded and SHALL NOT report the signal as successfully stored.

### Requirement 5: Demand Signal Scoring

**User Story:** As the system, I want to prioritize stronger purchase intent, so that the most likely buyer is offered a deal first when multiple buyers match.

#### Acceptance Criteria

1. THE Matching_Engine SHALL assign a Demand_Score of exactly 100 to a cart signal, exactly 90 to a buy-now signal, exactly 70 to a wishlist signal, and exactly 40 to a recently-viewed (view) signal.
2. WHERE two or more demand signals match a single ReturnOrder, THE Matching_Engine SHALL rank those signals in descending order of Demand_Score and select the signal with the highest Demand_Score as the one offered the deal first.
3. IF two or more demand signals matching a single ReturnOrder have an equal highest Demand_Score, THEN THE Matching_Engine SHALL select the signal with the earliest recorded timestamp as the one offered the deal first.

### Requirement 6: Continuous Matching Engine

**User Story:** As a buyer, I want to be matched to a nearby returned item when I show interest in that product, so that I can claim a faster, cheaper local deal.

#### Acceptance Criteria

1. WHEN a Demand_Signal is recorded, THE Matching_Engine SHALL identify the ASIN associated with the signal.
2. WHEN a Demand_Signal is recorded, THE Matching_Engine SHALL find ReturnOrders that have status SCANNING, an expires_at strictly later than the current time, a Product ASIN equal to the signal's ASIN, and a Seller whose identifier differs from the Buyer that produced the signal.
3. WHEN one or more candidate ReturnOrders are found, THE Matching_Engine SHALL calculate the geographic distance in kilometers, rounded to two decimal places, between the Buyer and each candidate ReturnOrder's Seller.
4. WHERE more than one candidate ReturnOrder is within the Match_Radius of 20 kilometers, THE Matching_Engine SHALL select the single ReturnOrder with the smallest distance, using the earliest expires_at as the tie-breaker when distances are equal.
5. IF the selected candidate's calculated distance is less than or equal to the Match_Radius of 20 kilometers and no PENDING MatchCandidate already exists for that Buyer and ReturnOrder pair, THEN THE Matching_Engine SHALL create a MatchCandidate record with status PENDING, the calculated distance_km, and the signal_source equal to the Demand_Signal type.
6. WHEN a MatchCandidate is created, THE Notification_Service SHALL deliver a match notification to the Buyer within 3 seconds.
7. WHEN a MatchCandidate is created, THE Backend_API SHALL increment the active-match count by one.
8. IF the selected candidate's calculated distance is greater than the Match_Radius, THEN THE Matching_Engine SHALL NOT create a MatchCandidate for that Buyer and ReturnOrder pair.
9. IF a PENDING MatchCandidate already exists for the Buyer and the selected ReturnOrder pair, THEN THE Matching_Engine SHALL NOT create a duplicate MatchCandidate.
10. IF no ReturnOrder satisfies the selection conditions for the recorded Demand_Signal, THEN THE Matching_Engine SHALL create no MatchCandidate and leave existing MatchCandidate records unchanged.

### Requirement 7: Local Deal Price Optimization

**User Story:** As a buyer, I want to see how much money, time, and carbon I save with a local deal, so that I can decide whether to claim it.

#### Acceptance Criteria

1. WHEN a MatchCandidate is created, THE Backend_API SHALL calculate the Local_Discount as the minimum of the estimated logistics savings and 15 percent of the Product price, where the result is a non-negative currency amount rounded to 2 decimal places, and where a calculated value below 0.01 is treated as 0.00.
2. WHEN a match notification is delivered, THE Notification_Service SHALL display the money saved as a currency value equal to the Local_Discount, the delivery time saved as a whole number of hours greater than or equal to 0, and the carbon emissions avoided as a value in kilograms of CO2 rounded to 1 decimal place and greater than or equal to 0.
3. IF the carbon emissions avoided for a candidate local match is less than 0.1 kilograms of CO2 compared to the original delivery, THEN THE Notification_Service SHALL deliver the match notification without any claim of environmental benefit and SHALL omit the carbon emissions avoided value from the notification.
4. WHEN a match notification is displayed to the Buyer, THE Frontend SHALL present a "Claim Deal" action and a "Keep Original Delivery" action, with both actions enabled and visible.

### Requirement 8: Match Notification Delivery

**User Story:** As a buyer, I want match notifications to appear promptly after I show interest, so that the local deal feels real-time.

#### Acceptance Criteria

1. WHEN a PENDING MatchCandidate is created for the active Buyer, THE Notification_Service SHALL make the match notification available to the active Buyer within 3 seconds, using either a short-polling loop with a polling interval of 3 seconds or a WebSocket notification endpoint.
2. WHEN a PENDING MatchCandidate exists for the active Buyer and both the "Claim Deal" and "Keep Original Delivery" actions are available, THE Frontend SHALL display, within 3 seconds of the MatchCandidate becoming available to the Buyer, a match notification popup containing the deal headline, money saved, delivery time saved, and carbon emissions avoided.
3. WHILE no PENDING MatchCandidate exists for the active Buyer, THE Frontend SHALL display no match notification popup.
4. WHEN the active Buyer accepts a match by selecting "Claim Deal", THE Frontend SHALL hide the match notification popup within 1 second.
5. WHEN the active Buyer selects "Keep Original Delivery" for the displayed match notification, THE Frontend SHALL hide the match notification popup within 1 second.
6. IF the Notification_Service cannot deliver a PENDING match notification to the active Buyer within 3 seconds, THEN THE Notification_Service SHALL retry delivery on the next polling cycle and SHALL preserve the MatchCandidate in PENDING status until it is delivered or its associated ReturnOrder leaves the SCANNING state.

### Requirement 9: Match Candidate Lifecycle

**User Story:** As the system, I want to track the outcome of each match offer, so that returns and analytics reflect buyer decisions.

#### Acceptance Criteria

1. WHEN a MatchCandidate is created, THE Backend_API SHALL set the MatchCandidate status to PENDING.
2. WHEN the Buyer associated with a PENDING MatchCandidate selects "Claim Deal" for that MatchCandidate, THE Backend_API SHALL set the MatchCandidate status to ACCEPTED within 2 seconds.
3. WHEN the Buyer associated with a PENDING MatchCandidate selects "Keep Original Delivery" for that MatchCandidate, THE Backend_API SHALL set the MatchCandidate status to REJECTED within 2 seconds.
4. IF a MatchCandidate remains PENDING when its associated ReturnOrder transitions to any status other than SCANNING (including EXPIRED, NGO_ROUTING, and MICROWAREHOUSE), THEN THE Backend_API SHALL set the MatchCandidate status to EXPIRED.
5. WHEN a MatchCandidate transitions to ACCEPTED, THE Backend_API SHALL advance the associated ReturnOrder along the Return_Lifecycle path SCANNING to MATCH_FOUND to BUYER_ACCEPTED to LOCAL_DELIVERY.
6. IF a Buyer attempts to accept or reject a MatchCandidate that is not in PENDING status, THEN THE Backend_API SHALL reject the action, leave the MatchCandidate status unchanged, and return an error indicating that the offer is no longer available.
7. IF a Buyer whose identifier does not match a MatchCandidate's Buyer attempts to accept or reject that MatchCandidate, THEN THE Backend_API SHALL reject the action, leave the MatchCandidate status unchanged, and return an error indicating the action is not authorized.
8. WHEN a MatchCandidate transitions to ACCEPTED, THE Backend_API SHALL set every other PENDING MatchCandidate for the same ReturnOrder to status EXPIRED.

### Requirement 10: Return Lifecycle State Machine

**User Story:** As an operations manager, I want returns to follow a defined lifecycle, so that every returned item reaches a valid disposition.

#### Acceptance Criteria

1. THE Backend_API SHALL permit the ReturnOrder transition sequence SCANNING → MATCH_FOUND → BUYER_ACCEPTED → LOCAL_DELIVERY, where each requested transition advances the status to exactly the next state in the sequence.
2. THE Backend_API SHALL permit the ReturnOrder transition sequence SCANNING → EXPIRED → FC_TRANSIT, where each requested transition advances the status to exactly the next state in the sequence.
3. THE Backend_API SHALL permit the ReturnOrder transition from SCANNING to NGO_ROUTING.
4. THE Backend_API SHALL permit the ReturnOrder transition from SCANNING to MICROWAREHOUSE.
5. WHEN a ReturnOrder status transition that is defined in the Return_Lifecycle is requested, THE Backend_API SHALL set the ReturnOrder status to the target state and return a confirmation identifying the resulting status.
6. THE Backend_API SHALL treat LOCAL_DELIVERY, FC_TRANSIT, NGO_ROUTING, and MICROWAREHOUSE as terminal ReturnOrder states from which no further transition is permitted.
7. IF a ReturnOrder status transition is requested whose source-to-target pair is not defined in the Return_Lifecycle, including any transition requested from a terminal state, THEN THE Backend_API SHALL reject the transition, leave the ReturnOrder's current status unchanged, and return an error response identifying the requested source status and target status as an invalid transition.
8. THE Backend_API SHALL permit the ReturnOrder transition from EXPIRED to NGO_ROUTING and the ReturnOrder transition from EXPIRED to MICROWAREHOUSE.
9. WHEN a ReturnOrder transitions from SCANNING to EXPIRED, THE Backend_API SHALL calculate a Reverse_Transit_Threshold equal to the Estimated_Reverse_Logistics_Cost of the ReturnOrder's Product plus a fixed buffer of ₹150.
10. IF a ReturnOrder has transitioned from SCANNING to EXPIRED and the ReturnOrder's Product price is less than or equal to the Reverse_Transit_Threshold, THEN THE Backend_API SHALL automatically transition the ReturnOrder from EXPIRED to NGO_ROUTING.
11. IF a ReturnOrder has transitioned from SCANNING to EXPIRED and the ReturnOrder's Product price is greater than the Reverse_Transit_Threshold, THEN THE Backend_API SHALL automatically transition the ReturnOrder from EXPIRED to MICROWAREHOUSE.
12. WHEN a ReturnOrder transitions from SCANNING to EXPIRED, THE Backend_API SHALL automatically route the ReturnOrder to exactly one of the two states NGO_ROUTING or MICROWAREHOUSE, determined by the comparison of the Product price against the Reverse_Transit_Threshold.

### Requirement 11: Extended Resale Marketplace Listing

**User Story:** As a seller, I want to resell an older purchased item through Amazon, so that I can recover value on items past the return window.

#### Acceptance Criteria

1. WHILE a Seller's OrderHistory is displayed and an OrderHistory record's purchased_at is more than 7 days before the current time, THE Frontend SHALL present a "Resell via Amazon" action for that order.
2. WHEN a Seller submits a resale listing through `POST /api/resale/list` with a mock AI camera grading result whose condition_grade is one of "Like New", "Good", or "Fair", THE Backend_API SHALL create a ResaleListing with status ACTIVE, the provided condition_grade, a resale_price greater than 0 and less than or equal to the original Product price, and listed_at set to the current time.
3. THE Backend_API SHALL accept condition_grade values of exactly "Like New", "Good", and "Fair" for a resale listing.
4. IF a resale listing request supplies a condition_grade that is not one of "Like New", "Good", or "Fair", THEN THE Backend_API SHALL reject the request, create no ResaleListing, and return an error indicating an unsupported condition_grade.
5. WHEN a Seller initiates a resale listing through the Frontend, THE Frontend SHALL display a mock AI scan for 2 seconds before the ResaleListing is created.
6. WHEN a Seller submits a resale listing through `POST /api/resale/list`, THE Backend_API SHALL accept a condition_image_url representing the mock camera capture and store it on the created ResaleListing as a non-empty URL string.
7. IF a resale listing request omits the condition_image_url or supplies an empty condition_image_url, THEN THE Backend_API SHALL reject the request, create no ResaleListing, and return an error indicating that the condition_image_url is required.

### Requirement 12: Resale Marketplace Feed

**User Story:** As a buyer, I want to browse verified used deals, so that I can purchase discounted authentic items.

#### Acceptance Criteria

1. WHEN a client requests `GET /api/resale/feed`, THE Backend_API SHALL return all ResaleListings with status ACTIVE, each joined with its Product and the original OrderHistory purchase date, ordered by listed_at with the most recent listing first.
2. IF no ResaleListing has status ACTIVE when `GET /api/resale/feed` is requested, THEN THE Backend_API SHALL return an empty collection rather than an error.
3. IF the Relational_Store cannot be reached while serving `GET /api/resale/feed`, THEN THE Backend_API SHALL return an error response and SHALL return no partial result set.
4. WHEN the `/local-deals` page loads and one or more active resale listings exist, THE Frontend SHALL display the active resale listings in a grid titled "Amazon Local Verified Used Deals".
5. WHEN the `/local-deals` page loads and no active resale listings exist, THE Frontend SHALL display the "Amazon Local Verified Used Deals" grid in an empty state without error.
6. WHEN a resale listing is displayed on the `/local-deals` page, THE Frontend SHALL show an "✅ Amazon Verified Original Purchase" badge and the listing's Condition Grade, where the Condition Grade is one of "Like New", "Good", or "Fair".
7. WHEN `GET /api/resale/feed` returns an active ResaleListing, THE Backend_API SHALL include in that listing's representation both the original Product image_url and the ResaleListing condition_image_url as non-empty URL strings.
8. WHEN a resale listing is displayed on the `/local-deals` page, THE Frontend SHALL render a Split-Trust image gallery that presents the official Product image_url as the primary image and the ResaleListing condition_image_url as a secondary thumbnail labeled with the badge text "Live Condition".

### Requirement 13: Admin Operations Metrics

**User Story:** As an operations manager, I want a metrics overview, so that I can monitor reverse-logistics performance.

#### Acceptance Criteria

1. WHEN a client requests `GET /api/admin/metrics`, THE Backend_API SHALL return the Cache Storage Capacity as a used count and a total count where the used count is between 0 and the total count and the total count is 1 or greater, the Reverse Logistics Saved amount as a non-negative currency value, the Carbon Offset Index as a non-negative kilograms-of-CO2 value, and the NGO CSR Credits as a non-negative currency value.
2. WHEN the Admin_Dashboard loads, THE Frontend SHALL render a four-column KPI grid displaying Cache Storage Capacity as a progress bar showing the used count, the total count, and the used-to-total percentage; Reverse Logistics Saved as a currency value with two decimal places; Carbon Offset Index as a kilograms-of-CO2 value with one decimal place; and NGO CSR Credits as a currency value with two decimal places.
3. IF one or more metrics cannot be retrieved while serving `GET /api/admin/metrics`, THEN THE Backend_API SHALL return an error response and SHALL return no partial metric values.
4. WHEN a metric value is zero, THE Frontend SHALL render the zero value rather than an empty or blank field.

### Requirement 14: Admin Operations Data Table

**User Story:** As an operations manager, I want to view and filter active returns, so that I can manage reverse-logistics operations.

#### Acceptance Criteria

1. WHEN a client requests `GET /api/admin/returns` with a status parameter equal to one of the recognized ReturnOrder status values or the value ALL, THE Backend_API SHALL return an array of ReturnOrders matching the requested status, each joined with its associated Product and User, and SHALL return all ReturnOrders when the status value is ALL.
2. WHEN a client requests `GET /api/admin/returns` with a status parameter for which no ReturnOrder matches, THE Backend_API SHALL return an empty array.
3. IF a client requests `GET /api/admin/returns` with a status parameter that is neither ALL nor a recognized ReturnOrder status value, THEN THE Backend_API SHALL reject the request, return no ReturnOrder data, and return an error response indicating that the status value is invalid.
4. WHEN the Admin_Dashboard operations table loads, THE Frontend SHALL display columns for ID, Product with thumbnail and ASIN, Source with user and location, Status as a styled badge, Time Remaining, and Actions.
5. THE Frontend SHALL provide a status filter dropdown containing exactly the options All, SCANNING, CACHED, RTO_QUEUED, and NGO_QUEUED.
6. WHEN the operations manager selects a status filter other than All, THE Frontend SHALL display only the ReturnOrders whose status equals the selected status value.
7. WHEN the operations manager selects the All status filter, THE Frontend SHALL display every ReturnOrder returned by the Backend_API regardless of status.

### Requirement 15: Admin Live Countdown Timer

**User Story:** As an operations manager, I want a live countdown for each return, so that I can prioritize items nearing expiry.

#### Acceptance Criteria

1. WHILE a ReturnOrder is displayed in the operations table and its expires_at is later than the current time, THE Frontend SHALL display a countdown derived from the difference between the ReturnOrder's expires_at and the current time, updated once per second, formatted as zero-padded hours, minutes, and seconds (HH:MM:SS).
2. WHILE a ReturnOrder is displayed in the operations table and its remaining time is greater than 0 seconds and less than 7200 seconds (2 hours), THE Frontend SHALL display the countdown text in red and alternate the countdown text between fully visible and fully hidden at a 1-second interval.
3. WHILE a ReturnOrder is displayed in the operations table and its remaining time is 7200 seconds (2 hours) or greater, THE Frontend SHALL display the countdown text in the default operations-table text color without alternating its visibility.
4. WHEN a displayed ReturnOrder's remaining time reaches or passes 0 seconds, THE Frontend SHALL display the countdown as "00:00:00" and stop decrementing it.

### Requirement 16: Admin Dispatch Action

**User Story:** As an operations manager, I want to batch-dispatch queued returns to a fulfillment hub, so that unclaimed items are routed efficiently.

#### Acceptance Criteria

1. WHEN a client submits `POST /api/admin/dispatch` with a supported action value and a non-empty hub identifier, THE Backend_API SHALL transition every ReturnOrder currently having status RTO_QUEUED to status FC_TRANSIT and return a success response stating the count of ReturnOrders transitioned.
2. WHEN a dispatch request completes successfully, THE Backend_API SHALL recalculate and return the Cache Storage Capacity, Reverse Logistics Saved amount, Carbon Offset Index, and NGO CSR Credits amount so that they reflect the post-dispatch state.
3. IF a dispatch request specifies an action value that is not in the set of supported actions, THEN THE Backend_API SHALL reject the request, make no ReturnOrder status changes, and return an error response indicating that the action is unsupported.
4. IF a dispatch request omits the hub identifier or provides an empty hub identifier, THEN THE Backend_API SHALL reject the request, make no ReturnOrder status changes, and return an error response indicating that the hub identifier is required.
5. WHEN a dispatch request is submitted with a supported action and a non-empty hub identifier but no ReturnOrder currently has status RTO_QUEUED, THE Backend_API SHALL return a success response with a transitioned count of zero and make no ReturnOrder status changes.

### Requirement 17: Amazon Visual Aesthetic

**User Story:** As a stakeholder, I want the interface to look like Amazon, so that the prototype is convincing and familiar.

#### Acceptance Criteria

1. THE Frontend SHALL apply the following design tokens consistently across all customer-facing pages (home, product listing, product detail, cart, and checkout): primary navy #232F3E to the top navigation bar, secondary dark blue #131921 to the secondary header band, Amazon orange #FF9900 to accent and call-to-attention elements, light teal #007185 to text links, and background gray #EAEDED to the page background.
2. THE Frontend SHALL render every primary action button with an 8px corner radius on all four corners and a top-to-bottom linear gradient transitioning from #FFD814 at the top edge to #F7CA00 at the bottom edge.
3. THE Admin_Dashboard SHALL render every page in dark mode using a slate-950 (#020617) background applied to the full viewport background.
4. THE Frontend SHALL maintain a minimum text-to-background contrast ratio of 4.5:1 for all body text on customer-facing pages.

### Requirement 18: Delayed Match Demonstration Flow

**User Story:** As a demo operator, I want to demonstrate an end-to-end match across two users, so that the real-time intercept value is clear.

#### Acceptance Criteria

1. WHEN the Seller initiates a return for the Sony WH-CH520 Wireless Headphones and no active Demand_Signal for that Product's ASIN exists from any Buyer within the Match_Radius of 20 kilometers, THE Backend_API SHALL create exactly one ReturnOrder with status SCANNING and create zero MatchCandidate records.
2. WHEN the demo operator switches the active user to the Buyer and the Buyer adds the Sony WH-CH520 Wireless Headphones to the cart from within the Match_Radius, THE Matching_Engine SHALL discover the active ReturnOrder and create exactly one MatchCandidate with status PENDING, a distance_km, and a signal_source of cart.
3. WHEN the MatchCandidate from the cart action is created, THE Notification_Service SHALL deliver to the Buyer within 3 seconds a notification headlined "🔥 Local Open-Box Deal Found Near You" with the money saved, delivery time saved, and carbon emissions avoided.
4. IF the Buyer who adds the Sony WH-CH520 Wireless Headphones to the cart is located outside the Match_Radius of 20 kilometers from the Seller, THEN THE Matching_Engine SHALL create no MatchCandidate and THE Notification_Service SHALL deliver no match notification.
