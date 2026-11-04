from rest_framework import status
from rest_framework.exceptions import APIException


class BusinessError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Request cannot be processed."
    default_code = "business_error"


class NotFoundError(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Not found."
    default_code = "not_found"


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Request conflicts with the current state."
    default_code = "conflict"


class UpstreamError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Events Provider is temporarily unavailable."
    default_code = "upstream_error"
