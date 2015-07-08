# Copyright 2015 Open vStorage NV
# All rights reserved

"""
Exceptions
"""


class APIException(Exception):
    status_code = 400


class BadRequest(APIException):
    status_code = 400
