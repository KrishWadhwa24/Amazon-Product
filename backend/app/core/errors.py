"""Shared domain errors for the backend pure cores and services.

These are transport-agnostic exceptions raised by the side-effect-free decision
cores (e.g. the return lifecycle state machine). The API/transport layer maps
them to HTTP responses; the cores themselves never import FastAPI so they stay
property-testable in isolation.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for backend domain errors.

    Each subclass declares a stable machine-readable ``code`` and the
    ``http_status`` the transport layer should respond with. A single FastAPI
    exception handler (see ``app.main``) reads these attributes and renders the
    consistent error envelope ``{"error": {"code", "message"}}`` from the
    design's REST API Contract, so the pure cores/services never import FastAPI.
    """

    #: Machine-readable error code surfaced in the response envelope.
    code: str = "DOMAIN_ERROR"
    #: HTTP status code the transport layer maps this error to.
    http_status: int = 400


class AuthError(DomainError):
    """Raised when a user-context action lacks an authenticated session.

    Maps to ``401`` with code ``NO_SESSION`` (design "Error Class to HTTP
    Mapping"; Requirements 1.4, 3.7). Used by the return-initiation flow when no
    signed session cookie resolves to a user (Requirement 3.7).
    """

    code = "NO_SESSION"
    http_status = 401

    def __init__(self, message: str = "Authentication required; no active session.") -> None:
        super().__init__(message)


class LoginFailedError(DomainError):
    """Raised when login credentials do not match any seeded account.

    Per Requirement 1.3 the Auth_Service rejects the login attempt, establishes
    no authenticated session, and the Frontend displays an authentication-failed
    message. The design's REST API Contract specifies ``401 AUTH_FAILED`` for
    ``POST /api/auth/login`` mismatches, so this error carries the distinct code
    ``AUTH_FAILED`` — leaving :class:`AuthError`'s ``NO_SESSION`` for the
    missing/forged-session case on protected routes (Requirement 1.4).
    """

    code = "AUTH_FAILED"
    http_status = 401

    def __init__(self, message: str = "Authentication failed: invalid email or password.") -> None:
        super().__init__(message)


class ForbiddenError(DomainError):
    """Raised when an authenticated user acts on a resource they do not own.

    Maps to ``403`` with code ``NOT_AUTHORIZED`` (Requirement 9.7). Defined here
    for the shared error surface; consumed by the match lifecycle endpoints.
    """

    code = "NOT_AUTHORIZED"
    http_status = 403

    def __init__(self, message: str = "You are not authorized to perform this action.") -> None:
        super().__init__(message)


class OfferUnavailableError(DomainError):
    """Raised when a buyer acts on a MatchCandidate that is not PENDING.

    Per Requirement 9.6 the Backend_API rejects an accept/reject on a candidate
    whose status is no longer PENDING (already ACCEPTED, REJECTED, or EXPIRED),
    leaves the candidate unchanged, and returns an error indicating the offer is
    no longer available. Maps to ``409`` with code ``OFFER_UNAVAILABLE``.
    """

    code = "OFFER_UNAVAILABLE"
    http_status = 409

    def __init__(
        self, message: str = "This local deal offer is no longer available."
    ) -> None:
        super().__init__(message)


class NotEligibleError(DomainError):
    """Raised when a return is initiated for a product not in the user's history.

    Per Requirement 3.7 the Backend_API rejects the request, creates no
    ReturnOrder, and returns an error indicating return initiation is not
    permitted. Maps to ``422`` with code ``RETURN_NOT_PERMITTED`` (design "Error
    Class to HTTP Mapping").
    """

    code = "RETURN_NOT_PERMITTED"
    http_status = 422

    def __init__(
        self,
        message: str = (
            "Return initiation is not permitted: the referenced order is not in "
            "the requesting user's order history."
        ),
    ) -> None:
        super().__init__(message)


class UnsupportedGradeError(DomainError):
    """Raised when a resale listing supplies an unrecognized condition_grade.

    Per Requirement 11.4 the Backend_API rejects a resale listing whose
    ``condition_grade`` is not one of "Like New", "Good", or "Fair", creates no
    ResaleListing, and returns an error indicating an unsupported grade. Maps to
    ``422`` with code ``UNSUPPORTED_GRADE``. The offending value is retained as
    an attribute for diagnostics.
    """

    code = "UNSUPPORTED_GRADE"
    http_status = 422

    def __init__(self, grade: object = None) -> None:
        self.grade = grade
        super().__init__(
            f"Unsupported condition_grade {grade!r}; expected one of "
            '"Like New", "Good", or "Fair".'
        )


