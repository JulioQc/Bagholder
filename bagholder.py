#!/usr/bin/env python3
"""
Bagholder — unofficial local Wealthsimple session reuse.
Passkey login happens on Wealthsimple's own site (we just open that URL).
After capture of the first-party session, later syncs are silent on this computer.
Nothing is hosted publicly. Tokens never leave this machine.

Run:  python3 bagholder.py
Open the printed http://127.0.0.1 URL (the dashboard), not Wealthsimple.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

import csvimport
import market
import model
import store

# --- constants (tradesimple WealthsimpleAPIBase) ---
OAUTH = "https://api.production.wealthsimple.com/v1/oauth/v2"
GRAPHQL = "https://my.wealthsimple.com/graphql"
GRAPHQL_VERSION = "12"
WS_CLIENT = "@wealthsimple/wealthsimple"
LOGIN_URL = "https://my.wealthsimple.com/app/login"


def _data_home():
    env = (os.environ.get("BAGHOLDER_HOME") or "").strip()
    if env:
        return Path(env)
    return Path.home() / ".bagholder"


HOME = _data_home()
SESSION_PATH = HOME / "session.json"
CLIENT_ID_PATH = HOME / "client_id"
UA_PATH = HOME / "user_agent"
TOKEN_CHECK_SEC = 30
TOKEN_REFRESH_MARGIN_SEC = 300
ACTIVITY_PULL_SEC = 24 * 60 * 60
PORTS = (8765, 8766, 8767)
DEBUG_PORTS = (18765, 18766, 18767)
CAPTURE_WAIT_SEC = 180
OAUTH_COOKIE = "_oauth2_access_v2"
DEVICE_COOKIE = "wssdi"

MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

Q_FETCH_ALL_ACCOUNT_FINANCIALS = """
query FetchAllAccountFinancials($identityId: ID!, $startDate: Date, $pageSize: Int = 25, $cursor: String) {
  identity(id: $identityId) {
    id
    ...AllAccountFinancials
    __typename
  }
}

fragment AllAccountFinancials on Identity {
  accounts(filter: {}, first: $pageSize, after: $cursor) {
    pageInfo {
      hasNextPage
      endCursor
      __typename
    }
    edges {
      cursor
      node {
        ...AccountWithFinancials
        __typename
      }
      __typename
    }
    __typename
  }
  __typename
}

fragment AccountWithFinancials on Account {
  ...AccountWithLink
  ...AccountFinancials
  __typename
}

fragment AccountWithLink on Account {
  ...Account
  linkedAccount {
    ...Account
    __typename
  }
  __typename
}

fragment Account on Account {
  ...AccountCore
  custodianAccounts {
    ...CustodianAccount
    __typename
  }
  __typename
}

fragment AccountCore on Account {
  id
  archivedAt
  branch
  closedAt
  createdAt
  cacheExpiredAt
  currency
  requiredIdentityVerification
  unifiedAccountType
  supportedCurrencies
  nickname
  status
  accountOwnerConfiguration
  accountFeatures {
    ...AccountFeature
    __typename
  }
  accountOwners {
    ...AccountOwner
    __typename
  }
  type
  __typename
}

fragment AccountFeature on AccountFeature {
  name
  enabled
  __typename
}

fragment AccountOwner on AccountOwner {
  accountId
  identityId
  accountNickname
  clientCanonicalId
  accountOpeningAgreementsSigned
  name
  email
  ownershipType
  activeInvitation {
    ...AccountOwnerInvitation
    __typename
  }
  sentInvitations {
    ...AccountOwnerInvitation
    __typename
  }
  __typename
}

fragment AccountOwnerInvitation on AccountOwnerInvitation {
  id
  createdAt
  inviteeName
  inviteeEmail
  inviterName
  inviterEmail
  updatedAt
  sentAt
  status
  __typename
}

fragment CustodianAccount on CustodianAccount {
  id
  branch
  custodian
  status
  updatedAt
  __typename
}

fragment AccountFinancials on Account {
  id
  custodianAccounts {
    id
    branch
    financials {
      current {
        ...CustodianAccountCurrentFinancialValues
        __typename
      }
      __typename
    }
    __typename
  }
  financials {
    currentCombined {
      id
      ...AccountCurrentFinancials
      __typename
    }
    __typename
  }
  __typename
}

fragment CustodianAccountCurrentFinancialValues on CustodianAccountCurrentFinancialValues {
  deposits { ...Money __typename }
  earnings { ...Money __typename }
  netDeposits { ...Money __typename }
  netLiquidationValue { ...Money __typename }
  withdrawals { ...Money __typename }
  __typename
}

fragment Money on Money {
  amount
  cents
  currency
  __typename
}

fragment AccountCurrentFinancials on AccountCurrentFinancials {
  id
  netLiquidationValue { ...Money __typename }
  netDeposits { ...Money __typename }
  simpleReturns(referenceDate: $startDate) { ...SimpleReturns __typename }
  totalDeposits { ...Money __typename }
  totalWithdrawals { ...Money __typename }
  __typename
}

fragment SimpleReturns on SimpleReturns {
  amount { ...Money __typename }
  asOf
  rate
  referenceDate
  __typename
}
""".strip()

Q_FETCH_ACTIVITY_FEED_ITEMS = """
query FetchActivityFeedItems($first: Int, $cursor: Cursor, $condition: ActivityCondition, $orderBy: [ActivitiesOrderBy!] = OCCURRED_AT_DESC) {
  activityFeedItems(
    first: $first
    after: $cursor
    condition: $condition
    orderBy: $orderBy
  ) {
    edges {
      node {
        ...Activity
        __typename
      }
      __typename
    }
    pageInfo {
      hasNextPage
      endCursor
      __typename
    }
    __typename
  }
}

fragment Activity on ActivityFeedItem {
  accountId
  aftOriginatorName
  aftTransactionCategory
  aftTransactionType
  amount
  amountSign
  assetQuantity
  assetSymbol
  canonicalId
  currency
  eTransferEmail
  eTransferName
  externalCanonicalId
  identityId
  institutionName
  occurredAt
  p2pHandle
  p2pMessage
  spendMerchant
  securityId
  billPayCompanyName
  billPayPayeeNickname
  redactedExternalAccountNumber
  opposingAccountId
  status
  subType
  type
  strikePrice
  contractType
  expiryDate
  chequeNumber
  provisionalCreditAmount
  primaryBlocker
  interestRate
  frequency
  counterAssetSymbol
  rewardProgram
  counterPartyCurrency
  counterPartyCurrencyAmount
  counterPartyName
  fxRate
  fees
  reference
  __typename
}
""".strip()

Q_FETCH_ACCOUNTS_WITH_BALANCE = """
query FetchAccountsWithBalance($ids: [String!]!, $type: BalanceType!) {
  accounts(ids: $ids) {
    ...AccountWithBalance
    __typename
  }
}

