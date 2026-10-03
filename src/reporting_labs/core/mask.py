"""Masks secrets in text and data. A port of src/mask.ts from the Node.js reporter (0.6.9).

Keep in step with mask.ts: the same default keys, value patterns, key rule (case-insensitive substring),
learned values and CSV parser.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable, List, Optional, Set

DEFAULT_KEYS = [
    "password", "passwd", "pwd", "secret", "token", "apikey", "api_key", "api-key", "authorization",
    "auth", "cookie", "set-cookie", "session", "credential", "private", "ssn", "cvv", "card",
]

# Values that are secrets on their own, whatever the surrounding text.
VALUE_PATTERNS = [
    re.compile(r"\b(Bearer|Basic|Digest|Token)\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),            # JWT
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test)?[-_]?[A-Za-z0-9]{12,}\b"),                   # Stripe-style keys
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),                             # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),                                           # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                                      # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),                                                # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}\b"),                                              # Google OAuth token
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),                                              # GitLab
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"),                                                  # npm
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),                            # SendGrid
]

# 13 to 19 digits, spaces or dashes between groups allowed; masked only when the Luhn check passes.
CARD_NUMBER = re.compile(r"(?<![\w.-])\d(?:[ -]?\d){12,18}(?![\w.-])")


def luhn(s: str) -> bool:
    total, dbl, digits = 0, False, 0
    for c in reversed(s):
        if not c.isdigit():
            continue
        d = ord(c) - 48
        digits += 1
        if dbl:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        dbl = not dbl
    return digits >= 13 and total % 10 == 0


# Auth schemes and placeholders that follow a sensitive key but are not the secret.
NOT_A_VALUE = {"bearer", "basic", "digest", "token", "undefined", "redacted", "hidden", "secret", "password"}

# Words after "password is ..." that are plainly not a secret.
NOT_A_SECRET = {
    "valid", "invalid", "visible", "hidden", "required", "optional", "missing", "empty", "null", "undefined", "none",
    "correct", "incorrect", "wrong", "right", "expired", "set", "unset", "not", "present", "absent", "ok", "true", "false",
    "masked", "blank", "too", "the", "a", "an", "same", "different", "changed", "unchanged", "shown", "displayed",
    "accepted", "rejected", "weak", "strong",
}

MASK = "****"
MAX_LEARNED = 500
_WORD = re.compile(r"[^a-z0-9]")


class Masker:
    """Masks secrets in strings and nested data. One instance per run; it learns values as it goes."""

    def __init__(self, extra_keys: Iterable[str] = (), known_values: Iterable[str] = (), from_env: bool = True,
                 environ: Optional[dict] = None) -> None:
        extra = [str(k) for k in extra_keys]
        self.keys: List[str] = DEFAULT_KEYS + [k.lower() for k in extra]
        self._learned: Set[str] = set()
        self._learned_re: Optional[re.Pattern] = None
        self._dirty = False
        esc = re.escape
        # Key names as they appear in free text: password, X-Api-Key, access_token, userPassword, "password", db.password...
        # `auth`, `otp`, `pin`... are matched as whole words only, so "author" or "pinned" stay untouched.
        compound = ["password", "passwort", "passwd", "pwd", "passcode", "secret", "token", "api[ _-]?key", "cookie",
                    "credentials?", "private[ _-]?key", "access[ _-]?key", "session[ _-]?id", "(?<![A-Za-z])auth(?![A-Za-z])",
                    *[esc(k) for k in extra]]
        exact = ["authorization", "pass", "pw", "otp", "pin", "cvv", "ssn"]
        key = "(?:[\\w.-]*?(?:" + "|".join(compound) + ")[\\w.-]*|" + "|".join(exact) + ")"
        # key = value | key: value | "key": "value" | key => value | key -> value   (value runs to a delimiter; a closing quote stays)
        self._kv = re.compile(r"([\"']?)\b(" + key + r")\b([\"']?)(\s*(?:=>|->|[=:])\s*)([\"']?)([^\"'\s&;,}\])]+)", re.I)
        spoken_keys = ["password", "passwort", "passwd", "pwd", "pass", "passcode", "secret", "token", "api[ _-]?key",
                       "access[ _-]?key", "otp", "pin", "cvv", *[esc(k) for k in extra]]
        # "password is x", "password for user admin is x", "token: x", "the token is: x", "with pwd x"
        self._spoken = re.compile(
            r"\b(" + "|".join(spoken_keys) + r")(s?\b(?:\s+for\s+(?:\S+\s+){1,3}?(?:[:=]|(?:is|was)\b)\s*|\s*[:=]?\s*(?:(?:is|was|of|as)\b\s*)?[:=]?\s*)['\"]?)((?=[A-Za-z0-9])[^\s'\",;]+)",
            re.I)
        self._mentions_secret = re.compile(r"\b(?:" + "|".join(spoken_keys) + r")s?\b", re.I)
        for v in known_values:
            self.learn(v, 4)
        if from_env:
            # PASSWORD=…, API_TOKEN=…, OAUTH_CLIENT_SECRET=… in the environment: the values a CI job injects are the
            # ones that end up in log lines. Short values are skipped so a plain word is not blanked everywhere.
            try:
                for k, v in (environ if environ is not None else os.environ).items():
                    if self.is_sensitive(k):
                        self.learn(v, 6)
            except Exception:
                pass

    # user:password@host in a URL, curl -u user:password, "credentials admin:x"
    _URL_USERINFO = re.compile(r"(://[^\s/:@]+:)([^\s@]+)(@)")
    _CLI_USER = re.compile(r"((?:^|\s)(?:-u|--user|--username|--credentials?)\s+[^\s:]+:)(\S+)")
    _CREDS_PAIR = re.compile(r"\b(credentials?|creds|login)(\s*[:=]?\s+[^\s:'\"]+:)([^\s'\",;]+)", re.I)
    # The value comes first: "Typed s3cret into password field", "Entered x in #password"
    _VALUE_THEN_KEY = re.compile(r"([^\s'\"(]+)(\s+(?:into|in|to|for|as)\s+(?:the\s+)?['\"#]?[\w-]*?(?:password|passwd|pwd|secret|token|otp|pin)\b)", re.I)
    # Assertion output: when the text talks about a password/token/secret, the compared values are that secret.
    _COMPARED = re.compile(r"\b(Expected|Received|Actual|expected|received|actual|got)(\s*[:=]\s*)([\"'“]?)([^\"'”\s]+)")
    _SCHEME = re.compile(r"^(Bearer|Basic|Digest|Token)\s", re.I)
    _PLAIN = re.compile(r"^[A-Za-z0-9_]+$")

    def is_sensitive(self, key: str) -> bool:
        low = str(key).lower()
        return any(low == s or s in low for s in self.keys)

    def learn(self, value: Any, min_length: int = 4) -> None:
        if not isinstance(value, str):
            return
        v = value.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        if len(v) < min_length or "***" in v or not re.search(r"[A-Za-z0-9]", v) or len(self._learned) >= MAX_LEARNED:
            return
        word = _WORD.sub("", v.lower())
        if word in NOT_A_SECRET or word in NOT_A_VALUE:
            return
        if v not in self._learned:
            self._learned.add(v)
            self._dirty = True

    def _learned_pattern(self) -> Optional[re.Pattern]:
        if not self._dirty:
            return self._learned_re
        vals = sorted(self._learned, key=len, reverse=True)   # longest first
        parts = [(r"(?<![A-Za-z0-9_])" + re.escape(v) + r"(?![A-Za-z0-9_])") if self._PLAIN.match(v) else re.escape(v) for v in vals]
        self._learned_re = re.compile("|".join(parts)) if parts else None
        self._dirty = False
        return self._learned_re

    @staticmethod
    def _looks_secret(v: str) -> bool:
        if re.search(r"\s", v):
            return False
        return bool((re.search(r"\d", v) and len(v) >= 4) or (re.search(r"[^A-Za-z0-9]", v) and len(v) >= 6)
                    or (re.search(r"[a-z][A-Z]|[A-Z][a-z].*[A-Z]", v) and len(v) >= 8))

    def mask_str(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        s = CARD_NUMBER.sub(lambda m: MASK if luhn(m.group(0)) else m.group(0), text)

        def value_pattern(m: "re.Match[str]") -> str:
            whole = m.group(0)
            if self._SCHEME.match(whole):
                i = re.search(r"\s", whole).start()
                self.learn(whole[i:].strip())
                return whole[:i] + " " + MASK
            self.learn(whole)
            return MASK

        for pat in VALUE_PATTERNS:
            s = pat.sub(value_pattern, s)

        def userinfo(m):
            self.learn(m.group(2))
            return m.group(1) + MASK + m.group(3)

        def cli(m):
            self.learn(m.group(2))
            return m.group(1) + MASK

        def creds(m):
            self.learn(m.group(3))
            return m.group(1) + m.group(2) + MASK

        def kv(m):
            self.learn(m.group(6))
            return m.group(1) + m.group(2) + m.group(3) + m.group(4) + m.group(5) + MASK

        s = self._URL_USERINFO.sub(userinfo, s)
        s = self._CLI_USER.sub(cli, s)
        s = self._CREDS_PAIR.sub(creds, s)
        s = self._kv.sub(kv, s)

        def spoken(m):
            key, between, value = m.group(1), m.group(2), m.group(3)
            word = _WORD.sub("", value.lower())
            if word in NOT_A_SECRET or "*" in value:
                return m.group(0)
            explicit = bool(re.search(r"\b(is|was|of|as)\b|['\"]$|[:=]\s*$", between))
            if explicit or self._looks_secret(value):
                self.learn(value)
                return key + between + MASK
            return m.group(0)

        s = self._spoken.sub(spoken, s)

        def value_then_key(m):
            value, rest = m.group(1), m.group(2)
            word = _WORD.sub("", value.lower())
            if word in NOT_A_SECRET or "*" in value or not self._looks_secret(value):
                return m.group(0)
            self.learn(value)
            return MASK + rest

        s = self._VALUE_THEN_KEY.sub(value_then_key, s)

        if self._mentions_secret.search(s):
            def compared(m):
                value = m.group(4)
                if not self._looks_secret(value):
                    return m.group(0)
                self.learn(value)
                return m.group(1) + m.group(2) + m.group(3) + MASK

            s = self._COMPARED.sub(compared, s)
        known = self._learned_pattern()
        if known:
            s = known.sub(MASK, s)
        return s

    def mask(self, value: Any, key: str = "") -> Any:
        if key and self.is_sensitive(key):
            self.learn(value)
            return MASK
        if isinstance(value, str):
            return self.mask_str(value)
        if isinstance(value, (list, tuple)):
            return [self.mask(x) for x in value]
        if isinstance(value, dict):
            return {str(k): self.mask(x, str(k)) for k, x in value.items()}
        return value


def parse_csv(text: str):
    """The same small CSV reader as mask.ts: quotes toggle, commas split, cells are trimmed."""
    lines = [line for line in text.replace("\r", "").split("\n") if line.strip()]

    def split(line: str) -> List[str]:
        out: List[str] = []
        cur, quoted = "", False
        for c in line:
            if c == '"':
                quoted = not quoted
            elif c == "," and not quoted:
                out.append(cur)
                cur = ""
            else:
                cur += c
        out.append(cur)
        return [s.strip() for s in out]

    rows = [split(line) for line in lines]
    if not rows:
        return [], []
    return rows[0], rows[1:]
