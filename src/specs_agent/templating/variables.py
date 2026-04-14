"""Built-in template variables -- Postman-style {{variable}} expansion.

Supports variables like:
  {{$guid}}          Random UUID
  {{$randomInt}}     Random integer 1-1000
  {{$randomEmail}}   Random email
  {{$randomName}}    Random full name
  {{$randomFirstName}}
  {{$randomLastName}}
  {{$randomUserName}}
  {{$randomPhone}}
  {{$randomWord}}
  {{$randomWords}}
  {{$randomSentence}}
  {{$randomUrl}}
  {{$randomIP}}
  {{$randomIPv6}}
  {{$randomHex}}     Random 16-char hex
  {{$randomColor}}   Random hex color
  {{$randomBoolean}}
  {{$randomFloat}}   Random float 0-100
  {{$randomDate}}    Random date YYYY-MM-DD
  {{$randomDatetime}}
  {{$timestamp}}     Current Unix timestamp
  {{$isoTimestamp}}  Current ISO 8601
  {{$randomCompany}}
  {{$randomJobTitle}}
  {{$randomCountry}}
  {{$randomCity}}
  {{$randomStreet}}
  {{$randomZip}}
  {{$randomCreditCard}}
  {{$randomCurrency}}
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from faker import Faker

_fake = Faker()

# Pattern: {{$variableName}} or {{variableName}}
_VAR_PATTERN = re.compile(r"\{\{\s*\$?(\w+)\s*\}\}")

# Registry of built-in variable generators
_GENERATORS: dict[str, callable] = {}


def _register(name: str, *aliases: str):
    """Decorator to register a variable generator."""
    def decorator(fn):
        _GENERATORS[name.lower()] = fn
        for alias in aliases:
            _GENERATORS[alias.lower()] = fn
        return fn
    return decorator


# ── Identity / UUID ──────────────────────────────────────────────────────────

@_register("guid", "uuid", "randomuuid", "randomguid", "random_guid", "random_uuid")
def _guid():
    return str(uuid.uuid4())


# ── Numbers ──────────────────────────────────────────────────────────────────

@_register("randomint", "random_int", "randominteger")
def _random_int():
    return _fake.random_int(min=1, max=1000)


@_register("randomfloat", "random_float")
def _random_float():
    return round(_fake.pyfloat(min_value=0, max_value=100, right_digits=2), 2)


@_register("randomboolean", "random_boolean", "randombool")
def _random_boolean():
    return _fake.boolean()


# ── Strings / Text ───────────────────────────────────────────────────────────

@_register("randomword", "random_word")
def _random_word():
    return _fake.word()


@_register("randomwords", "random_words")
def _random_words():
    return " ".join(_fake.words(nb=3))


@_register("randomsentence", "random_sentence")
def _random_sentence():
    return _fake.sentence()


@_register("randomhex", "random_hex")
def _random_hex():
    return _fake.hexify(text="^^^^^^^^^^^^^^^^")


@_register("randomcolor", "random_color", "randomhexcolor")
def _random_color():
    return _fake.hex_color()


# ── Person ───────────────────────────────────────────────────────────────────

@_register("randomname", "random_name", "randomfullname")
def _random_name():
    return _fake.name()


@_register("randomfirstname", "random_first_name")
def _random_first_name():
    return _fake.first_name()


@_register("randomlastname", "random_last_name")
def _random_last_name():
    return _fake.last_name()


@_register("randomusername", "random_user_name")
def _random_username():
    return _fake.user_name()


@_register("randomemail", "random_email")
def _random_email():
    return _fake.email()


@_register("randomphone", "random_phone", "randomphonenumber")
def _random_phone():
    return _fake.phone_number()


# ── Network ──────────────────────────────────────────────────────────────────

@_register("randomurl", "random_url")
def _random_url():
    return _fake.url()


@_register("randomip", "random_ip", "randomipv4")
def _random_ip():
    return _fake.ipv4()


@_register("randomipv6", "random_ipv6")
def _random_ipv6():
    return _fake.ipv6()


# ── Date / Time ──────────────────────────────────────────────────────────────

@_register("timestamp", "unixtimestamp")
def _timestamp():
    return int(time.time())


@_register("isotimestamp", "iso_timestamp", "now")
def _iso_timestamp():
    return datetime.now(timezone.utc).isoformat()


@_register("randomdate", "random_date")
def _random_date():
    return _fake.date()


@_register("randomdatetime", "random_datetime")
def _random_datetime():
    return _fake.iso8601()


# ── Business ─────────────────────────────────────────────────────────────────

@_register("randomcompany", "random_company")
def _random_company():
    return _fake.company()


@_register("randomjobtitle", "random_job_title", "randomjob")
def _random_job_title():
    return _fake.job()


# ── Address ──────────────────────────────────────────────────────────────────

@_register("randomcountry", "random_country")
def _random_country():
    return _fake.country()


@_register("randomcity", "random_city")
def _random_city():
    return _fake.city()


@_register("randomstreet", "random_street", "randomaddress")
def _random_street():
    return _fake.street_address()


@_register("randomzip", "random_zip", "randomzipcode", "randompostcode")
def _random_zip():
    return _fake.zipcode()


# ── Finance ──────────────────────────────────────────────────────────────────

@_register("randomcreditcard", "random_credit_card", "randomcc")
def _random_credit_card():
    return _fake.credit_card_number()


@_register("randomcurrency", "random_currency", "randomcurrencycode")
def _random_currency():
    return _fake.currency_code()


# ── Public API ───────────────────────────────────────────────────────────────

def list_variables() -> list[dict[str, str]]:
    """Return a list of all available template variables with examples."""
    seen: set[int] = set()
    result: list[dict[str, str]] = []
    for name, fn in sorted(_GENERATORS.items()):
        fn_id = id(fn)
        if fn_id in seen:
            continue
        seen.add(fn_id)
        # Find all aliases for this function
        aliases = sorted(k for k, v in _GENERATORS.items() if v is fn)
        example = fn()
        result.append({
            "name": aliases[0],
            "aliases": ", ".join(f"{{{{${a}}}}}" for a in aliases),
            "example": str(example),
        })
    return result


def resolve_string(text: str) -> str:
    """Replace all {{$var}} or {{var}} placeholders in a string."""
    def _replace(match: re.Match) -> str:
        var_name = match.group(1).lower()
        gen = _GENERATORS.get(var_name)
        if gen:
            return str(gen())
        return match.group(0)  # Leave unresolved vars as-is

    return _VAR_PATTERN.sub(_replace, text)


def resolve_value(value: Any) -> Any:
    """Recursively resolve template variables in any value.

    Handles strings, dicts, lists, and nested structures.
    Non-string leaf values are returned as-is.
    """
    if isinstance(value, str):
        resolved = resolve_string(value)
        # If the entire string was a single variable, try to return native type
        if resolved != value and _VAR_PATTERN.fullmatch(value.strip()):
            # The original was a single {{var}}, return the native type
            var_name = _VAR_PATTERN.match(value.strip()).group(1).lower()
            gen = _GENERATORS.get(var_name)
            if gen:
                return gen()
        return resolved

    if isinstance(value, dict):
        return {k: resolve_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [resolve_value(item) for item in value]

    return value