class MissingImageError(DomainError):
    """Raised when a resale listing omits/empties the condition_image_url.

    Per Requirement 11.7 the Backend_API rejects a resale listing that omits the
    ``condition_image_url`` or supplies an empty one, creates no ResaleListing,
    and returns an error indicating the image is required. Maps to ``422`` with
    code ``CONDITION_IMAGE_REQUIRED``.
    """

    code = "CONDITION_IMAGE_REQUIRED"
    http_status = 422

    def __init__(
        self,
        message: str = (
            "A non-empty condition_image_url is required for a resale listing."
        ),
    ) -> None:
        super().__init__(message)


class InvalidResalePriceError(DomainError):
    """Raised when a resale price is outside ``(0, product.price]``.

    Per Requirement 11.2 a ResaleListing's ``resale_price`` must be greater than
    0 and less than or equal to the original Product price. When it is not, the
    request is rejected and no ResaleListing is created. Maps to ``422`` with
    code ``INVALID_RESALE_PRICE``; the offending price and the product ceiling
    are retained as attributes for diagnostics.
    """

    code = "INVALID_RESALE_PRICE"
    http_status = 422

    def __init__(self, resale_price: object = None, product_price: object = None) -> None:
        self.resale_price = resale_price
        self.product_price = product_price
        super().__init__(
            f"Invalid resale_price {resale_price!r}; must be greater than 0 and "
            f"less than or equal to the original product price {product_price!r}."
        )


class InvalidTransitionError(DomainError):
    """Raised when a ReturnOrder status transition is not in the lifecycle.

    Names both the requested source and target status so callers (and the API
    error response, Requirement 10.7) can identify the rejected transition. The
    offending statuses are also retained as attributes for programmatic use.
    """

    code = "INVALID_TRANSITION"
    http_status = 409

    def __init__(self, source: object, target: object) -> None:
        self.source = source
        self.target = target
        source_name = getattr(source, "value", source)
        target_name = getattr(target, "value", target)
        super().__init__(
            f"Invalid return lifecycle transition from {source_name} to "
            f"{target_name}"
        )


class InvalidLocationError(DomainError):
    """Raised when a buyer's coordinates are absent or out of geographic bounds.

    A demand signal must carry a longitude in ``[-180, 180]`` and a latitude in
    ``[-90, 90]`` (Requirement 4.6). When the coordinates are missing or fall
    outside those bounds the Demand Signal Service rejects the recording and
    makes no write to the Geospatial_Index; the API maps this error to a
    ``400/422 INVALID_LOCATION`` response. The offending ``lon``/``lat`` are
    retained as attributes for programmatic use and diagnostics.

    Maps to ``400`` with code ``INVALID_LOCATION`` (design "REST API Contract";
    Requirement 4.6).
    """

    code = "INVALID_LOCATION"
    http_status = 400

    def __init__(self, lon: object = None, lat: object = None) -> None:
        self.lon = lon
        self.lat = lat
        super().__init__(
            f"Invalid buyer location: lon={lon!r}, lat={lat!r}; "
            "longitude must be in [-180, 180] and latitude in [-90, 90]"
        )


class ProductNotFoundError(DomainError):
    """Raised when a catalog read references an ASIN with no Product.

    Backs ``GET /api/products/{asin}`` and the demand endpoints' product
    existence check: when no Product matches the requested ASIN the Backend_API
    returns ``404`` with code ``PRODUCT_NOT_FOUND``, rendered via the shared
    domain-error envelope. The offending ASIN is retained for diagnostics.
    """

    code = "PRODUCT_NOT_FOUND"
    http_status = 404

    def __init__(self, asin: object = None) -> None:
        self.asin = asin
        super().__init__(f"No product found for asin {asin!r}.")


class SignalNotRecordedError(DomainError):
    """Raised when a demand signal cannot be persisted to the Geospatial_Index.

    Per Requirement 4.7, if the native Redis geospatial add operation fails the
    Backend_API must return an error indicating the demand signal was not
    recorded and must never report the signal as successfully stored. The demand
    endpoints catch the lower-level
    :class:`~app.db.redis_gateway.SignalStorageError` (which is *not* a
    :class:`DomainError`) and raise this instead so the shared domain-error
    handler renders the consistent ``502 SIGNAL_NOT_RECORDED`` envelope. Chain
    the original storage exception via ``raise ... from exc`` to preserve the
    underlying cause for diagnostics.
    """

    code = "SIGNAL_NOT_RECORDED"
    http_status = 502

    def __init__(
        self,
        message: str = (
            "The demand signal could not be recorded; please try again later."
        ),
    ) -> None:
        super().__init__(message)