fragment AccountWithBalance on Account {
  id
  custodianAccounts {
    id
    financials {
      ... on CustodianAccountFinancialsSo {
        balance(type: $type) {
          ...Balance
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
  __typename
}

fragment Balance on Balance {
  quantity
  securityId
  __typename
}
""".strip()

Q_FETCH_SECURITY_SEARCH_RESULT = """
query FetchSecuritySearchResult($query: String!) {
  securitySearch(input: {query: $query}) {
    results {
      ...SecuritySearchResult
      __typename
    }
    __typename
  }
}

fragment SecuritySearchResult on Security {
  id
  buyable
  status
  stock {
    symbol
    name
    primaryExchange
    __typename
  }
  securityGroups {
    id
    name
    __typename
  }
  quoteV2 {
    ... on EquityQuote {
      marketStatus
      __typename
    }
    __typename
  }
  __typename
}
""".strip()


Q_IDENTITY_HISTORICAL_FINANCIALS = """
query IdentityHistoricalFinancialsQuery(
  $identityId: ID!
  $currency: Currency!
  $startDate: Date!
  $endDate: Date
  $limit: Int
  $cursor: String
  $includeNetDeposits: Boolean = true
) {
  identity(id: $identityId) {
    id
    financials(filter: { archived: false }) {
      historicalDaily(
        currency: $currency
        startDate: $startDate
        endDate: $endDate
        first: $limit
        after: $cursor
      ) {
        edges {
          cursor
          node {
            date
            netLiquidationValue { amount currency __typename }
            netDeposits @include(if: $includeNetDeposits) { amount currency __typename }
            __typename
          }
          __typename
        }
        pageInfo {
          endCursor
          hasNextPage
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
""".strip()

Q_FETCH_ACCOUNT_HISTORICAL_FINANCIALS = """
query FetchAccountHistoricalFinancials(
  $id: ID!
  $currency: Currency!
  $startDate: Date
  $resolution: DateResolution!
  $endDate: Date
  $first: Int
  $cursor: String
) {
  account(id: $id) {
    id
    financials {
      historicalDaily(
        currency: $currency
        startDate: $startDate
        resolution: $resolution
        endDate: $endDate
        first: $first
        after: $cursor
      ) {
        edges {
          node {
            date
            netLiquidationValueV2 { amount currency __typename }
            netDepositsV2 { amount currency __typename }
            __typename
          }
          __typename
        }
        pageInfo {
          hasNextPage
          endCursor
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
""".strip()

Q_FETCH_SECURITY = """
query FetchSecurity($securityId: ID!) {
  security(id: $securityId) {
    id
    currency
    stock { name primaryExchange primaryMic symbol }
    optionDetails { underlyingSecurity { id currency } }
    __typename
  }
}
""".strip()


Q_FETCH_SECURITIES = """
query FetchSecurities($ids: [ID!]!) {
  securities(ids: $ids) {
    id
    currency
    stock { name primaryExchange primaryMic symbol }
    optionDetails { underlyingSecurity { id currency } }
    __typename
  }
}
""".strip()

SECURITY_BATCH = 50

# Versions are GitHub releases tagged vMAJOR.MINOR.PATCH. APP_VERSION is bumped in
# the commit that a release is cut from; once a day the app asks GitHub for the
# latest release and shows an update link when that tag is newer than this copy.
# Commits without a release never trigger it.
APP_VERSION = "1.8.0"
REPO = "ProfessorBagholder/Bagholder"
REPO_URL = "https://github.com/" + REPO
RELEASE_URL = "https://api.github.com/repos/" + REPO + "/releases/latest"
RELEASE_TAG_URL = "https://api.github.com/repos/" + REPO + "/releases/tags/%s"
# In-app update: the running server is a child of a small supervisor (see
# supervise). An update swaps the files, then the child exits with RESTART_CODE
# and the supervisor starts it again in the same console, on the same port.
RESTART_CODE = 3
APP_DIR = Path(__file__).resolve().parent
UPDATE_HEALTHY_SEC = 20          # a restarted server alive this long is a good update
UPDATE_MAX_BYTES = 50 * 1024 * 1024
UPDATE_CHECK_HOURS = 1   # a release is a click away now, so the check is hourly and at every start
# A copy in a container (the Dockerfile): bound to every interface of the container while
# compose publishes it on the host's loopback only, and never installing a release into
# itself, since a new release is a new image; it still checks for one and says so in the
# header, where the pull command stands in for the Update button. Both empty on a desktop.
BIND_HOST = (os.environ.get("BAGHOLDER_BIND") or "").strip() or "127.0.0.1"
UPDATES_OFF = bool((os.environ.get("BAGHOLDER_NO_UPDATE") or "").strip())
UPDATES_OFF_MESSAGE = "This copy is updated with docker compose pull; a new release is a new image."

# Bumped whenever the page and the server change together. The page compares it
# with what /api/status reports and tells the user to restart when they differ.
PROTOCOL = "2026-09-09.3"
STARTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

Q_FETCH_ACCOUNT_MARGIN_BUYING_POWER = """
query FetchAccountCurrentMarginBuyingPowerV2($accountId: ID!, $currency: Currency = CAD) {
  account(id: $accountId) {
    id
    financials {
      current {
        id
        marginV3 {
          trading {
            buyingPower(asCurrency: $currency) {
              __typename
              ... on BuyingPowerMetricAvailable {
                total { amount currency __typename }
                __typename
              }
              ... on BuyingPowerMetricUnavailable {
                reason {
                  __typename
                  ... on UnavailableSecurities {
                    securities { securityId status __typename }
                    __typename
                  }
                }
                __typename
              }
            }
            __typename
          }
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
""".strip()

QUERIES = {
    "FetchAccountCurrentMarginBuyingPowerV2": Q_FETCH_ACCOUNT_MARGIN_BUYING_POWER,
    "FetchSecurities": Q_FETCH_SECURITIES,
    "IdentityHistoricalFinancialsQuery": Q_IDENTITY_HISTORICAL_FINANCIALS,
    "FetchAccountHistoricalFinancials": Q_FETCH_ACCOUNT_HISTORICAL_FINANCIALS,
    "FetchAllAccountFinancials": Q_FETCH_ALL_ACCOUNT_FINANCIALS,
    "FetchActivityFeedItems": Q_FETCH_ACTIVITY_FEED_ITEMS,
    "FetchAccountsWithBalance": Q_FETCH_ACCOUNTS_WITH_BALANCE,
    "FetchSecuritySearchResult": Q_FETCH_SECURITY_SEARCH_RESULT,
    "FetchSecurity": Q_FETCH_SECURITY,
}

SKIP_TYPE_MARKERS = (
    "SHARE_LENDING",
    "SHARELENDING",
    "STOCK_LENDING",
    "STOCKLENDING",
)


def _num(v, default=0.0):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _s(v):
    if v is None:
        return ""
    return str(v)


def _upper(v):
    return _s(v).strip().upper()


def _compact(v):
    return re.sub(r"[\s_\-]+", "", _upper(v))


def _date_only(occurred):
    s = _s(occurred).strip()
    if not s:
        return ""
    if "T" in s:
        s = s.split("T", 1)[0]
    return s[:10]


def _asset_symbol(item):
    raw = _s(item.get("assetSymbol")).strip()
    if raw.upper().startswith("EXCHANGE:"):
        raw = raw.split(":", 1)[-1]
    return raw.upper().strip()


# Fills that hit the cash book. Everything else (pending limits, cancelled,
# submitted, working) is not a trade.
_KEEP_STATUS = (
    "POSTED",
    "COMPLETED",
    "SETTLED",
    "COMPLETE",
    "FILLED",
    "EXECUTED",
    "PROCESSED",
    "CONFIRMED",
    "BOOKED",
    "SUCCEEDED",
    "SUCCESS",
)

_CORP_BLOBS = (
    "STKDIS",
    "STOCKDISTRIBUTION",
    "STOCKDIV",
    "SPINOFF",
    "SPIN",
    "DIVIDENDINKIND",
    "INKIND",
    "CORPORATEACTION",
    "CODECHANGE",
    "SYMBOLCHANGE",
    "TICKERCHANGE",
    "LISTINGSTATUS",
    "SECURITYSWAP",
    "MANDATORYEXCHANGE",
    "NAMECHANGE",
)


def _type_blob(item):
    typ = _upper(item.get("type")).replace("-", "_")
    sub = _upper(item.get("subType")).replace("-", "_")
    blob = "_".join(
        _compact(x)
        for x in (
            typ,
            sub,
            item.get("aftTransactionType"),
            item.get("aftTransactionCategory"),
        )
        if x
    )
    return typ, sub, blob


def _is_corp_share_move(item):
    typ, sub, blob = _type_blob(item)
    if any(k in blob for k in _CORP_BLOBS):
        return True
    # In-kind / spin-in: a dividend (or distribution) that delivers shares, not cash.
    qty = abs(_num(item.get("assetQuantity")))
    cash = abs(_num(item.get("amount")))
    if qty and _asset_symbol(item) and cash == 0 and (
        "DIVIDEND" in _compact(typ) or "DISTRIBUT" in blob
    ):
        return True
    return False


def _is_code_change(item):
    _, _, blob = _type_blob(item)
    return any(
        k in blob
        for k in (
            "CODECHANGE",
            "SYMBOLCHANGE",
            "TICKERCHANGE",
            "LISTINGSTATUS",
            "SECURITYSWAP",
            "MANDATORYEXCHANGE",
            "NAMECHANGE",
        )
    )


def set_home(path):
    """Point session + SQLite paths at a directory (used by tests)."""
    global HOME, SESSION_PATH, CLIENT_ID_PATH, UA_PATH, _refused_refresh_token
    HOME = Path(path)
    _refused_refresh_token = None
    SESSION_PATH = HOME / "session.json"
    CLIENT_ID_PATH = HOME / "client_id"
    UA_PATH = HOME / "user_agent"
    store.set_home(HOME)


def skip_activity(item):
    """True when this GraphQL row should not be stored."""
    if not item:
        return True
    if not _s(item.get("occurredAt")).strip():
        return True
    status = _compact(item.get("status"))
    typ, sub, blob = _type_blob(item)
    # Corporate actions often land as processed / empty, not posted.
    if _is_corp_share_move(item):
        if any(x in status for x in ("REJECT", "CANCEL", "FAIL", "VOID")):
            return True
    elif typ in ("DIVIDEND", "INTEREST_CHARGE") and not status:
        # Cash dividends and margin interest charges often arrive with no
        # status at all; both have already hit the cash balance.
        pass
    elif not status or status not in _KEEP_STATUS:
        return True
    # INTEREST / FPL_INTEREST must not be treated as a loan skip.
    if typ in ("LOAN", "RECALL") or sub in ("LOAN", "RECALL"):
        return True
    if typ.endswith("_LOAN") or sub.endswith("_LOAN"):
        return True
    if typ.endswith("_RECALL") or sub.endswith("_RECALL"):
        return True
    for marker in SKIP_TYPE_MARKERS:
        if marker in blob:
            return True
    if "SHARE_LENDING" in blob or "SHARELENDING" in blob:
        return True
    return False


def option_symbol(item):
    """OCC-ish display so an option rolls into the underlying ticker."""
    under = _asset_symbol(item)
    contract = item.get("contractType")
    strike = item.get("strikePrice")
    expiry = item.get("expiryDate")
    if not (contract and strike is not None and expiry and under):
        return under
    ds = _s(expiry).strip()
    if "T" in ds:
        ds = ds.split("T", 1)[0]
    parts = ds.replace("/", "-")[:10].split("-")
    if len(parts) != 3:
        return under
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        mon = MONTHS[month - 1]
    except (ValueError, IndexError):
        return under
    yy = f"{year % 100:02d}"
    dd = f"{day:02d}"
    try:
        strike_f = float(strike)
    except (TypeError, ValueError):
        return under
    strike_s = f"{strike_f:.2f}"
    cp = _upper(contract)
    if cp in ("C", "CALL"):
        cp = "CALL"
    elif cp in ("P", "PUT"):
        cp = "PUT"
    return f"{under} {dd}{mon}{yy} {strike_s} {cp}"


def signed_cash(item):
    """Ledger cash: buys/withdrawals/source transfers negative; sells/deposits/income positive."""
    amount = abs(_num(item.get("amount")))
    typ = _upper(item.get("type")).replace("-", "_")
    sub = _upper(item.get("subType")).replace("-", "_")
    if typ in ("DIY_BUY", "OPTIONS_BUY", "WITHDRAWAL") or (
        typ == "INTERNAL_TRANSFER" and "SOURCE" in sub
    ):
        return -amount
    if typ in (
        "DIY_SELL",
        "OPTIONS_SELL",
        "DEPOSIT",
        "CONTRIBUTION",
        "DIVIDEND",
        "INTEREST",
    ) or (typ == "INTERNAL_TRANSFER" and "DESTINATION" in sub):
        return amount
    sign = _s(item.get("amountSign")).strip().lower()
    if sign in ("negative", "debit", "-", "neg"):
        return -amount
    if sign in ("positive", "credit", "+", "pos"):
        return amount
    raw = item.get("amount")
    if raw is None or raw == "":
        return 0.0
    return _num(raw)


def _account_type(account_id, accounts):
    if not accounts:
        return ""
    rec = None
    if isinstance(accounts, dict):
        rec = accounts.get(account_id) or accounts.get(_s(account_id))
    else:
        for a in accounts:
            if isinstance(a, dict) and _s(a.get("id")) == _s(account_id):
                rec = a
                break
    if not rec or not isinstance(rec, dict):
        return ""
    return _s(rec.get("nickname") or rec.get("unifiedAccountType") or rec.get("type"))


def nav_account_groups(accounts):
    """Filter nickname -> Wealthsimple account ids. CAD+USD with the same nickname share a group."""
    if isinstance(accounts, dict):
        recs = [v for v in accounts.values() if isinstance(v, dict)]
    else:
        recs = [a for a in (accounts or []) if isinstance(a, dict)]
    groups = {}
    for acc in recs:
        aid = _s(acc.get("id")).strip()
        if not aid:
            continue
        nick = _s(acc.get("nickname") or acc.get("unifiedAccountType") or acc.get("type")).strip()
        if not nick:
            continue
        bucket = groups.setdefault(nick, [])
        if aid not in bucket:
            bucket.append(aid)
    return groups


def fifo_pool_ids(accounts):
    """CAD + USD sides of the same Wealthsimple account share one FIFO book.

    Linked pairs (linkedAccount) and matching nicknames with CAD/USD collapse
    to one root id. Distinct nicknames stay separate.
    """
    recs = []
    if isinstance(accounts, dict):
        recs = [v for v in accounts.values() if isinstance(v, dict)]
    else:
        recs = [a for a in (accounts or []) if isinstance(a, dict)]
    parent = {}

    def find(x):
        x = str(x)
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        a, b = _s(a), _s(b)
        if not a or not b:
            return
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_nick = {}
    for a in recs:
        aid = _s(a.get("id"))
        if not aid:
            continue
        find(aid)
        linked = a.get("linkedAccount") if isinstance(a.get("linkedAccount"), dict) else {}
        lid = _s(linked.get("id"))
        if lid:
            union(aid, lid)
        nick = _s(a.get("nickname")).strip()
        if nick:
            by_nick.setdefault(nick, []).append(aid)
    for ids in by_nick.values():
        root = ids[0]
        for other in ids[1:]:
            union(root, other)
    return {aid: find(aid) for aid in list(parent)}


def _is_option(item):
    return bool(item.get("contractType"))


def _is_to_close(sub):
    c = _compact(sub)
    return "TOCLOSE" in c or c in ("BTC", "STC", "BUYTOCLOSE", "SELLTOCLOSE")


def _human_desc(item, typ, sub, symbol, qty, px, cash):
    t = _upper(typ).replace("-", "_")
    s = _upper(sub).replace("-", "_")
    if t == "DIY_BUY" or (t == "TRADE" and _compact(sub) in ("BUY", "BUYTOOPEN", "BUYTOCLOSE")):
        verb = "Buy to close" if "CLOSE" in _compact(sub) else ("Buy to open" if "OPEN" in _compact(sub) else "Buy")
        if qty and px:
            return f"{verb} {qty:g} {symbol} @ {px:g}"
        return f"{verb} {symbol}".strip()
    if t == "DIY_SELL" or (t == "TRADE" and "SELL" in _compact(sub)):
        verb = "Sell to close" if "CLOSE" in _compact(sub) else ("Sell to open" if "OPEN" in _compact(sub) else "Sell")
        if qty and px:
            return f"{verb} {abs(qty):g} {symbol} @ {px:g}"
        return f"{verb} {symbol}".strip()
    if t in ("DEPOSIT", "CONTRIBUTION"):
        return "Deposit"
    if t == "WITHDRAWAL":
        return "Withdrawal"
    if t == "INTERNAL_TRANSFER":
        return "Transfer out" if "SOURCE" in s else "Transfer in"
    if t == "DIVIDEND":
        return f"Dividend: {symbol}" if symbol else "Dividend"
    if t == "INTEREST":
        if "FPL" in s:
            return "Stock Lending Earnings"
        return "Interest"
    if t == "FUNDS_CONVERSION":
        return "Funds conversion"
    if t in ("FEE", "REFUND"):
        return "Fee refund" if t == "REFUND" else "Fee"
    if t in ("STOCK_DISTRIBUTION", "STKDIS", "SPIN", "SPINOFF"):
        return f"Stock distribution: {symbol}" if symbol else "Stock distribution"
    if (
        t in ("EXPIR", "EXPIRY", "EXPIRE", "ASSIGN", "ASSIGNMENT", "EXERCISE")
        or "EXPIR" in t
        or "ASSIGN" in t
        or "EXERCISE" in t
    ):
        label = "Assign" if "ASSIGN" in t else ("Exercise" if "EXERCISE" in t else "Expir")
        return f"{label} {symbol}".strip()
    if symbol:
        return f"{t}: {symbol}"
    return t.replace("_", " ").title() or "Activity"


def _counter_symbol(item):
    raw = _s(item.get("counterAssetSymbol")).strip()
    if raw.upper().startswith("EXCHANGE:"):
        raw = raw.split(":", 1)[-1]
    return raw.upper().strip()


def map_activity_rows(item, accounts=None):
    """One GraphQL row may become two when a code change names a different ticker."""
    if not item:
        return []
    src = _asset_symbol(item)
    dst = _counter_symbol(item)
    qty = abs(_num(item.get("assetQuantity")))
    if src and dst and src != dst and qty and _is_corp_share_move(item):
        cid = _s(item.get("canonicalId")).strip() or "swap"
        outgoing = dict(item)
        outgoing["assetSymbol"] = src
        outgoing["counterAssetSymbol"] = ""
        outgoing["type"] = "STKDIS"
        outgoing["subType"] = "STKDIS"
        outgoing["assetQuantity"] = -qty
        outgoing["amount"] = 0
        outgoing["amountSign"] = "negative"
        outgoing["canonicalId"] = cid + ":out"
        incoming = dict(item)
        incoming["assetSymbol"] = dst
        incoming["counterAssetSymbol"] = ""
        incoming["type"] = "STKDIS"
        incoming["subType"] = "STKDIS"
        incoming["assetQuantity"] = qty
        incoming["amount"] = 0
        incoming["amountSign"] = "positive"
        incoming["canonicalId"] = cid + ":in"
        rows = [map_activity(outgoing, accounts), map_activity(incoming, accounts)]
        return [r for r in rows if r]
    row = map_activity(item, accounts)
    return [row] if row else []


def map_activity(item, accounts=None):
    """GraphQL ActivityFeedItem -> ledger activity object. None if skipped."""
    if skip_activity(item):
        return None
    occurred = _s(item.get("occurredAt")).strip()
    transaction_date = _date_only(occurred)
    if not transaction_date:
        return None
    # Keep Wealthsimple date and time. transactionDate stays the calendar day
    # for FIFO / filters that compare YYYY-MM-DD.
    account_id = _s(item.get("accountId"))
    typ = _upper(item.get("type")).replace("-", "_")
    sub = _upper(item.get("subType")).replace("-", "_")
    qty_raw = _num(item.get("assetQuantity"))
    qty_abs = abs(qty_raw)
    cash = signed_cash(item)
    amount_abs = abs(_num(item.get("amount")))
    fees = abs(_num(item.get("fees")))
    is_opt = _is_option(item)
    symbol = option_symbol(item) if is_opt else _asset_symbol(item)

    cur = _upper(item.get("currency"))
    if cur not in ("CAD", "USD"):
        cur = "USD" if is_opt else "CAD"

    unit_price = 0.0
    if qty_abs:
        # WS option `amount` is full contract cash (per-share × 100 × contracts).
        if is_opt:
            unit_price = amount_abs / (qty_abs * 100.0)
        else:
            unit_price = amount_abs / qty_abs

    activity_type = "Other"
    activity_sub = sub or typ
    category = "other"
    quantity = qty_abs

    if typ == "DIY_BUY":
        category = "trade"
        if is_opt:
            if _is_to_close(sub):
                activity_type, activity_sub = "Trade", "BUYTOCLOSE"
            else:
                activity_type, activity_sub = "Trade", "BUYTOOPEN"
        else:
            activity_type, activity_sub = "Trade", "BUY"
        quantity = abs(qty_abs)
    elif typ == "DIY_SELL":
        category = "trade"
        if is_opt:
            if _is_to_close(sub):
                activity_type, activity_sub = "Trade", "SELLTOCLOSE"
            else:
                activity_type, activity_sub = "Trade", "SELLTOOPEN"
        else:
            activity_type, activity_sub = "Trade", "SELL"
        quantity = -abs(qty_abs)
    elif typ == "OPTIONS_BUY":
        category = "trade"
        if _is_to_close(sub):
            activity_type, activity_sub = "OPTIONS_BUY", "BUYTOCLOSE"
        else:
            activity_type, activity_sub = "OPTIONS_BUY", "BUYTOOPEN"
        quantity = abs(qty_abs)
    elif typ == "OPTIONS_SELL":
        category = "trade"
        if _is_to_close(sub):
            activity_type, activity_sub = "OPTIONS_SELL", "SELLTOCLOSE"
        else:
            activity_type, activity_sub = "OPTIONS_SELL", "SELLTOOPEN"
        quantity = -abs(qty_abs)
    elif "MULTILEG" in typ:
        # WS filled combo / roll legs often have null assetQuantity.
        # Credit is covered-call premium: sell-to-open a short, not close a long.
        # Debit prefers BUYTOCLOSE; FIFO opens LONG if no short exists.
        category = "trade"
        if cash < 0:
            activity_type, activity_sub = "OPTIONS_BUY", "BUYTOCLOSE"
            quantity = abs(qty_abs)
        else:
            activity_type, activity_sub = "OPTIONS_SELL", "SELLTOOPEN"
            quantity = -abs(qty_abs) if qty_abs else 0.0
    elif (
        typ in ("EXPIR", "EXPIRY", "EXPIRE", "ASSIGN", "ASSIGNMENT", "EXERCISE")
        or "EXPIR" in typ
        or "ASSIGN" in typ
        or "EXERCISE" in typ
    ):
        category = "option_event"
        keep = "ASSIGN" if "ASSIGN" in typ else ("EXERCISE" if "EXERCISE" in typ else "EXPIR")
        activity_type = keep
        short_expir = "SHORT_EXPIR" in typ or ("SHORT" in typ and "EXPIR" in typ)
        if "ASSIGN" in typ:
            activity_sub = "BUYTOCLOSE"
        elif short_expir:
            activity_sub = "BUY"
        elif "EXPIR" in typ:
            activity_sub = "SELL"
        elif "COVER" in _compact(sub) or _is_to_close(sub):
            activity_sub = "BUY"
        else:
            activity_sub = "SELL"
        quantity = -abs(qty_abs) if activity_sub == "SELL" else abs(qty_abs)
        # Strike cash on ASSIGN is share delivery, not option buyback.
        if "ASSIGN" in typ or abs(cash) < 1e-12:
            unit_price = 0.0
        if not is_opt:
            symbol = symbol or _asset_symbol(item)
    elif typ in ("DEPOSIT", "CONTRIBUTION"):
        activity_type, activity_sub, category = "Deposit", "deposit", "deposit"
    elif typ == "WITHDRAWAL":
        activity_type, activity_sub, category = "Withdrawal", "withdrawal", "withdrawal"
    elif typ == "INTERNAL_TRANSFER" or _compact(typ) in (
        "TRFIN",
        "TRFOUT",
        "TRANSFERIN",
        "TRANSFEROUT",
        "INTERNALTRANSFER",
    ):
        # Share TRFIN/TRFOUT are custody moves, not sells.
        activity_type, activity_sub, category = "Transfer", "transfer", "transfer"
    elif typ == "DIVIDEND" and not _is_corp_share_move(item):
        activity_type, activity_sub, category = "Dividend", "dividend", "dividend"
    elif typ == "INTEREST" or "FPL_INTEREST" in sub or _compact(typ) == "FPLINTEREST":
        activity_type, activity_sub, category = "Interest", "interest", "interest"
    elif typ == "FUNDS_CONVERSION":
        activity_type, activity_sub, category = "FxExchange", "fx", "fx"
    elif typ in ("FEE", "REFUND"):
        activity_type = "Refund" if typ == "REFUND" else "Fee"
        activity_sub, category = "fee", "fee"
    elif _is_corp_share_move(item) or (
        typ in ("STOCK_DISTRIBUTION", "STKDIS", "SPIN", "SPINOFF", "STK_DIS")
        or "STKDIS" in _compact(typ)
        or "STOCKDISTRIBUTION" in _compact(typ)
        or "STOCKDISTRIBUTION" in _compact(sub)
    ):
        # Name-change is -N then +N of the same ticker.
        # foldStkdis nets SELL against BUY. Unsigned qty would open 2N at $0.
        # Leftover +N opens at $0 so a later sell has lots.
        activity_type, category = "STKDIS", "trade"
        unit_price = 0.0
        sign = _s(item.get("amountSign")).strip().lower()
        # A lone international code change names the old ticker with +qty.
        # Those shares were replaced, not bought.
        outgoing = qty_raw < 0 or sign in ("negative", "debit", "-", "neg")
        if (
            not outgoing
            and _is_code_change(item)
            and not _counter_symbol(item)
            and "STKDIS" not in _compact(item.get("type"))
        ):
            outgoing = True
        if outgoing:
            activity_sub = "SELL"
            quantity = -qty_abs
        else:
            activity_sub = "BUY"
            quantity = qty_abs
    else:
        activity_type = (item.get("type") or "Other")
        activity_sub = item.get("subType") or "other"
        category = "other"

    if activity_sub in ("SELL", "SELLTOOPEN", "SELLTOCLOSE"):
        quantity = -abs(qty_abs) if qty_abs else quantity

    sign = _s(item.get("amountSign")).strip().lower()
    direction = ""
    if sign in ("negative", "debit", "-", "neg") or cash < 0:
        direction = "DEBIT"
    elif sign in ("positive", "credit", "+", "pos") or cash > 0:
        direction = "CREDIT"

    cid = _s(item.get("canonicalId")).strip()
    if store.looks_like_homemade_id(cid):
        cid = ""

    desc = _human_desc(item, typ, sub, symbol, quantity, unit_price, cash)
    name = _s(item.get("aftOriginatorName") or item.get("institutionName") or symbol)

    return {
        "canonicalId": cid or None,
        "occurredAt": occurred,
        "transactionDate": transaction_date,
        "settlementDate": transaction_date,
        "accountId": account_id,
        "bookId": account_id,
        "fifoId": fifo_pool_ids(accounts).get(account_id, account_id) if accounts else account_id,
        "accountType": _account_type(account_id, accounts),
        "activityType": activity_type,
        "activitySubType": activity_sub,
        "description": desc,
        "direction": direction,
        "symbol": symbol,
        "name": name,
        "currency": cur,
        "quantity": quantity,
        "unitPrice": unit_price,
        "commission": fees,
        "netCashAmount": cash,
        "category": category,
        "balance": None,
        "source": "wealthsimple",
        "rawType": _s(item.get("type")),
        "aftType": _s(item.get("aftTransactionType")),
        "counterSymbol": _counter_symbol(item),
        "securityId": _s(item.get("securityId")).strip() or None,
    }


# --- runtime (not executed on import) ---

_lock = threading.RLock()
_state = {
    "connected": False,
    "capturing": False,
    "syncing": False,
    "syncStep": "",
    "email": "",
    "lastSync": "",
    "error": "",
    "chrome_proc": None,
    "login_attempt": 0,
    "updating": "",
    "updateError": "",
    "listingsFilling": False,
}
_stop = threading.Event()
_httpd = None
_exit_code = [0]


def _ensure_home():
    HOME.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(HOME, 0o700)
    except OSError:
        pass


def _atomic_write(path: Path, data: bytes, mode=0o600):
    _ensure_home()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, mode)
    tmp.replace(path)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def load_session():
    with _lock:
        if not SESSION_PATH.exists():
            return None
        try:
            return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def save_session(sess):
    with _lock:
        _atomic_write(SESSION_PATH, json.dumps(sess, indent=2).encode("utf-8"), 0o600)


def delete_session_and_book():
    """Drop the login session only. Stored activity rows stay in SQLite."""
    global _refused_refresh_token
    _refused_refresh_token = None
    with _lock:
        try:
            SESSION_PATH.unlink()
        except OSError:
            pass
        _state["connected"] = False
        _state["email"] = ""
        _state["lastSync"] = ""
        _state["capturing"] = False
        _state["error"] = ""


def load_book():
    store.ensure()
    return store.snapshot()


def save_accounts_snapshot(book):
    """Write accounts / balances / NAV. Never rebuilds the activity table."""
    store.replace_accounts(book.get("accounts") or [])
    store.replace_balances(book.get("balances") or [])
    if "margin" in book:
        store.replace_margin(book.get("margin") or [])
    store.upsert_nav(book.get("navHistory") or [])
    if book.get("syncedAt"):
        store.set_meta("synced_at", book["syncedAt"])



_SSL_CTX = None

def _ssl_context():
    global _SSL_CTX
    if _SSL_CTX is not None:
        return _SSL_CTX
    ca_files = []
    try:
        import certifi
        where = certifi.where()
        if where:
            ca_files.append(where)
    except Exception:
        pass
    ca_files.extend((
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
        "/opt/homebrew/etc/openssl@1.1/cert.pem",
    ))
    for path in ca_files:
        if path and os.path.isfile(path):
            try:
                _SSL_CTX = ssl.create_default_context(cafile=path)
                return _SSL_CTX
            except Exception:
                continue
    _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


_GZIP_MAGIC = b"\x1f\x8b"


def _http_body_text(raw, headers=None):
    """Decode HTTP body bytes. Decompress gzip when the payload is still compressed."""
    if not raw:
        return ""
    encoding = ""
    if headers is not None:
        try:
            encoding = (headers.get("Content-Encoding") or "").strip().lower()
        except Exception:
            encoding = ""
    gzip_magic = raw.startswith(_GZIP_MAGIC)
    # urllib may leave gzip bodies compressed. Magic bytes are the reliable check;
    # Content-Encoding alone is not enough, and must not cause a second decompress.
    if gzip_magic or (encoding == "gzip" and gzip_magic):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw.decode("utf-8", "replace")


def _http_json(method, url, body=None, headers=None, timeout=60):
    hdrs = {
        "Accept": "application/json",
    }
    ua = cached_user_agent()
    if ua:
        hdrs["User-Agent"] = ua
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read()
            text = _http_body_text(raw, getattr(resp, "headers", None))
            if not text:
                return {}
            try:
                return json.loads(text)
            except ValueError:
                return {
                    "error": "invalid_json",
                    "_http_status": getattr(resp, "status", None) or 200,
                }
    except HTTPError as e:
        raw = e.read() if e.fp else b""
        text = _http_body_text(raw, getattr(e, "headers", None))
        parsed = None
        try:
            parsed = json.loads(text) if text else {}
        except ValueError:
            parsed = {"error": "http_%s" % e.code}
        parsed = parsed or {}
        parsed["_http_status"] = e.code
        return parsed


def cached_client_id():
    if CLIENT_ID_PATH.exists():
        try:
            v = CLIENT_ID_PATH.read_text(encoding="utf-8").strip()
            if v:
                return v
        except OSError:
            pass
    return ""


def save_client_id(cid):
    if not cid:
        return
    _ensure_home()
    try:
        CLIENT_ID_PATH.write_text(cid, encoding="utf-8")
        os.chmod(CLIENT_ID_PATH, 0o600)
    except OSError:
        pass


def cached_user_agent():
    sess = load_session() or {}
    v = _s(sess.get("user_agent")).strip()
    if v:
        return v
    if UA_PATH.exists():
        try:
            v = UA_PATH.read_text(encoding="utf-8").strip()
            if v:
                return v
        except OSError:
            pass
    return ""


def save_user_agent(ua):
    if not ua:
        return
    _ensure_home()
    try:
        UA_PATH.write_text(ua, encoding="utf-8")
        os.chmod(UA_PATH, 0o600)
    except OSError:
        pass


def scrape_client_id():
    """Production clientId from Wealthsimple login JS. Empty if it cannot be read."""
    cached = cached_client_id()
    if cached:
        return cached
    try:
        hdrs = {}
        ua = cached_user_agent()
        if ua:
            hdrs["User-Agent"] = ua
        req = Request(LOGIN_URL, headers=hdrs)
        with urlopen(req, timeout=20, context=_ssl_context()) as resp:
            html = _http_body_text(resp.read(), getattr(resp, "headers", None))
        m = re.search(r'<script[^>]+src="([^"]*app-[a-f0-9]+\.js[^"]*)"', html, re.I)
        if not m:
            return ""
        js_url = m.group(1)
        if js_url.startswith("//"):
            js_url = "https:" + js_url
        elif js_url.startswith("/"):
            js_url = "https://my.wealthsimple.com" + js_url
        req2 = Request(js_url, headers=hdrs)
        with urlopen(req2, timeout=20, context=_ssl_context()) as resp:
            js = _http_body_text(resp.read(), getattr(resp, "headers", None))
        m2 = re.search(r'production:.*?clientId:"([a-f0-9]+)"', js, re.S)
        if m2:
            save_client_id(m2.group(1))
            return m2.group(1)
    except Exception:
        pass
    return ""


def client_id_for(sess):
    """Session or cached file only. Do not scrape at refresh time."""
    if sess and sess.get("client_id"):
        save_client_id(sess["client_id"])
        return sess["client_id"]
    return cached_client_id()


def _ws_session_headers(sess, headers):
    headers = dict(headers)
    if sess and sess.get("wssdi"):
        headers["x-ws-device-id"] = sess["wssdi"]
    if sess and sess.get("session_id"):
        headers["x-ws-session-id"] = sess["session_id"]
    return headers


def _set_public_error(msg):
    with _lock:
        _state["error"] = msg or ""


def _oauth_error_code(data):
    """Short OAuth `error` field only. Never tokens, client_id values, or raw bodies."""
    err = (data or {}).get("error")
    if not isinstance(err, str):
        return ""
    err = err.strip()
    if not err:
        return ""
    if re.fullmatch(r"[a-f0-9]{32,}", err, re.I):
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", err):
        return ""
    return _public_sync_error(err)


REFUSED_LOGIN_MESSAGE = "Saved login refused. Connect Wealthsimple again."


def _refresh_failure_message(data):
    status = (data or {}).get("_http_status")
    oauth_err = _oauth_error_code(data)
    if oauth_err == "invalid_grant":
        return REFUSED_LOGIN_MESSAGE
    parts = []
    if status:
        parts.append("Wealthsimple token refresh HTTP %s" % status)
    if oauth_err:
        parts.append(oauth_err)
    return " ".join(parts) if parts else "Wealthsimple token refresh failed"


def _expires_at_as_timestamp(data):
    """Store Wealthsimple expiry as the same timestamp string the cookie uses."""
    raw = (data or {}).get("expires_at")
    if isinstance(raw, str) and "T" in raw.strip():
        return raw.strip()
    unix = None
    if isinstance(raw, (int, float)):
        unix = float(raw)
    elif data and data.get("expires_in") is not None:
        unix = time.time() + int(data["expires_in"])
    if unix is None:
        return None
    dt = datetime.fromtimestamp(unix, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


_refresh_lock = threading.Lock()
_refused_refresh_token = None  # a token Wealthsimple answered invalid_grant to; never posted again this run


def refresh_session(sess, adopt=True):
    """refresh_token grant. Do not send Authorization.

    Wealthsimple rotates the refresh token on every grant, so two threads
    posting the same token would leave the loser with invalid_grant and the
    login dead. Refreshes run one at a time; under the lock the session on
    disk is read again and, when another thread has rotated it meanwhile,
    that session is adopted and nothing is posted. A caller holding a login
    newer than the file (a capture) passes adopt=False."""
    rt = (sess or {}).get("refresh_token")
    if not rt:
        _set_public_error("missing refresh token")
        return False
    with _refresh_lock:
        if adopt:
            current = load_session() or {}
            if current.get("access_token") and current.get("refresh_token") and current.get("refresh_token") != rt:
                sess.update(current)
                return True
        if rt == _refused_refresh_token:
            _set_public_error(REFUSED_LOGIN_MESSAGE)
            return False
        return _refresh_session_locked(sess, rt)


def _refresh_session_locked(sess, rt):
    cid = client_id_for(sess)
    if not cid:
        _set_public_error("session has no client id")
        return False
    body = {
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": cid,
    }
    headers = _ws_session_headers(
        sess,
        {
            "x-wealthsimple-client": WS_CLIENT,
            "x-ws-profile": "invest",
        },
    )
    data = _http_json("POST", OAUTH + "/token", body, headers)
    if not data or not data.get("access_token"):
        if _oauth_error_code(data) == "invalid_grant":
            global _refused_refresh_token
            _refused_refresh_token = rt
        _set_public_error(_refresh_failure_message(data))
        return False
    sess["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        sess["refresh_token"] = data["refresh_token"]
    stamped = _expires_at_as_timestamp(data)
    if stamped:
        sess["expires_at"] = stamped
    sess["client_id"] = cid
    save_session(sess)
    return True


def token_info(sess):
    token = (sess or {}).get("access_token")
    if not token:
        return {}
    headers = _ws_session_headers(
        sess,
        {
            "Authorization": "Bearer " + token,
            "x-wealthsimple-client": WS_CLIENT,
        },
    )
    data = _http_json("GET", OAUTH + "/token/info", None, headers)
    if data and data.get("_http_status") in (401, 403):
        return {}
    return data or {}


def client_id_from_token_info(info):
    """OAuth application uid that issued these tokens. Unofficial token/info shape."""
    if not isinstance(info, dict):
        return ""
    uid = info.get("application_uid")
    if uid:
        return str(uid).strip()
    app = info.get("application")
    if isinstance(app, dict) and app.get("uid"):
        return str(app.get("uid")).strip()
    return ""


def apply_token_info_client_id(sess, info=None):
    """Write token/info application uid to the session and CLIENT_ID_PATH. Do not scrape."""
    if not sess or not sess.get("access_token"):
        return ""
    if info is None:
        try:
            info = token_info(sess) or {}
        except Exception:
            info = {}
    cid = client_id_from_token_info(info)
    if not cid:
        return ""
    sess["client_id"] = cid
    save_client_id(cid)
    return cid


IDENTITY_KEYS = (
    "identity_canonical_id",
    "identityCanonicalId",
    "canonical_id",
    "identity_id",
    "resource_owner_id",
    "sub",
)


def _identity_from(obj):
    if not isinstance(obj, dict):
        return ""
    for k in IDENTITY_KEYS:
        v = obj.get(k)
        if v:
            return str(v)
    return ""


def graphql(sess, operation, variables, query=None):
    token = sess.get("access_token") or ""
    headers = {
        "Authorization": "Bearer " + token,
        "x-wealthsimple-client": WS_CLIENT,
        "x-ws-profile": "trade",
        "x-ws-api-version": GRAPHQL_VERSION,
        "x-ws-locale": "en-CA",
        "x-platform-os": "web",
        "Content-Type": "application/json",
        "Origin": "https://my.wealthsimple.com",
        "Referer": "https://my.wealthsimple.com/app/trade",
    }
    if sess.get("wssdi"):
        headers["x-ws-device-id"] = sess["wssdi"]
    if sess.get("session_id"):
        headers["x-ws-session-id"] = sess["session_id"]
    body = {
        "operationName": operation,
        "query": query if query is not None else QUERIES[operation],
        "variables": {k: v for k, v in variables.items() if v is not None},
    }
    data = _http_json("POST", GRAPHQL, body, headers, timeout=90)
    if data and data.get("_http_status") in (401, 403):
        raise PermissionError("not authorized")
    errs = (data or {}).get("errors")
    if errs:
        first = errs[0] if isinstance(errs, list) else errs
        if isinstance(first, dict):
            emsg = first.get("message") or first.get("error") or str(first)
        else:
            emsg = str(first)
        raise RuntimeError(str(operation) + ": " + str(emsg))
    if not data or data.get("data") is None:
        raise RuntimeError("graphql failed: " + operation)
    return data["data"]



def _money_amount(node, *keys):
    """First present Money.amount from netLiquidationValue / V2 (or deposits)."""
    if not isinstance(node, dict):
        return None, None
    for key in keys:
        money = node.get(key)
        if not isinstance(money, dict) or money.get("amount") is None:
            continue
        try:
            return float(money["amount"]), money.get("currency") or "CAD"
        except (TypeError, ValueError):
            continue
    return None, None


def _nav_points_from_payload(data):
    points = []
    blob = data or {}
    ident = blob.get("identity") or {}
    acc = blob.get("account") or {}
    fin = ident.get("financials") if ident.get("financials") is not None else acc.get("financials")
    hist = ((fin or {}).get("historicalDaily") or {})
    for edge in hist.get("edges") or []:
        node = (edge or {}).get("node") or {}
        amt, cur = _money_amount(node, "netLiquidationValue", "netLiquidationValueV2")
        d = (node.get("date") or "")[:10]
        if not d or amt is None:
            continue
        rec = {"date": d, "equity": amt, "currency": cur or "CAD"}
        nd_amt, _nd_cur = _money_amount(node, "netDeposits", "netDepositsV2")
        if nd_amt is not None:
            rec["netDeposits"] = nd_amt
        points.append(rec)
    page = hist.get("pageInfo") or {}
    return points, page


def _paginate_nav_history(sess, operation, extra_variables, query=None, since_date=None):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since = _s(since_date)[:10]
    if since and since > today:
        return []
    year0 = int(since[:4]) if since else 2020
    year1 = int(today[:4])
    points = []
    for year in range(year0, year1 + 1):
        start = f"{year}-01-01"
        if since and start < since:
            start = since
        end = today if year == year1 else f"{year}-12-31"
        if start > end:
            continue
        cursor = None
        for _ in range(8):
            variables = dict(extra_variables)
            variables["startDate"] = start
            variables["endDate"] = end
            variables["cursor"] = cursor
            data = graphql(sess, operation, variables, query=query)
            chunk, page = _nav_points_from_payload(data)
            points.extend(chunk)
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
            if not cursor:
                break
    by_date = {}
    for rec in points:
        by_date[rec["date"]] = rec
    return [by_date[d] for d in sorted(by_date)]


def fetch_nav_history(sess, identity_id, since_date=None):
    """Identity-wide Wealthsimple net liquidation (All / accountId '')."""
    return _paginate_nav_history(
        sess,
        "IdentityHistoricalFinancialsQuery",
        {
            "identityId": identity_id,
            "currency": "CAD",
            "limit": 400,
            "includeNetDeposits": True,
        },
        query=Q_IDENTITY_HISTORICAL_FINANCIALS,
        since_date=since_date,
    )


def fetch_account_nav_history(sess, account_id, since_date=None):
    """Daily NAV for one Wealthsimple account via FetchAccountHistoricalFinancials."""
    aid = _s(account_id).strip()
    if not aid:
        return []
    return _paginate_nav_history(
        sess,
        "FetchAccountHistoricalFinancials",
        {
            "id": aid,
            "currency": "CAD",
            "resolution": "DAILY",
            "first": 400,
        },
        query=Q_FETCH_ACCOUNT_HISTORICAL_FINANCIALS,
        since_date=since_date,
    )


def merge_nav_points(series_list):
    """Sum equity (and netDeposits when present) by date across account series."""
    by_date = {}
    for series in series_list or []:
        for rec in series or []:
            if not isinstance(rec, dict):
                continue
            d = _s(rec.get("date"))[:10]
            if not d:
                continue
            equity = rec.get("equity")
            if equity is None:
                continue
            try:
                eq = float(equity)
            except (TypeError, ValueError):
                continue
            cur = by_date.get(d)
            if cur is None:
                cur = {
                    "date": d,
                    "equity": 0.0,
                    "currency": _s(rec.get("currency") or "CAD") or "CAD",
                }
                by_date[d] = cur
            cur["equity"] += eq
            if rec.get("currency"):
                cur["currency"] = _s(rec.get("currency")) or cur["currency"]
            nd = rec.get("netDeposits")
            if nd is not None:
                try:
                    cur["netDeposits"] = cur.get("netDeposits", 0.0) + float(nd)
                except (TypeError, ValueError):
                    pass
    return [by_date[d] for d in sorted(by_date)]


def fetch_nickname_nav_history(sess, accounts):
    """Per-filter-nickname daily NAV. Returns (points, public_errors)."""
    points = []
    errors = []
    last_by = store.nav_last_dates()
    for nick, ids in sorted(nav_account_groups(accounts).items()):
        _set_sync_step("Fetching equity history for %s…" % nick)
        try:
            since = last_by.get(nick)
            series = [fetch_account_nav_history(sess, aid, since_date=since) for aid in ids]
            pts = merge_nav_points(series)
        except Exception as e:
            public = _public_sync_error(e)
            errors.append("%s: %s" % (nick, public))
            sys.stderr.write("NAV history failed for %s: %s\n" % (nick, public))
            continue
        for rec in pts:
            tagged = dict(rec)
            tagged["accountId"] = nick
            points.append(tagged)
    return points, errors


def refresh_nav_only(allow_refresh=True):
    """Pull daily NAV only. Does not pull activity."""
    store.ensure()
    sess = load_session()
    if not sess or not sess.get("access_token"):
        return {"ok": False, "error": "not connected"}
    identity = _identity_from(sess)
    if not identity:
        try:
            info = token_info(sess)
        except Exception:
            info = {}
        identity = _identity_from(info or {})
    if not identity:
        return {"ok": False, "error": "no identity"}
    accounts = (load_book() or {}).get("accounts") or []
    if not accounts:
        return {"ok": False, "error": "no accounts stored"}
    try:
        last_by = store.nav_last_dates()
        try:
            nav_history = fetch_nav_history(sess, identity, since_date=last_by.get(""))
        except PermissionError:
            raise
        except Exception:
            nav_history = []
        combined = []
        for rec in nav_history:
            tagged = dict(rec)
            tagged["accountId"] = ""
            combined.append(tagged)
        nickname_pts, nav_errors = fetch_nickname_nav_history(sess, accounts)
        combined.extend(nickname_pts)
        store.upsert_nav(combined)
        nicks = sorted({_s(p.get("accountId")) for p in combined if _s(p.get("accountId"))})
        return {
            "ok": True,
            "allDays": sum(1 for p in combined if not _s(p.get("accountId"))),
            "accounts": len(nicks),
            "errors": nav_errors,
        }
    except PermissionError:
        if allow_refresh and refresh_session(load_session() or {}):
            return refresh_nav_only(allow_refresh=False)
        return {"ok": False, "error": "Session expired. Connect again."}


def fetch_all_accounts(sess, identity_id):
    accounts = []
    cursor = None
    while True:
        variables = {
            "identityId": identity_id,
            "pageSize": 25,
            "startDate": "2015-01-01",
            "cursor": cursor,
        }
        data = graphql(sess, "FetchAllAccountFinancials", variables)
        ident = (data or {}).get("identity") or {}
        conn = ident.get("accounts") or {}
        for edge in conn.get("edges") or []:
            node = (edge or {}).get("node")
            if node:
                accounts.append(node)
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
        if not cursor:
            break
    return accounts


def activity_fetch_condition(account_id, start_date=None, now=None):
    """Wealthsimple ActivityCondition. startDate bounds a daily pull to new rows."""
    end = (now or datetime.now(timezone.utc)) + timedelta(days=1)
    cond = {
        "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
        "accountIds": [account_id],
    }
    if start_date:
        raw = _s(start_date).strip()
        if raw:
            if "T" not in raw:
                raw = raw[:10] + "T00:00:00.000Z"
            cond["startDate"] = raw
    return cond


def fetch_activities_for_account(
    sess, account_id, start_date=None, known_canonical_ids=None
):
    items = []
    cursor = None
    while True:
        variables = {
            "first": 100,
            "orderBy": "OCCURRED_AT_DESC",
            "condition": activity_fetch_condition(account_id, start_date=start_date),
        }
        if cursor:
            variables["cursor"] = cursor
        data = graphql(sess, "FetchActivityFeedItems", variables)
        feed = (data or {}).get("activityFeedItems") or {}
        for edge in feed.get("edges") or []:
            node = (edge or {}).get("node")
            if node:
                items.append(node)
        page = feed.get("pageInfo") or {}
        # Walk every page Wealthsimple returns for the window: a page of known
        # rows can still carry a revised one, and the rows behind it are new.
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
        if not cursor:
            break
    return items


def fetch_balances(sess, account_ids):
    balances = []
    ids = [i for i in account_ids if i]
    for i in range(0, len(ids), 20):
        chunk = ids[i : i + 20]
        data = graphql(
            sess,
            "FetchAccountsWithBalance",
            {"ids": chunk, "type": "TRADING"},
        )
        for acc in data.get("accounts") or []:
            aid = acc.get("id")
            for ca in acc.get("custodianAccounts") or []:
                fin = ca.get("financials") or {}
                bals = fin.get("balance") or []
                if isinstance(bals, dict):
                    bals = [bals]
                for b in bals:
                    balances.append(
                        {
                            "accountId": aid,
                            "custodianAccountId": ca.get("id"),
                            "securityId": b.get("securityId"),
                            "quantity": b.get("quantity"),
                        }
                    )
    return balances


def parse_margin(data):
    """Wealthsimple's buying power for one account, as it answers: a Money when
    available, the reason when not, None when the account has no margin figures."""
    try:
        trading = (((((data or {}).get("account") or {}).get("financials") or {}).get("current") or {}).get("marginV3") or {}).get("trading") or {}
    except AttributeError:
        return None
    bp = trading.get("buyingPower")
    if not isinstance(bp, dict):
        return None
    if bp.get("__typename") == "BuyingPowerMetricAvailable":
        total = bp.get("total") or {}
        amount = _num(total.get("amount"), None)
        if amount is None:
            return None
        return {"buyingPower": amount, "currency": _s(total.get("currency")) or "CAD", "unavailable": ""}
    reason = (bp.get("reason") or {})
    why = _s(reason.get("__typename")) or _s(bp.get("__typename")) or "unavailable"
    n = len(reason.get("securities") or []) if isinstance(reason.get("securities"), list) else 0
    if n:
        why += " (%d securities)" % n
    return {"buyingPower": None, "currency": "CAD", "unavailable": why}


def margin_account_ids(accounts):
    """The open margin accounts: the only ones whose buying power is margin available.
    Wealthsimple answers the buying-power query for every self-directed account with
    the cash it could buy with, and with an error for cash, card and crypto accounts;
    neither is margin."""
    out = []
    for a in accounts or []:
        typ = _s(a.get("unifiedAccountType") or a.get("unified_account_type")).upper()
        status = _s(a.get("status")).lower()
        if a.get("id") and "MARGIN" in typ and status != "closed":
            out.append(a.get("id"))
    return out


def fetch_margin(sess, account_ids):
    """One buying-power request per margin account (margin_account_ids); only accounts
    that answer are rows. A request that fails is reported once on the terminal, not hidden."""
    rows = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    failed = 0
    first_error = ""
    for aid in account_ids or []:
        if not aid:
            continue
        try:
            data = graphql(sess, "FetchAccountCurrentMarginBuyingPowerV2", {"accountId": aid, "currency": "CAD"})
        except Exception as e:
            failed += 1
            if not first_error:
                first_error = e.__class__.__name__ + (": " + str(e) if str(e) else "")
            continue
        parsed = parse_margin(data)
        if parsed is None:
            continue
        parsed["accountId"] = aid
        parsed["fetchedAt"] = now
        rows.append(parsed)
    if failed:
        sys.stderr.write("bagholder portfolio: buying power request failed for %d of %d accounts (%s)\n" % (failed, len([a for a in account_ids or [] if a]), first_error))
    return rows


PORTFOLIO_REFRESH_MINUTES = 5


def refresh_portfolio():
    """Net liquidation values, cash balances and buying power, read again between
    syncs so the Portfolio tiles move with the day. Never raises; says what it
    did on the terminal, since a tile showing a dash must be explainable."""
    with _lock:
        if _state["syncing"]:
            return {"ok": False, "skipped": "sync running"}
        if not _state["connected"]:
            return {"ok": False, "skipped": "not connected"}
    try:
        sess = load_session()
        identity = _identity_from(sess or {})
        if not sess or not sess.get("access_token") or not identity:
            sys.stderr.write("bagholder portfolio: no session to read with\n")
            return {"ok": False, "skipped": "no session"}
        accounts = fetch_all_accounts(sess, identity)
        ids = [a.get("id") for a in accounts if a.get("id")]
        if not ids:
            sys.stderr.write("bagholder portfolio: Wealthsimple returned no accounts\n")
            return {"ok": False, "skipped": "no accounts"}
        balances = fetch_balances(sess, ids)
        margin = fetch_margin(sess, margin_account_ids(accounts))
        store.replace_accounts([slim_account(a) for a in accounts])
        store.replace_balances(balances)
        store.replace_margin(margin)
        model.invalidate()
        available = sum(1 for m in margin if m.get("buyingPower") is not None)
        sys.stderr.write("bagholder portfolio: %d accounts, %d balances, buying power for %d of %d margin accounts\n" % (len(ids), len(balances), available, len(margin)))
        return {"ok": True, "accounts": len(ids), "balances": len(balances), "margin": len(margin)}
    except Exception as e:
        sys.stderr.write("bagholder portfolio: failed: %s\n" % (e.__class__.__name__ + (": " + str(e) if str(e) else "")))
        return {"ok": False, "skipped": "error"}


def portfolio_loop():
    """The Portfolio figures Wealthsimple states: once at start, then every
    PORTFOLIO_REFRESH_MINUTES while connected. The first read does not wait,
    so the tiles are filled by the time the page is up."""
    refresh_portfolio()
    while not _stop.wait(60 * PORTFOLIO_REFRESH_MINUTES):
        refresh_portfolio()


def fetch_security(sess, security_id):
    sid = _s(security_id).strip()
    if not sid:
        return None
    try:
        data = graphql(sess, "FetchSecurity", {"securityId": sid})
    except Exception:
        return None
    return _security_record((data or {}).get("security"), sid)


def fetch_securities(sess, security_ids):
    """One request per SECURITY_BATCH ids. Unknown ids come back null and are
    dropped; a failed batch falls back to one request per id."""
    ids = []
    seen = set()
    for raw in security_ids or []:
        sid = _s(raw).strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    out = []
    for i in range(0, len(ids), SECURITY_BATCH):
        chunk = ids[i : i + SECURITY_BATCH]
        try:
            data = graphql(sess, "FetchSecurities", {"ids": chunk})
            rows = (data or {}).get("securities")
            if not isinstance(rows, list):
                raise RuntimeError("no securities list")
        except Exception:
            for sid in chunk:
                rec = fetch_security(sess, sid)
                if rec:
                    out.append(rec)
            continue
        for sec in rows:
            rec = _security_record(sec, "")
            if rec:
                out.append(rec)
    return out


def _security_record(sec, sid):
    if not isinstance(sec, dict) or not sec:
        return None
    stock = sec.get("stock") or {}
    if not isinstance(stock, dict):
        stock = {}
    option = sec.get("optionDetails") or {}
    if not isinstance(option, dict):
        option = {}
    under = option.get("underlyingSecurity") or {}
    if not isinstance(under, dict):
        under = {}
    under_id = _s(under.get("id")).strip() or None
    return {
        "id": _s(sec.get("id")).strip() or sid,
        "symbol": _s(stock.get("symbol")).strip(),
        "name": _s(stock.get("name")).strip(),
        "primaryExchange": _s(stock.get("primaryExchange")).strip(),
        "primaryMic": _s(stock.get("primaryMic")).strip(),
        "currency": _s(sec.get("currency")).strip(),
        "underlyingId": under_id,
    }


def _collect_security_ids():
    ids = []
    seen = set()
    snap = store.snapshot()
    for a in snap.get("activities") or []:
        sid = _s(a.get("securityId")).strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    for b in snap.get("balances") or []:
        sid = _s(b.get("securityId")).strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    return ids


def _account_ids_for_backfill():
    snap = store.snapshot()
    ids = []
    seen = set()
    for acc in snap.get("accounts") or []:
        aid = _s(acc.get("id")).strip()
        if aid and aid not in seen:
            seen.add(aid)
            ids.append(aid)
    if ids:
        return ids
    for a in snap.get("activities") or []:
        aid = _s(a.get("accountId")).strip()
        if aid and aid not in seen:
            seen.add(aid)
            ids.append(aid)
    return ids


def fill_listings(sess, from_sync=False):
    """Stamp missing activity security_id values and cache FetchSecurity listings."""
    store.ensure()
    if not sess or not sess.get("access_token"):
        return False
    with _lock:
        if _state.get("listingsFilling"):
            return False
        if _state.get("syncing") and not from_sync:
            return False
        _state["listingsFilling"] = True
        _state["syncStep"] = "Attaching listing ids…"
    try:
        if store.needs_security_id_backfill():
            walk_ok = True
            known = store.canonical_ids()
            mapped = []
            _set_sync_step("Attaching listing ids…")
            for aid in _account_ids_for_backfill():
                try:
                    raw_items = fetch_activities_for_account(
                        sess,
                        aid,
                        start_date=None,
                        known_canonical_ids=known,
                    )
                except Exception:
                    walk_ok = False
                    continue
                acc_by_id = {
                    a.get("id"): a
                    for a in (store.snapshot().get("accounts") or [])
                    if a.get("id")
                }
                for it in raw_items:
                    mapped.extend(map_activity_rows(it, acc_by_id))
            if mapped:
                store.apply_wealthsimple_mapped(mapped)
            if walk_ok:
                store.set_meta("security_id_backfill_done", "1")
        wanted = _collect_security_ids()
        pending = store.missing_security_ids(wanted)
        seen = set()
        to_upsert = []
        # Options point at an underlying security; fetch those in a second round.
        while pending:
            _set_sync_step("Looking up company names, %s left" % len(pending))
            batch = [sid for sid in pending if sid not in seen]
            seen.update(batch)
            pending = []
            if not batch:
                break
            recs = fetch_securities(sess, batch)
            to_upsert.extend(recs)
            under = [_s(r.get("underlyingId")).strip() for r in recs]
            under = [u for u in under if u and u not in seen]
            if under:
                pending = store.missing_security_ids(under)
        if to_upsert:
            store.upsert_securities(to_upsert)
        return True
    except Exception:
        return False
    finally:
        with _lock:
            _state["listingsFilling"] = False
            _state["syncStep"] = ""


def slim_account(acc):
    nlv = None
    try:
        nlv = (
            (((acc.get("financials") or {}).get("currentCombined") or {}).get("netLiquidationValue") or {}).get("amount")
        )
    except Exception:
        nlv = None
    return {
        "id": acc.get("id"),
        "nickname": acc.get("nickname") or "",
        "unifiedAccountType": acc.get("unifiedAccountType") or "",
        "currency": acc.get("currency") or "",
        "status": acc.get("status") or "",
        "type": acc.get("type") or "",
        "netLiquidationValue": nlv,
    }


def _public_sync_error(exc):
    msg = str(exc or "").replace("\n", " ").strip()
    if "CERTIFICATE_VERIFY_FAILED" in msg or "unable to get local issuer certificate" in msg:
        return "could not verify HTTPS certificates"
    msg = re.sub(r"(?i)bearer\s+\S+", "[redacted]", msg)
    msg = re.sub(r"(?i)(access_token|refresh_token)\s*[:=]\s*\S+", r"\1=[redacted]", msg)
    if "bearer" in msg.lower() or "access_token" in msg.lower() or "refresh_token" in msg.lower():
        msg = re.sub(r"(?i)(bearer|access_token|refresh_token)", "[redacted]", msg)
    msg = re.sub(r"\s+", " ", msg).strip()
    if len(msg) > 180:
        msg = msg[:177] + "..."
    return msg or "unknown error"


def _set_sync_step(msg):
    with _lock:
        _state["syncStep"] = msg or ""


def _expires_at_unix(sess):
    raw = (sess or {}).get("expires_at")
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def token_refresh_needed(sess, now=None):
    exp = _expires_at_unix(sess)
    if exp is None:
        return True
    now = time.time() if now is None else float(now)
    return now >= exp - TOKEN_REFRESH_MARGIN_SEC


def ensure_fresh_token(sess=None):
    """Refresh the access token before expires_at. Token POST only.

    Connected means this POST produced a new access token. A failed POST
    leaves session.json on disk and marks connected False.
    """
    sess = sess if sess is not None else load_session()
    if not sess or not sess.get("refresh_token"):
        with _lock:
            _state["connected"] = False
            _state["error"] = "missing refresh token"
        return False
    with _lock:
        connected = bool(_state.get("connected"))
    if connected and not token_refresh_needed(sess):
        return True
    ok = refresh_session(sess)
    with _lock:
        _state["connected"] = bool(ok)
        if ok:
            _state["error"] = ""
        elif not (_state.get("error") or "").strip():
            _state["error"] = "Wealthsimple token refresh failed"
    return ok


def activity_sync_bounds():
    """Full history only when the activity table has no rows yet."""
    if store.activity_count() == 0:
        return {"start_date": None, "full_history": True}
    start = store.incremental_start_date() or None
    return {"start_date": start, "full_history": False}


def run_sync(allow_refresh=True, force_activity=True):
    """GraphQL pull. Inserts new Wealthsimple rows only. Never rebuilds the table."""
    store.ensure()
    with _lock:
        if _state["syncing"]:
            return False
        _state["syncing"] = True
        _state["error"] = ""
        _state["syncStep"] = "Checking session…"
    try:
        sess = load_session()
        if not sess or not (sess.get("access_token") or sess.get("refresh_token")):
            with _lock:
                _state["connected"] = False
            return False
        info = {}
        if not sess or not sess.get("access_token"):
            with _lock:
                _state["connected"] = False
            return False
        identity = _identity_from(sess) or _identity_from(info or {})
        if not identity:
            info = info or token_info(sess)
            identity = _identity_from(info or {})
        if not identity:
            raise RuntimeError("no identity_canonical_id")
        sess["identity_canonical_id"] = identity
        email = (info or {}).get("email") or (info or {}).get("username") or sess.get("email") or ""
        if email:
            sess["email"] = email
        save_session(sess)

        if not force_activity and not store.activity_pull_due(interval_sec=ACTIVITY_PULL_SEC):
            with _lock:
                _state["connected"] = True
                _state["email"] = email
                _state["lastSync"] = store.get_meta("synced_at") or _state["lastSync"]
                _state["capturing"] = False
                _state["error"] = ""
                _state["syncStep"] = ""
            return True

        _set_sync_step("Fetching accounts…")
        accounts = fetch_all_accounts(sess, identity)
        acc_by_id = {a.get("id"): a for a in accounts if a.get("id")}
        bounds = activity_sync_bounds()
        start_date = bounds["start_date"]
        known = store.canonical_ids() if not bounds["full_history"] else set()
        mapped = []
        with_ids = [a for a in accounts if a.get("id")]
        _set_sync_step("Syncing transactions")
        for acc in with_ids:
            aid = acc.get("id")
            raw_items = fetch_activities_for_account(
                sess,
                aid,
                start_date=start_date,
                known_canonical_ids=known,
            )
            for it in raw_items:
                mapped.extend(map_activity_rows(it, acc_by_id))
        pools = fifo_pool_ids(accounts)
        for row in mapped:
            aid = row.get("accountId") or ""
            row["fifoId"] = pools.get(aid, aid)
        _set_sync_step("Fetching balances…")
        balances = fetch_balances(sess, list(acc_by_id.keys()))
        margin = fetch_margin(sess, margin_account_ids(accounts))
        _set_sync_step("Fetching equity history…")
        last_by = store.nav_last_dates()
        try:
            nav_history = fetch_nav_history(sess, identity, since_date=last_by.get(""))
        except Exception:
            nav_history = []
        combined = []
        for rec in nav_history:
            tagged = dict(rec)
            tagged["accountId"] = ""
            combined.append(tagged)
        nickname_pts, nav_errors = fetch_nickname_nav_history(sess, accounts)
        combined.extend(nickname_pts)
        store.apply_wealthsimple_mapped(mapped)
        synced = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _set_sync_step("Saving…")
        save_accounts_snapshot(
            {
                "accounts": [slim_account(a) for a in accounts],
                "balances": balances,
                "margin": margin,
                "navHistory": combined,
                "syncedAt": synced,
            }
        )
        store.mark_activity_pulled(synced)
        fill_listings(sess, from_sync=True)
        nav_err_line = ""
        if nav_errors:
            nav_err_line = "NAV history failed for " + "; ".join(nav_errors)
        with _lock:
            _state["connected"] = True
            _state["email"] = email
            _state["lastSync"] = synced
            _state["capturing"] = False
            _state["error"] = nav_err_line
            _state["syncStep"] = ""
        return True
    except PermissionError:
        if allow_refresh and refresh_session(load_session() or {}):
            with _lock:
                _state["syncing"] = False
            return run_sync(allow_refresh=False, force_activity=force_activity)
        with _lock:
            _state["connected"] = False
            _state["error"] = "Session expired. Connect again."
        return False
    except Exception as e:
        line = "Sync failed: " + _public_sync_error(e)
        sys.stderr.write(line + "\n")
        with _lock:
            _state["error"] = line
        return False
    finally:
        with _lock:
            _state["syncing"] = False
            _state["syncStep"] = ""


def boot_session():
    store.ensure()
    sess = load_session()
    if not sess:
        with _lock:
            _state["connected"] = False
            snap = store.snapshot()
            _state["lastSync"] = snap.get("syncedAt") or ""
        return
    info = {}
    info_ok = False
    if sess.get("access_token"):
        try:
            info = token_info(sess) or {}
        except Exception:
            info = {}
        info_ok = bool(info) and not info.get("error") and not info.get("_http_status")
        if info_ok:
            apply_token_info_client_id(sess, info)
            if info.get("identity_canonical_id") and not sess.get("identity_canonical_id"):
                sess["identity_canonical_id"] = info["identity_canonical_id"]
            if info.get("email"):
                sess["email"] = info["email"]
            save_session(sess)
    ok = bool(info_ok)
    if not ok and sess.get("refresh_token"):
        ok = refresh_session(sess)
        sess = load_session() or sess
    with _lock:
        _state["connected"] = bool(ok)
        if ok:
            _state["error"] = ""
        elif not (_state.get("error") or "").strip():
            if not (sess or {}).get("refresh_token"):
                _state["error"] = "missing refresh token"
            else:
                _state["error"] = "Wealthsimple token refresh failed"
        _state["email"] = (sess or {}).get("email") or ""
        book = load_book()
        _state["lastSync"] = book.get("syncedAt") or ""


def find_chrome():
    if sys.platform == "darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            if os.path.isfile(p):
                return p
    names = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
        "chrome",
    ]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    extras = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    extras.extend(
        [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
    )
    for p in extras:
        if p and os.path.isfile(p):
            return p
    return ""


def _cdp_list(port, timeout=1):
    for path in ("/json/list", "/json"):
        try:
            url = "http://127.0.0.1:%s%s" % (port, path)
            req = Request(url, headers={"Host": "127.0.0.1:%s" % port})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            if not raw:
                continue
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            continue
    return []


def _mask_ws(data, key):
    data = data if isinstance(data, (bytes, bytearray)) else bytes(data)
    key = bytes(key)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key[i % 4]
    return bytes(out)


class _MiniWS:
    """RFC6455 client: mask outgoing frames, answer ping with pong."""

    def __init__(self, sock):
        self.sock = sock
        self._buf = b""
        self._next_id = 1

    def close(self):
        try:
            self.send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def send_frame(self, opcode, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        payload = payload or b""
        mask_key = os.urandom(4)
        masked = _mask_ws(payload, mask_key)
        n = len(payload)
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        header.extend(mask_key)
        self.sock.sendall(header + masked)

    def send_text(self, text):
        if not isinstance(text, str):
            text = text.decode("utf-8") if isinstance(text, (bytes, bytearray)) else str(text)
        self.send_frame(0x1, text.encode("utf-8"))

    def _recv_exact(self, n, deadline):
        if n <= 0:
            return b""
        while len(self._buf) < n:
            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError("ws read timeout")
            self.sock.settimeout(max(0.05, remain))
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("ws closed")
            self._buf += chunk
        data = self._buf[:n]
        self._buf = self._buf[n:]
        return data

    def _read_frame(self, deadline):
        b1 = self._recv_exact(1, deadline)[0]
        b2 = self._recv_exact(1, deadline)[0]
        fin = (b1 & 0x80) != 0
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2, deadline))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8, deadline))[0]
        mask_key = self._recv_exact(4, deadline) if masked else None
        payload = self._recv_exact(length, deadline) if length else b""
        if mask_key:
            payload = _mask_ws(payload, mask_key)
        return fin, opcode, payload

    def recv_message(self, timeout=8):
        deadline = time.time() + timeout
        fragments = []
        started = None
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError("ws read timeout")
            fin, opcode, payload = self._read_frame(deadline)
            if opcode == 0x8:
                raise OSError("ws closed")
            if opcode == 0x9:
                self.send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                started = opcode
                fragments = [payload]
                if fin:
                    return started, b"".join(fragments)
                continue
            if opcode == 0x0:
                fragments.append(payload)
                if fin:
                    return started or 0x1, b"".join(fragments)
                continue


def _ws_connect(ws_url, timeout=5):
    parsed = urlparse(ws_url)
    host = "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = path + "?" + parsed.query
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%s\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n"
            "\r\n"
        ) % (path, host, port, key)
        sock.sendall(req.encode("ascii"))
        buf = b""
        deadline = time.time() + timeout
        while b"\r\n\r\n" not in buf:
            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError("ws handshake timeout")
            sock.settimeout(max(0.05, remain))
            chunk = sock.recv(4096)
            if not chunk:
                raise OSError("ws handshake closed")
            buf += chunk
        header, rest = buf.split(b"\r\n\r\n", 1)
        status_line = header.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            raise OSError("ws handshake failed: %s" % status_line.decode("latin1", "replace"))
        ws = _MiniWS(sock)
        ws._buf = rest
        sock = None
        return ws
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _cdp_call(ws, method, params=None, timeout=8):
    msg_id = ws._next_id
    ws._next_id = msg_id + 1
    payload = {"id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    ws.send_text(json.dumps(payload))
    deadline = time.time() + timeout
    while time.time() < deadline:
        remain = deadline - time.time()
        try:
            opcode, data = ws.recv_message(timeout=max(0.2, remain))
        except Exception:
            continue
        if opcode not in (0x1, 0x2):
            continue
        try:
            msg = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if msg.get("id") == msg_id:
            return msg
    return None


def _json_with_access_token(raw):
    if raw is None:
        return None
    s = raw if isinstance(raw, str) else str(raw)
    if not s:
        return None
    cur = s.strip()
    for _ in range(3):
        if "access_token" in cur:
            try:
                obj = json.loads(cur)
            except ValueError:
                obj = None
            if isinstance(obj, dict) and obj.get("access_token"):
                return obj
        nxt = unquote(cur)
        if nxt == cur:
            break
        cur = nxt
    return None

def _cookies_from_document_cookie(text):
    cookies = []
    if not text:
        return cookies
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({"name": name.strip(), "value": value})
    return cookies

def _tokens_from_cookie_list(cookies):
    if not cookies:
        return None
    body = {}
    oauth = None
    wssdi = ""
    for c in cookies:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or ""
        value = c.get("value") or ""
        if name == DEVICE_COOKIE and value:
            wssdi = value
        parsed = _json_with_access_token(value)
        if parsed:
            if name == OAUTH_COOKIE or oauth is None:
                oauth = parsed
    if not oauth or not oauth.get("access_token"):
        return None
    for k in ("access_token", "refresh_token", "identity_canonical_id", "client_id", "session_id"):
        if oauth.get(k):
            body[k] = oauth[k]
    ident = _identity_from(oauth)
    if ident:
        body["identity_canonical_id"] = ident
    if oauth.get("expires_at") is not None:
        body["expires_at"] = oauth["expires_at"]
    if wssdi:
        body["wssdi"] = wssdi
    return body

def _cdp_cookie_list(msg):
    if msg and isinstance(msg.get("result"), dict):
        return msg["result"].get("cookies") or []
    return []


CAPTURE_CALL_SEC = 2   # each DevTools call while capturing: short, so a closed window is noticed quickly
WINDOW_CHECK_SEC = 0.5   # how often the watcher looks for the window
CAPTURE_EVERY_SEC = 1.5  # how often it tries to capture the session


def _cdp_cookies_from_target(ws_url):
    ws = None
    try:
        ws = _ws_connect(ws_url, timeout=CAPTURE_CALL_SEC)
        ua = ""
        ver = _cdp_call(ws, "Browser.getVersion", timeout=CAPTURE_CALL_SEC)
        if ver and isinstance(ver.get("result"), dict):
            ua = _s(ver["result"].get("userAgent")).strip()
        if ua:
            save_user_agent(ua)
        _cdp_call(ws, "Network.enable", timeout=CAPTURE_CALL_SEC)
        cookies = _cdp_cookie_list(_cdp_call(ws, "Network.getAllCookies", timeout=CAPTURE_CALL_SEC))
        body = _tokens_from_cookie_list(cookies)
        if body:
            if ua:
                body["user_agent"] = ua
            return body
        extra = _cdp_cookie_list(_cdp_call(ws, "Storage.getCookies", timeout=CAPTURE_CALL_SEC))
        if extra:
            cookies = list(cookies) + list(extra)
        body = _tokens_from_cookie_list(cookies)
        if body:
            if ua:
                body["user_agent"] = ua
            return body
        ev = _cdp_call(
            ws,
            "Runtime.evaluate",
            {"expression": "document.cookie", "returnByValue": True},
            timeout=CAPTURE_CALL_SEC,
        )
        val = ""
        if ev:
            res = (ev.get("result") or {}).get("result") or {}
            val = res.get("value") or ""
        body = _tokens_from_cookie_list(_cookies_from_document_cookie(val))
        if body and ua:
            body["user_agent"] = ua
        return body
    except Exception:
        return None
    finally:
        if ws is not None:
            ws.close()


def _try_capture_from_cdp(port):
    targets = _cdp_list(port)
    pages = []
    others = []
    for t in targets:
        if not isinstance(t, dict) or not t.get("webSocketDebuggerUrl"):
            continue
        if t.get("type") == "page":
            pages.append(t)
        else:
            others.append(t)
    for t in pages + others:
        try:
            body = _cdp_cookies_from_target(t["webSocketDebuggerUrl"])
        except Exception:
            continue
        if body and body.get("access_token"):
            return body
    return None


def _cdp_pages(port):
    """The open windows and tabs of the app's login Chrome. A Chrome left running
    with no window still answers on the debug port with background targets; only
    page targets mean a window is up."""
    return [t for t in _cdp_list(port, timeout=WINDOW_CHECK_SEC) if isinstance(t, dict) and t.get("type") == "page" and t.get("id")]


def _attempt_is(attempt):
    with _lock:
        return attempt is None or _state.get("login_attempt") == attempt


def _capture_loop(proc, debug_port, attempt):
    """Try to capture the session every CAPTURE_EVERY_SEC while the attempt is
    live. Runs beside the window watcher so a capture call stuck on a window
    that just closed never delays noticing the close. A captured refresh token
    Wealthsimple refused is not posted again; the loop waits for the browser
    to hold a different one."""
    refused = None
    while _attempt_is(attempt):
        with _lock:
            if not _state.get("capturing"):
                return
        body = None
        try:
            if _cdp_pages(debug_port):
                body = _try_capture_from_cdp(debug_port)
        except Exception:
            body = None
        if body and body.get("access_token") and _attempt_is(attempt) and body.get("refresh_token") != refused:
            with _lock:
                if not _state.get("capturing"):
                    return
            if capture_tokens(body).get("ok"):
                sys.stderr.write("bagholder captured Wealthsimple session\n")
                _close_login_browser(proc)
                return
            refused = body.get("refresh_token")
            sys.stderr.write("bagholder login: Wealthsimple refused the captured session on refresh; still watching the window\n")
        time.sleep(CAPTURE_EVERY_SEC)


def _poll_chrome_session(proc, debug_port, attempt=None):
    """Watch one login attempt's window: every WINDOW_CHECK_SEC, is it still
    there? The capture runs in its own thread (_capture_loop). A watcher belongs
    to the attempt it was started for; once a later Connect has started
    another, it exits without touching anything."""
    deadline = time.time() + CAPTURE_WAIT_SEC
    start = time.time()
    seen_page = False
    threading.Thread(target=_capture_loop, args=(proc, debug_port, attempt), name="bagholder-cdp-capture", daemon=True).start()
    while time.time() < deadline:
        if not _attempt_is(attempt):
            return
        with _lock:
            still = bool(_state.get("capturing"))
        if not still:
            return
        try:
            pages = _cdp_pages(debug_port) if proc.poll() is None else []
        except Exception:
            pages = []
        seen_page = seen_page or bool(pages)
        gone = proc.poll() is not None or (not pages and (seen_page or time.time() - start > 10))
        if gone:
            # the window is gone (Chrome quit, or the window closed with Chrome
            # lingering without one): the attempt is over, nothing is relaunched
            if not _attempt_is(attempt):
                return
            with _lock:
                if _state.get("capturing"):
                    _state["error"] = (
                        "The Chrome window closed before a session showed up. Choose Connect Wealthsimple to try again."
                    )
                    _state["capturing"] = False
            sys.stderr.write("bagholder login: window closed, waiting stopped\n")
            _close_login_browser(proc)
            return
        time.sleep(WINDOW_CHECK_SEC)
    if not _attempt_is(attempt):
        return
    with _lock:
        if _state.get("capturing"):
            _state["error"] = (
                "No session yet. Finish login in the Chrome window, then wait a few seconds."
            )
            _state["capturing"] = False
    _close_login_browser(proc)


def _login_browser_ws():
    """DevTools browser endpoint of the Chrome the app launched, or None."""
    port = DEBUG_PORTS[0]
    try:
        req = Request("http://127.0.0.1:%s/json/version" % port, headers={"Host": "127.0.0.1:%s" % port})
        with urlopen(req, timeout=2) as resp:
            v = json.loads(resp.read().decode("utf-8"))
        return v.get("webSocketDebuggerUrl") or None
    except Exception:
        return None


def _close_login_browser(only=None):
    """Close the Chrome the app launched for login: gracefully through DevTools,
    then by ending the process if it lingers. Only ever the app's own instance,
    never the user's Chrome. With `only`, a watcher closes just the instance it
    was watching, never a later attempt's window."""
    with _lock:
        proc = _state.get("chrome_proc")
        if only is not None and proc is not only:
            proc = only
            current = False
        else:
            current = True
        if current:
            _state["chrome_proc"] = None
    if proc is None:
        return
    if not current:
        # an older instance: it is no longer on the debug port, just end it if it lingers
        try:
            proc.wait(timeout=0.1)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        return
    ws_url = _login_browser_ws()
    if ws_url:
        try:
            ws = _ws_connect(ws_url)
            try:
                _cdp_call(ws, "Browser.close")
            finally:
                ws.close()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _login_browser_alive():
    """True only while the app's login Chrome has a window up."""
    with _lock:
        proc = _state.get("chrome_proc")
    if proc is None or proc.poll() is not None or not _login_browser_ws():
        return False
    try:
        return bool(_cdp_pages(DEBUG_PORTS[0]))
    except Exception:
        return False


def cancel_login():
    """Stop waiting for a login and close the window the app opened."""
    with _lock:
        was = bool(_state.get("capturing"))
        _state["capturing"] = False
        _state["error"] = ""
    sys.stderr.write("bagholder login: cancelled\n")
    _close_login_browser()
    return {"ok": True, "cancelled": was}


def start_login_browser():
    """Open the login window. Only a press of Connect reaches here, and this is
    the only place the app opens a browser window: a window the app's Chrome
    still has up is brought forward instead; anything else (no window, a
    lingering windowless Chrome) is closed and one fresh window is launched."""
    sys.stderr.write("bagholder login: connect requested\n")
    if _login_browser_alive():
        try:
            ws = _ws_connect(_login_browser_ws())
            try:
                _cdp_call(ws, "Target.activateTarget", {"targetId": _cdp_pages(DEBUG_PORTS[0])[0]["id"]})
            finally:
                ws.close()
        except Exception:
            pass
        with _lock:
            already = bool(_state.get("capturing"))
            _state["capturing"] = True
            _state["error"] = ""
            proc = _state.get("chrome_proc")
            if not already:
                _state["login_attempt"] += 1
            attempt = _state["login_attempt"]
        if not already:
            threading.Thread(target=_poll_chrome_session, args=(proc, DEBUG_PORTS[0], attempt), name="bagholder-cdp-capture", daemon=True).start()
        sys.stderr.write("bagholder login: window already up, brought forward\n")
        return {"ok": True, "reused": True}
    _close_login_browser()   # a windowless leftover of ours, if any
    chrome = find_chrome()
    if not chrome:
        return {
            "ok": False,
            "error": 'Install Chrome. Passkey login has to happen on Wealthsimple’s site.',
        }
    profile = HOME / "chrome"
    _ensure_home()
    profile.mkdir(mode=0o700, exist_ok=True)
    debug_port = DEBUG_PORTS[0]
    args = [
        chrome,
        "--user-data-dir=" + str(profile),
        "--remote-debugging-port=%s" % debug_port,
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=http://127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        LOGIN_URL,
    ]
    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(args, **kwargs)
        sys.stderr.write("bagholder login: chrome launched (pid %s)\n" % proc.pid)
        with _lock:
            _state["chrome_proc"] = proc
            _state["capturing"] = True
            _state["error"] = ""
            _state["login_attempt"] += 1   # any watcher of an earlier attempt now exits quietly
            attempt = _state["login_attempt"]
        t = threading.Thread(
            target=_poll_chrome_session,
            args=(proc, debug_port, attempt),
            name="bagholder-cdp-capture",
            daemon=True,
        )
        t.start()
        return {"ok": True}
    except Exception:
        return {
            "ok": False,
            "error": 'Install Chrome. Passkey login has to happen on Wealthsimple’s site.',
        }


def capture_tokens(body):
    """Persist session.json and kick a sync thread. Never print tokens."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "bad body"}
    access = body.get("access_token")
    if not access:
        return {"ok": False, "error": "missing access_token"}
    sess = load_session() or {}
    for k in (
        "access_token",
        "refresh_token",
        "identity_canonical_id",
        "expires_at",
        "wssdi",
        "client_id",
        "session_id",
        "user_agent",
    ):
        if body.get(k):
            sess[k] = body[k]
    ident = _identity_from(body) or _identity_from(sess)
    info = {}
    if sess.get("access_token"):
        try:
            info = token_info(sess) or {}
        except Exception:
            info = {}
    if not ident:
        ident = _identity_from(info)
    if ident:
        sess["identity_canonical_id"] = ident
    if not sess.get("session_id"):
        sess["session_id"] = str(uuid.uuid4())
    apply_token_info_client_id(sess, info)
    if not sess.get("client_id"):
        cid = scrape_client_id()
        if cid:
            sess["client_id"] = cid
    if not sess.get("user_agent"):
        ua = cached_user_agent()
        if ua:
            sess["user_agent"] = ua
    # Take the login over: rotate its refresh token now, so the copy the
    # browser holds goes stale instead of ours, and a capture Wealthsimple
    # will not honour is found out here, not at the next restart.
    if not refresh_session(sess, adopt=False):
        with _lock:
            _state["connected"] = False
            err = _state.get("error") or "Wealthsimple refused the captured login"
        return {"ok": False, "error": err}
    save_session(sess)
    with _lock:
        _state["connected"] = True
        _state["capturing"] = False
        _state["error"] = ""
    t = threading.Thread(target=run_sync, name="bagholder-sync", daemon=True)
    t.start()
    return {"ok": True}


def _manual_from_fields(body):
    side = _upper(body.get("side") or "BUY")
    if side not in ("BUY", "SELL"):
        side = "BUY"
    qty = abs(_num(body.get("qty") if body.get("qty") is not None else body.get("quantity")))
    px = abs(_num(body.get("price") if body.get("price") is not None else body.get("unitPrice")))
    date = _date_only(body.get("date") or body.get("transactionDate") or body.get("occurredAt")) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    symbol = _upper(body.get("symbol"))
    currency = _upper(body.get("currency") or "CAD")
    if currency not in ("CAD", "USD"):
        currency = "CAD"
    account_id = _s(body.get("accountId") or body.get("account") or "manual") or "manual"
    signed_qty = qty if side == "BUY" else -qty
    cash = -(qty * px) if side == "BUY" else (qty * px)
    return {
        "id": str(uuid.uuid4()),
        "occurredAt": date,
        "transactionDate": date,
        "settlementDate": date,
        "accountId": account_id,
        "bookId": account_id,
        "accountType": _s(body.get("accountType") or ("Manual" if account_id == "manual" else "")),
        "activityType": "Trade",
        "activitySubType": side,
        "description": ("Buy" if side == "BUY" else "Sell") + (f" {qty:g} {symbol} @ {px:g}" if symbol else ""),
        "direction": "DEBIT" if side == "BUY" else "CREDIT",
        "symbol": symbol,
        "name": symbol,
        "currency": currency,
        "quantity": signed_qty,
        "unitPrice": px,
        "commission": abs(_num(body.get("commission"))),
        "netCashAmount": cash,
        "category": "trade",
        "balance": None,
        "source": "manual",
    }


def _normalize_local_row(act):
    act = dict(act or {})
    source = _s(act.get("source")) or "manual"
    if source == "wealthsimple":
        cid = store._canonical_from_row(act, "wealthsimple")
        if cid:
            act["canonicalId"] = cid
            act["source"] = "wealthsimple"
            return act
        source = "manual"
    act["source"] = source
    act.pop("canonicalId", None)
    act.pop("canonical_id", None)
    if not act.get("accountId"):
        act["accountId"] = "manual"
    if not act.get("bookId"):
        act["bookId"] = act["accountId"]
    if not act.get("id") or store.looks_like_homemade_id(act.get("id")):
        act["id"] = str(uuid.uuid4())
    if not act.get("occurredAt"):
        act["occurredAt"] = act.get("transactionDate") or ""
    return act


def append_manual(body):
    body = body or {}
    rows = []
    if isinstance(body.get("activities"), list):
        rows = [r for r in body["activities"] if isinstance(r, dict)]
    elif body.get("activity") and isinstance(body["activity"], dict):
        rows = [body["activity"]]
    else:
        rows = [_manual_from_fields(body)]
    rows = [_normalize_local_row(r) for r in rows]
    result = store.merge_local_rows(rows)
    snap = store.snapshot()
    if not snap.get("syncedAt"):
        store.set_meta("synced_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        snap = store.snapshot()
    with _lock:
        _state["lastSync"] = snap.get("syncedAt") or _state["lastSync"]
    saved = result.get("activities") or []
    out = {"ok": True, "added": result.get("added", 0), "duplicates": result.get("duplicates", 0)}
    if len(saved) == 1:
        out["activity"] = saved[0]
    elif saved:
        out["activities"] = saved
    elif len(rows) == 1:
        # duplicate of an already-stored local row
        out["activity"] = rows[0]
    return out


def status_payload():
    book = load_book()
    sess = load_session()
    with _lock:
        connected = bool(_state["connected"] and sess and sess.get("access_token"))
        return {
            "ok": True,
            "connected": connected,
            "email": _state["email"] or (sess or {}).get("email") or "",
            "lastSync": _state["lastSync"] or book.get("syncedAt") or "",
            "activityCount": len(book.get("activities") or []),
            "accountCount": len(book.get("accounts") or []),
            "capturing": bool(_state["capturing"]),
            "syncing": bool(_state["syncing"]),
            "listingsFilling": bool(_state.get("listingsFilling")),
            "syncStep": _state.get("syncStep") or "",
            "error": _state["error"] or "",
            "dataVersion": store.data_version() + "|" + model.today_local(),
            "protocol": PROTOCOL,
            "startedAt": STARTED_AT,
            "version": APP_VERSION,
            "latestVersion": str(update_status().get("latest") or ""),
            "updateAvailable": bool(update_status().get("updateAvailable")),
            "updateUrl": str(update_status().get("url") or REPO_URL),
            "canUpdate": can_update(),
            "updateBy": "image" if UPDATES_OFF else "app",
            "updating": str(_state.get("updating") or ""),
            "updateError": str(_state.get("updateError") or ""),
        }


def ledger_path():
    return Path(__file__).resolve().parent / "ledger.html"


def _payer_symbols():
    try:
        return model.payer_symbols()
    except Exception:
        return []


def refresh_market_data():
    """USD/CAD, S&P 500 and declared distributions for the derived model. Never raises."""
    try:
        out = market.refresh_all(_ssl_context(), _payer_symbols())
        out["quotes"] = refresh_quotes()
        if out.get("distributions") or out.get("quotes"):
            model.invalidate()
        return out
    except Exception:
        return {"fx": 0, "benchmark": 0, "distributions": 0, "quotes": 0, "skipped": True}


def refresh_quotes():
    """Prices for held positions, at most every QUOTE_REFRESH_MINUTES. Never raises."""
    try:
        n = market.refresh_quotes(model.held_symbols(), _ssl_context())
        if n:
            model.invalidate()
        return n
    except Exception:
        return 0


def refresh_periodic_market():
    """USD/CAD, S&P 500 and declared distributions on their own clocks. Never raises."""
    try:
        out = market.refresh_periodic(_ssl_context(), _payer_symbols())
        if out.get("fx") or out.get("benchmark") or out.get("distributions"):
            model.invalidate()
        return out
    except Exception:
        return {"fx": 0, "benchmark": 0, "distributions": 0, "skipped": True}


def archive_intraday_bars():
    """Keep intraday bars for everything traded or held in the past year, a few
    instruments per call so the sources are never hammered. Never raises."""
    try:
        recs = model.intraday_archive_symbols()
        return market.archive_daily(recs, _ssl_context()) + market.archive_intraday(recs, _ssl_context())
    except Exception:
        return []


def archive_loop():
    """Sweeps the archive until every instrument is kept, then tops up once a day
    per instrument. While there is a backlog the next pass follows at once; when a
    pass finds nothing to do the loop rests five minutes."""
    delay = 20
    while not _stop.wait(delay):
        worked = archive_intraday_bars()
        delay = 5 if len(worked) >= market.ARCHIVE_BATCH else 5 * 60


def quote_loop():
    """Prices, every QUOTE_REFRESH_MINUTES."""
    while not _stop.wait(60 * market.QUOTE_REFRESH_MINUTES):
        refresh_quotes()


def market_loop():
    """Declared distributions (20-hour records), USD/CAD and the S&P 500 (6 hours),
    checked once an hour on their own clock, apart from prices."""
    while not _stop.wait(60 * market.MARKET_CHECK_MINUTES):
        refresh_periodic_market()
        check_for_update_if_due()


WATCH_SCAN_SEC = 10 * 60


def scan_watched_folder():
    """Import new or changed CSVs from the watched folder. Never raises."""
    try:
        if not csvimport.watch_folder():
            return None
        result = csvimport.scan_folder()
        if result.get("ok") and result.get("added"):
            model.invalidate()
        return result
    except Exception:
        return None


def watch_loop():
    scan_watched_folder()
    while not _stop.wait(WATCH_SCAN_SEC):
        scan_watched_folder()


def sync_then_market():
    ok = run_sync()
    refresh_market_data()
    return ok


def parse_version(tag):
    """'v1.2.3' -> (1, 2, 3); anything else -> None."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", str(tag or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def check_for_update(now=None):
    """Ask GitHub for the latest release and compare its tag with APP_VERSION.
    Returns the record stored in meta: {checkedAt, ok, latest, url, updateAvailable}. Never raises."""
    now = now or datetime.now(timezone.utc)
    record = {"checkedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "ok": False, "latest": "", "url": REPO_URL + "/releases/latest", "updateAvailable": False}
    try:
        rel = _http_json("GET", RELEASE_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Bagholder/" + APP_VERSION}, timeout=30)
        latest = parse_version((rel or {}).get("tag_name"))
        if latest is None:
            raise ValueError("no release")
        record.update({"ok": True, "latest": str(rel.get("tag_name")), "url": str(rel.get("html_url") or record["url"]), "updateAvailable": latest > parse_version(APP_VERSION)})
        record["assets"] = release_assets(rel)
    except Exception:
        pass
    try:
        store.set_meta("update_check", json.dumps(record))
    except Exception:
        pass
    return record


def update_status():
    try:
        raw = store.get_meta("update_check")
        rec = json.loads(raw) if raw else {}
        return rec if isinstance(rec, dict) else {}
    except Exception:
        return {}


def release_assets(rel):
    """{zip, sha} download URLs of a release's web archive and its .sha256, when present.

    The archive is bagholder-<tag>-web.zip; releases before the name carried a
    platform were bagholder-<tag>.zip, still accepted. Other assets on the page
    (the Android build, bagholder-<tag>-android.apk) are ignored.
    """
    tag = str((rel or {}).get("tag_name") or "")
    found = {}
    for a in (rel or {}).get("assets") or []:
        found[str(a.get("name") or "")] = str(a.get("browser_download_url") or "")
    for stem in ("bagholder-%s-web.zip" % tag, "bagholder-%s.zip" % tag):
        if found.get(stem) and found.get(stem + ".sha256"):
            return {"zip": found[stem], "sha": found[stem + ".sha256"]}
    return {}


# --------------------------------------------------------------------------
# in-app update
# --------------------------------------------------------------------------


def update_mode():
    """'git' when this copy is a git checkout with git on the path, else 'release'."""
    return "git" if (APP_DIR / ".git").exists() and shutil.which("git") else "release"


def _git(*args):
    return subprocess.run(["git"] + list(args), cwd=str(APP_DIR), capture_output=True, text=True, timeout=120)


def git_update_ready():
    """(ok, reason) for updating a git checkout: clean tree on master."""
    try:
        if _git("status", "--porcelain").stdout.strip():
            return False, "This copy is a git checkout with local changes; pull it yourself."
        if _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "master":
            return False, "This copy is a git checkout on another branch; pull it yourself."
        return True, ""
    except Exception as e:
        return False, "git: %s" % e


def can_update(rec=None):
    rec = rec if rec is not None else update_status()
    if not rec.get("updateAvailable") or UPDATES_OFF:
        return False
    if update_mode() == "git":
        return git_update_ready()[0]
    return bool(rec.get("assets"))


def _download(url, dest, max_bytes=UPDATE_MAX_BYTES):
    req = Request(url, headers={"User-Agent": "Bagholder/" + APP_VERSION, "Accept": "application/octet-stream"})
    with urlopen(req, timeout=120, context=_ssl_context()) as resp, open(dest, "wb") as f:
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("release archive is larger than expected")
            f.write(chunk)


def _extract_release(zip_path, staging):
    """The archive's regular files into `staging`, refusing anything that would
    land outside it. Returns the relative paths written."""
    import zipfile
    written = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or not name or name.startswith("/") or ".." in name.split("/"):
                continue
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(name)
    if not written:
        raise ValueError("release archive is empty")
    return written


def _check_python(staging, names):
    import py_compile
    for name in names:
        if name.endswith(".py"):
            py_compile.compile(str(staging / name), doraise=True)


def _install_files(staging, names, tag):
    """Keep the current copies under HOME/previous, then put the new files in
    place, and leave the marker the supervisor watches for."""
    previous = HOME / "previous"
    if previous.exists():
        shutil.rmtree(previous)
    for name in names:
        cur = APP_DIR / name
        if cur.exists():
            (previous / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cur, previous / name)
    try:
        for name in names:
            (APP_DIR / name).parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / name, APP_DIR / name)
    except Exception:
        # a replace failed part way (a file held open, a permission): every file
        # goes back to its previous copy before the failure is reported
        _rollback()
        raise
    (HOME / "update-pending").write_text(tag)


def _rollback():
    """Put the previous copies back (a restarted server that died at once)."""
    previous = HOME / "previous"
    if not previous.exists():
        return False
    for p in previous.rglob("*"):
        if p.is_file():
            rel = p.relative_to(previous)
            (APP_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, APP_DIR / rel)
    shutil.rmtree(previous, ignore_errors=True)
    return True


def request_restart():
    """Finish the response in flight, then stop serving so the supervisor restarts us."""
    _exit_code[0] = RESTART_CODE
    def go():
        time.sleep(0.5)
        _stop.set()
        try:
            if _httpd is not None:
                _httpd.shutdown()
        except Exception:
            pass
    threading.Thread(target=go, name="bagholder-restart", daemon=True).start()


def perform_update(tag, rec):
    """Bring this copy to `tag`: a git checkout pulls, anything else downloads the
    release, checks it, swaps the files. Then a restart. Never raises; failures
    land in _state['updateError'] and nothing is changed."""
    try:
        if update_mode() == "git":
            with _lock:
                _state["updating"] = "Updating to %s…" % tag
            ok, why = git_update_ready()
            if not ok:
                raise RuntimeError(why)
            r = _git("pull", "--ff-only")
            if r.returncode != 0:
                raise RuntimeError("git pull failed: " + (r.stderr or r.stdout).strip()[:200])
            (HOME / "update-pending").write_text(tag)
        else:
            assets = rec.get("assets") or {}
            if not assets:
                raise RuntimeError("This release has no downloadable archive.")
            with _lock:
                _state["updating"] = "Downloading %s…" % tag
            staging = HOME / "staging"
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            zip_path = HOME / ("bagholder-%s.zip" % tag)
            _download(assets["zip"], zip_path)
            _download(assets["sha"], HOME / "release.sha256", max_bytes=4096)
            import hashlib
            want = (HOME / "release.sha256").read_text().split()[0].strip().lower()
            got = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            if want != got:
                raise RuntimeError("The download did not match the release's checksum.")
            with _lock:
                _state["updating"] = "Installing %s…" % tag
            names = _extract_release(zip_path, staging)
            _check_python(staging, names)
            _install_files(staging, names, tag)
            shutil.rmtree(staging, ignore_errors=True)
            try:
                zip_path.unlink()
                (HOME / "release.sha256").unlink()
            except Exception:
                pass
        with _lock:
            _state["updating"] = "Restarting…"
        sys.stderr.write("bagholder update: %s installed, restarting\n" % tag)
        request_restart()
    except Exception as e:
        with _lock:
            _state["updating"] = ""
            _state["updateError"] = "Update failed: %s" % e
        sys.stderr.write("bagholder update failed: %s\n" % e)


def start_update():
    """Begin the update the page asked for; the work runs in the background."""
    if UPDATES_OFF:
        return {"ok": False, "error": UPDATES_OFF_MESSAGE}
    rec = update_status()
    with _lock:
        if _state.get("updating"):
            return {"ok": True}
        if _state.get("syncing"):
            return {"ok": False, "error": "Wait for the sync to finish, then update."}
        if not rec.get("updateAvailable") or not rec.get("latest"):
            return {"ok": False, "error": "No update to install."}
        if not can_update(rec):
            return {"ok": False, "error": git_update_ready()[1] if update_mode() == "git" else "This release has no downloadable archive."}
        _state["updateError"] = ""
        _state["updating"] = "Updating to %s…" % rec["latest"]
    threading.Thread(target=perform_update, args=(rec["latest"], rec), name="bagholder-update", daemon=True).start()
    return {"ok": True}


def supervise(spawn=None, healthy_sec=UPDATE_HEALTHY_SEC):
    """Run the server as a child and start it again whenever it exits asking to
    be restarted (an update). A restarted server that dies within `healthy_sec`
    of an update gets the previous files put back and is started once more."""
    def default_spawn():
        env = dict(os.environ)
        env["BAGHOLDER_CHILD"] = "1"
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve())], env=env)
    spawn = spawn or default_spawn
    marker = HOME / "update-pending"
    while True:
        child = spawn()
        pending = marker.exists()
        try:
            if pending:
                try:
                    child.wait(timeout=healthy_sec)
                except subprocess.TimeoutExpired:
                    # alive past the window: the update took
                    try:
                        marker.unlink()
                    except Exception:
                        pass
                    shutil.rmtree(HOME / "previous", ignore_errors=True)
                    pending = False
                    child.wait()
            else:
                child.wait()
        except KeyboardInterrupt:
            try:
                child.terminate()
                child.wait(timeout=10)
            except Exception:
                pass
            return 0
        code = child.returncode
        if code == RESTART_CODE:
            continue
        if pending and code != 0:
            try:
                marker.unlink()
            except Exception:
                pass
            if _rollback():
                sys.stderr.write("bagholder update: the new version did not start; the previous one is back\n")
                continue
        return code or 0


def check_for_update_if_due(now=None):
    now = now or datetime.now(timezone.utc)
    rec = update_status()
    try:
        last = datetime.fromisoformat(str(rec.get("checkedAt") or "").replace("Z", "+00:00"))
        if now - last < timedelta(hours=UPDATE_CHECK_HOURS):
            return rec
    except ValueError:
        pass
    return check_for_update(now)


def history_payload(query):
    """Daily bars for one instrument over a date span, fetched and cached on demand."""
    q = parse_qs(query or "")
    one = lambda k: (q.get(k) or [""])[0].strip()
    rec = {"symbol": one("symbol"), "exchange": one("exchange"), "currency": one("currency") or "CAD", "kind": one("kind") or "Shares"}
    start, end = one("from")[:10], one("to")[:10]
    tf = one("tf") or "1d"
    if not rec["symbol"] or len(start) != 10 or len(end) != 10 or tf not in market.TIMEFRAMES:
        return {"ok": False, "error": "symbol, from, to and a known tf are required"}
    inst = market.chart_instrument(rec)
    src = market.history_source(inst)
    available = market.offered_timeframes(inst, start)
    pending = False
    try:
        if not (src and tf in available):
            bars = []
        elif tf in market.INTRADAY_SECONDS and not market.intraday_ready(inst, tf, start):
            # never block the chart on a minute-data fetch: hand back what is stored,
            # fetch the rest in the background, and let the page ask again
            market.ensure_intraday_in_background(inst, tf, start, end, _ssl_context())
            pending = True
            bars = []
        else:
            bars = market.ensure_bars(inst, tf, start, end, _ssl_context())
    except Exception:
        bars = []
    return {"ok": True, "symbol": rec["symbol"], "chartSymbol": inst["symbol"], "source": src[0] if src else "",
            "tf": tf, "available": available, "bars": bars, "pending": pending,
            "reason": "" if bars or pending else market.chart_reason(inst, tf)}


def _model_filters(query):
    raw = (parse_qs(query or "").get("filters") or [""])[0]
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("bagholder %s - %s\n" % (self.address_string(), fmt % args))

    def _local(self):
        if BIND_HOST != "127.0.0.1":
            return True   # bound beyond loopback on purpose (a container); the peer is its bridge
        ip = self.client_address[0]
        return ip in ("127.0.0.1", "::1")

    def _host_ok(self):
        raw = (self.headers.get("Host") or "").strip().lower()
        if not raw or "," in raw:
            return False
        if BIND_HOST != "127.0.0.1":
            # a container's port may be published under another number; the name must still be 127.0.0.1
            return bool(re.fullmatch(r"127\.0\.0\.1:\d{1,5}", raw))
        port = self.server.server_address[1]
        return raw == "127.0.0.1:%s" % port

    def _write_ok(self):
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site == "same-origin":
            return True
        return bool((self.headers.get("X-Bagholder") or "").strip())

    def _gate(self, write=False):
        if not self._local() or not self._host_ok():
            return False
        if write and not self._write_ok():
            return False
        return True

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            raw = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n < 0 or n > 1_048_576:
            return {}
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def do_OPTIONS(self):
        self._send(403, {"ok": False})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html", "/ledger.html", "/v2", "/v2/"):
            if not self._gate():
                self._send(403, {"ok": False})
                return
            p = ledger_path()
            try:
                data = p.read_bytes()
            except OSError:
                self._send(404, {"ok": False, "error": "ledger.html missing"})
                return
            self._send(200, data, "text/html; charset=utf-8")
            return
        if path == "/api/status":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            self._send(200, status_payload())
            return
        if path == "/api/history":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            self._send(200, history_payload(self.path.split("?", 1)[1] if "?" in self.path else ""))
            return
        if path == "/lightweight-charts.js":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            lib = Path(__file__).resolve().parent / "lightweight-charts.js"
            try:
                data = lib.read_bytes()
            except OSError:
                self._send(404, {"ok": False, "error": "lightweight-charts.js missing"})
                return
            self._send(200, data, "application/javascript; charset=utf-8")
            return
        if path == "/api/watch":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            self._send(200, csvimport.status())
            return
        if path == "/api/data":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            summary = store.data_summary()
            summary["ok"] = True
            summary["sessionPresent"] = bool(load_session())
            self._send(200, summary)
            return
        if path == "/api/model":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            try:
                if market.is_stale(symbols=_payer_symbols()):
                    threading.Thread(target=refresh_market_data, name="bagholder-market", daemon=True).start()
                elif market.quote_symbols_needing_refresh(model.held_symbols()):
                    threading.Thread(target=refresh_quotes, name="bagholder-quotes", daemon=True).start()
            except Exception:
                pass
            try:
                payload = model.view(_model_filters(query))
            except Exception as e:
                sys.stderr.write("model failed: %r\n" % (e,))
                self._send(500, {"ok": False, "error": "model failed: %s" % type(e).__name__})
                return
            payload["status"] = status_payload()
            self._send(200, payload)
            return
        if path in ("/favicon.png", "/favicon.ico"):
            if not self._gate():
                self._send(403, {"ok": False})
                return
            icon = Path(__file__).resolve().parent / "favicon.png"
            try:
                data = icon.read_bytes()
            except OSError:
                self._send(404, {"ok": False, "error": "favicon missing"})
                return
            self._send(200, data, "image/png")
            return
        if path == "/api/book":
            if not self._gate():
                self._send(403, {"ok": False})
                return
            book = load_book()
            self._send(
                200,
                {
                    "ok": True,
                    "activities": book.get("activities") or [],
                    "accounts": book.get("accounts") or [],
                    "balances": book.get("balances") or [],
                    "navHistory": book.get("navHistory") or [],
                    "navByAccount": book.get("navByAccount") or {},
                    "syncedAt": book.get("syncedAt") or "",
                    "tradeGroups": book.get("tradeGroups") or [],
                    "notes": book.get("notes") or {},
                    "securities": book.get("securities") or [],
                },
            )
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if not self._gate(write=True):
            self._send(403, {"ok": False})
            return
        if path == "/api/login/start":
            self._read_json()
            result = start_login_browser()
            self._send(200 if result.get("ok") else 200, result)
            return
        if path == "/api/login/cancel":
            self._read_json()
            self._send(200, cancel_login())
            return
        if path == "/api/update":
            self._read_json()
            self._send(200, start_update())
            return
        if path == "/api/capture":
            body = self._read_json()
            result = capture_tokens(body)
            self._send(200, result)
            return
        if path == "/api/refresh":
            self._read_json()
            result = refresh_now()
            self._send(200, result)
            return
        if path == "/api/sync":
            self._read_json()
            sess = load_session()
            if not sess:
                self._send(200, {"ok": False, "error": "not connected"})
                return
            with _lock:
                _state["error"] = ""
            threading.Thread(target=sync_then_market, name="bagholder-sync", daemon=True).start()
            self._send(200, {"ok": True, "syncing": True})
            return
        if path == "/api/data/clear":
            body = self._read_json()
            body = body if isinstance(body, dict) else {}
            with _lock:
                if _state["syncing"]:
                    self._send(409, {"ok": False, "error": "A sync is running. Wait for it to finish."})
                    return
            summary = store.clear_synced_data(
                keep_journal=not bool(body.get("journal")),
                keep_market=not bool(body.get("market")),
            )
            if body.get("session"):
                delete_session_and_book()
            with _lock:
                _state["lastSync"] = ""
                _state["error"] = ""
            model.invalidate()
            summary["ok"] = True
            summary["sessionPresent"] = bool(load_session())
            self._send(200, summary)
            return
        if path == "/api/journal":
            body = self._read_json()
            if not isinstance(body, dict) or not _s(body.get("id")).strip():
                self._send(400, {"ok": False, "error": "id required"})
                return
            entries = store.save_journal_entry(
                body.get("id"),
                {
                    "thesis": body.get("thesis"),
                    "tags": body.get("tags"),
                    "grade": body.get("grade"),
                },
            )
            model.apply_journal(entries)
            self._send(200, {"ok": True, "journal": entries})
            return
        if path == "/api/disconnect":
            self._read_json()
            delete_session_and_book()
            self._send(200, {"ok": True})
            return
        if path == "/api/book/append":
            body = self._read_json()
            result = append_manual(body)
            model.invalidate()
            self._send(200, result)
            return
        if path == "/api/import":
            body = self._read_json()
            body = body if isinstance(body, dict) else {}
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                self._send(400, {"ok": False, "error": "text required"})
                return
            report = csvimport.import_text(_s(body.get("name")) or "upload.csv", text)
            if report.get("added"):
                model.invalidate()
            self._send(200, report)
            return
        if path == "/api/watch":
            body = self._read_json()
            body = body if isinstance(body, dict) else {}
            set_result = csvimport.set_watch_folder(body.get("path"))
            if not set_result.get("ok"):
                self._send(400, set_result)
                return
            result = csvimport.scan_folder(force=True)
            if result.get("added"):
                model.invalidate()
            result["status"] = csvimport.status()
            self._send(200, result)
            return
        if path == "/api/watch/scan":
            self._read_json()
            result = csvimport.scan_folder(force=True)
            if result.get("ok") and result.get("added"):
                model.invalidate()
            result["status"] = csvimport.status()
            self._send(200 if result.get("ok") else 400, result)
            return
        if path == "/api/watch/clear":
            self._read_json()
            csvimport.clear_watch_folder()
            self._send(200, csvimport.status())
            return
        if path == "/api/groups":
            body = self._read_json()
            groups = store.save_trade_groups(body.get("groups") if isinstance(body, dict) else [])
            self._send(200, {"ok": True, "groups": groups})
            return
        if path == "/api/notes":
            body = self._read_json()
            notes = store.save_trade_notes(body.get("notes") if isinstance(body, dict) else {})
            self._send(200, {"ok": True, "notes": notes})
            return
        self._send(404, {"ok": False, "error": "not found"})



def refresh_now():
    """Token POST only. Always POST, even if expiry is not near."""
    sess = load_session()
    if not sess or not sess.get("refresh_token"):
        with _lock:
            _state["connected"] = False
            _state["error"] = "not connected"
        return {"ok": False, "error": "not connected", "connected": False}
    ok = refresh_session(sess)
    with _lock:
        _state["connected"] = bool(ok)
        if ok:
            _state["error"] = ""
        err = (_state.get("error") or "").strip()
    return {"ok": bool(ok), "error": err, "connected": bool(ok)}


def auto_sync_loop():
    delay = TOKEN_CHECK_SEC
    fail_delay = TOKEN_CHECK_SEC
    while not _stop.wait(delay):
        sess = load_session()
        if sess and sess.get("refresh_token"):
            try:
                ensure_fresh_token(sess)
            except Exception:
                pass
        with _lock:
            connected = _state["connected"]
            syncing = _state["syncing"]
        if connected and not syncing and store.activity_pull_due(interval_sec=ACTIVITY_PULL_SEC):
            try:
                ok = run_sync(force_activity=True)
            except Exception:
                ok = False
            refresh_market_data()
            fail_delay = TOKEN_CHECK_SEC if ok else min(max(fail_delay, TOKEN_CHECK_SEC) * 2, 1800)
            delay = fail_delay
        else:
            delay = TOKEN_CHECK_SEC
            fail_delay = TOKEN_CHECK_SEC


def port_choices():
    """The ports to try: BAGHOLDER_PORT when set (a second instance for testing
    beside the live app), else the usual three."""
    env = (os.environ.get("BAGHOLDER_PORT") or "").strip()
    if env.isdigit() and 1024 <= int(env) <= 65535:
        return (int(env),)
    return PORTS


def bind_server():
    last = None
    for port in port_choices():
        try:
            httpd = ThreadingHTTPServer((BIND_HOST, port), Handler)
            return httpd, port
        except OSError as e:
            last = e
            continue
    raise SystemExit("Could not bind %s:%s (%s)" % (BIND_HOST, "-".join(str(p) for p in port_choices()), last))


def main():
    global _httpd
    _ensure_home()
    store.ensure()
    boot_session()
    httpd, port = bind_server()
    _httpd = httpd
    t = threading.Thread(target=auto_sync_loop, name="bagholder-auto-sync", daemon=True)
    t.start()
    threading.Thread(target=refresh_market_data, name="bagholder-market", daemon=True).start()
    threading.Thread(target=check_for_update, name="bagholder-update-check", daemon=True).start()
    threading.Thread(target=quote_loop, name="bagholder-quote-loop", daemon=True).start()
    threading.Thread(target=portfolio_loop, name="bagholder-portfolio-loop", daemon=True).start()
    threading.Thread(target=market_loop, name="bagholder-market-loop", daemon=True).start()
    threading.Thread(target=archive_loop, name="bagholder-archive", daemon=True).start()
    threading.Thread(target=watch_loop, name="bagholder-watch", daemon=True).start()
    url = "http://127.0.0.1:%s" % port
    print("Bagholder  %s" % url, flush=True)
    # A second instance run for verification (BAGHOLDER_NO_BROWSER=1) must not open
    # anyone's browser: the user's own copy is what they are looking at.
    if not (os.environ.get("BAGHOLDER_NO_BROWSER") or "").strip():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    if _state.get("connected"):
        if store.activity_pull_due(interval_sec=ACTIVITY_PULL_SEC):
            threading.Thread(target=run_sync, name="bagholder-boot-sync", daemon=True).start()
        else:
            threading.Thread(
                target=fill_listings,
                args=(load_session(),),
                name="bagholder-listings",
                daemon=True,
            ).start()
    # a container stops its process with SIGTERM, which PID 1 would otherwise ignore: same exit as Ctrl-C
    def _on_sigterm(*_):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBagholder stopped.", flush=True)
    finally:
        _stop.set()
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    if _exit_code[0]:
        sys.exit(_exit_code[0])


def connect_cli():
    """`bagholder.py --connect`: sign in on this machine for a copy that runs elsewhere
    (a container). The Chrome window opens here, the login lands in HOME/session.json,
    and the command exits; that folder is what the container mounts as its data."""
    _ensure_home()
    store.ensure()
    res = start_login_browser()
    if not res.get("ok"):
        sys.stderr.write("bagholder: %s\n" % (res.get("error") or "could not open the login"))
        return 1
    print("Sign in to Wealthsimple in the Chrome window…", flush=True)
    deadline = time.time() + CAPTURE_WAIT_SEC + 15
    try:
        while time.time() < deadline:
            with _lock:
                connected = bool(_state.get("connected"))
                capturing = bool(_state.get("capturing"))
                error = str(_state.get("error") or "")
            if connected:
                print("Signed in. The login is saved in %s" % SESSION_PATH, flush=True)
                return 0
            if not capturing:
                sys.stderr.write("bagholder: %s\n" % (error or "no session was captured"))
                return 1
            time.sleep(1)
        sys.stderr.write("bagholder: no session yet; run it again and finish the login sooner\n")
        return 1
    finally:
        _close_login_browser()


def cli_mode(argv):
    """'connect' for `--connect`, 'serve' otherwise; anything else is a usage error."""
    args = [a for a in argv[1:] if a.strip()]
    if not args:
        return "serve"
    if args == ["--connect"]:
        return "connect"
    raise SystemExit("usage: python3 bagholder.py [--connect]")


if __name__ == "__main__":
    mode = cli_mode(sys.argv)
    if mode == "connect":
        sys.exit(connect_cli())
    elif os.environ.get("BAGHOLDER_CHILD") == "1" or UPDATES_OFF:
        # the supervisor exists to restart an updated server; a copy that never updates runs plain
        main()
    else:
        sys.exit(supervise())
