"""Back-compat shim: ``sms_api_client`` was renamed to ``viva_api_client``.

``SmsApiClient``/``SmsApiError`` moved to :mod:`vivarium_workbench.lib.viva_api_client`
as ``VivaApiClient``/``VivaApiError`` (the client itself is unchanged — same
sms-api HTTP surface, only the identifiers follow the sms-api -> viva-api
rename). This module re-exports both names so existing
``from vivarium_workbench.lib.sms_api_client import SmsApiClient`` /
``SmsApiError`` call sites keep working during the deprecation window.

Importing this module emits a one-time :class:`DeprecationWarning`. Update
imports to ``viva_api_client`` / ``VivaApiClient`` / ``VivaApiError``; this
shim is removed in a future major release.
"""
from __future__ import annotations

import warnings

from vivarium_workbench.lib.viva_api_client import VivaApiClient, VivaApiError

warnings.warn(
    "vivarium_workbench.lib.sms_api_client is renamed to "
    "vivarium_workbench.lib.viva_api_client (SmsApiClient -> VivaApiClient, "
    "SmsApiError -> VivaApiError); update your imports (the sms_api_client "
    "alias is removed in a future major release).",
    DeprecationWarning,
    stacklevel=2,
)

# Deprecated aliases — re-exported under both old and new names.
SmsApiClient = VivaApiClient
SmsApiError = VivaApiError

__all__ = ["VivaApiClient", "VivaApiError", "SmsApiClient", "SmsApiError"]