class InvalidStatusFilterError(DomainError):
    """Raised when the admin returns filter status is neither ALL nor recognized.

    Per Requirement 14.3, ``GET /api/admin/returns`` rejects a ``status`` query
    value that is neither ``ALL`` nor a recognized ReturnOrder status value (nor
    one of the admin display aliases CACHED/RTO_QUEUED/NGO_QUEUED), returns no
    ReturnOrder data, and returns an error indicating the status value is
    invalid. Maps to ``400`` with code ``INVALID_STATUS``. The offending value is
    retained as an attribute for diagnostics.
    """

    code = "INVALID_STATUS"
    http_status = 400

    def __init__(self, status_value: object = None) -> None:
        self.status_value = status_value
        super().__init__(
            f"Invalid returns filter status {status_value!r}; expected 'ALL', a "
            "recognized ReturnOrder status, or one of the aliases 'CACHED', "
            "'RTO_QUEUED', 'NGO_QUEUED'."
        )


class UnsupportedActionError(DomainError):
    """Raised when a batch-dispatch request specifies an unsupported action.

    Per Requirement 16.3, when ``POST /api/admin/dispatch`` is called with an
    ``action`` value that is not in the set of supported actions, the
    Backend_API rejects the request, makes no ReturnOrder status changes, and
    returns an error indicating the action is unsupported. Maps to ``400`` with
    code ``UNSUPPORTED_ACTION`` (design "Error Class to HTTP Mapping"). The
    offending value is retained as an attribute for diagnostics.
    """

    code = "UNSUPPORTED_ACTION"
    http_status = 400

    def __init__(self, action: object = None) -> None:
        self.action = action
        super().__init__(
            f"Unsupported dispatch action {action!r}; the action is not in the "
            "set of supported dispatch actions."
        )


class MissingHubError(DomainError):
    """Raised when a batch-dispatch request omits/empties the hub identifier.

    Per Requirement 16.4, when ``POST /api/admin/dispatch`` omits the hub
    identifier or provides an empty one, the Backend_API rejects the request,
    makes no ReturnOrder status changes, and returns an error indicating the hub
    identifier is required. Maps to ``400`` with code ``HUB_REQUIRED`` (design
    "Error Class to HTTP Mapping").
    """

    code = "HUB_REQUIRED"
    http_status = 400

    def __init__(
        self,
        message: str = (
            "A non-empty hub identifier is required to dispatch queued returns."
        ),
    ) -> None:
        super().__init__(message)


class UnsupportedImageError(DomainError):
    """Raised when an uploaded product photo is missing or not an image.

    Maps to ``400`` with code ``UNSUPPORTED_IMAGE``. The offending content type
    is retained for diagnostics.
    """

    code = "UNSUPPORTED_IMAGE"
    http_status = 400

    def __init__(self, content_type: object = None) -> None:
        self.content_type = content_type
        super().__init__(
            f"Unsupported or missing image upload (content type {content_type!r}); "
            "please upload a JPEG, PNG, WebP, or GIF image."
        )


class ResaleListingNotFoundError(DomainError):
    """Raised when a resale purchase/cart action references an unknown listing.

    Maps to ``404`` with code ``RESALE_LISTING_NOT_FOUND``. The offending id is
    retained for diagnostics.
    """

    code = "RESALE_LISTING_NOT_FOUND"
    http_status = 404

    def __init__(self, listing_id: object = None) -> None:
        self.listing_id = listing_id
        super().__init__(f"No resale listing found for id {listing_id!r}.")


class ResaleListingUnavailableError(DomainError):
    """Raised when a buyer acts on a resale listing that is no longer ACTIVE.

    A listing that has already been SOLD or REMOVED cannot be purchased or added
    to a cart again. Maps to ``409`` with code ``RESALE_UNAVAILABLE``.
    """

    code = "RESALE_UNAVAILABLE"
    http_status = 409

    def __init__(
        self,
        message: str = "This resale listing is no longer available.",
    ) -> None:
        super().__init__(message)


class StoreUnavailableError(DomainError):
    """Raised when the Relational_Store cannot be reached while serving a read.

    Per Requirement 12.3 the Backend_API, when it cannot reach the
    Relational_Store while serving ``GET /api/resale/feed``, returns an error
    response and no partial result set. Maps to ``503`` with code
    ``STORE_UNAVAILABLE`` (design "REST API Contract"). The triggering
    persistence exception should be chained via ``raise ... from exc`` so the
    underlying cause is preserved for diagnostics.
    """

    code = "STORE_UNAVAILABLE"
    http_status = 503

    def __init__(
        self,
        message: str = (
            "The data store is currently unavailable; please try again later."
        ),
    ) -> None:
        super().__init__(message)
