# Copyright 2015 CloudFounders NV
# All rights reserved

"""
Exceptions
"""


class APIException(Exception):
    status_code = 400


class BadRequest(APIException):
    status_code = 400
