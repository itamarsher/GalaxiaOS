"""Namecheap registrar adapter — REAL domain purchase (credential-gated).

Availability uses RDAP (free); registration calls the Namecheap
``namecheap.domains.create`` API. Credentials and the registrant contact come
from settings (``ABOS_NAMECHEAP_*``); without them, :meth:`register` raises
:class:`RegistrarError` rather than attempting a charge.

⚠️  This performs a REAL purchase and has not been exercised against the live
API in this repo. Verify against the Namecheap **sandbox**
(``ABOS_NAMECHEAP_SANDBOX=true``) before enabling in production, and confirm the
contact fields your account requires. It is off by default
(``ABOS_DOMAIN_REGISTRAR=simulated``).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.config import settings
from app.integrations import _pricing
from app.integrations.availability import rdap_available
from app.integrations.base import DomainQuote, DomainRegistration, RegistrarError

_SANDBOX_URL = "https://api.sandbox.namecheap.com/xml.response"
_PROD_URL = "https://api.namecheap.com/xml.response"

# Namecheap domains.create requires four contact roles; we reuse one contact.
_CONTACT_ROLES = ("Registrant", "Tech", "Admin", "AuxBilling")
_CONTACT_FIELDS = (
    "FirstName",
    "LastName",
    "Address1",
    "City",
    "StateProvince",
    "PostalCode",
    "Country",
    "Phone",
    "EmailAddress",
)


def _local(tag: str) -> str:
    """Strip the XML namespace from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


class NamecheapRegistrar:
    def _require_credentials(self) -> dict[str, str]:
        creds = {
            "ApiUser": settings.namecheap_api_user,
            "ApiKey": settings.namecheap_api_key,
            "UserName": settings.namecheap_username,
            "ClientIp": settings.namecheap_client_ip,
        }
        missing = [k for k, v in creds.items() if not v]
        if missing:
            raise RegistrarError(
                f"Namecheap credentials missing: {', '.join(missing)} "
                "(set ABOS_NAMECHEAP_* env vars)."
            )
        return creds

    async def _call(self, params: dict[str, str]) -> ET.Element:
        """GET the Namecheap API and return the parsed, status-checked root.

        Raises :class:`RegistrarError` on a network error, non-XML body, or a
        non-OK API status (surfacing the vendor error messages).
        """
        url = _SANDBOX_URL if settings.namecheap_sandbox else _PROD_URL
        try:
            async with httpx.AsyncClient(timeout=settings.rdap_timeout_seconds * 3) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RegistrarError(f"Namecheap request failed: {exc}") from exc
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            raise RegistrarError(f"Namecheap returned non-XML: {exc}") from exc
        if root.attrib.get("Status") != "OK":
            errors = [e.text or "" for e in root.iter() if _local(e.tag) == "Error"]
            raise RegistrarError(f"Namecheap error: {'; '.join(errors) or 'unknown'}")
        return root

    async def check(self, domain: str) -> DomainQuote:
        if not _pricing.is_registrable(domain):
            return DomainQuote(domain=domain, available=False, price_cents=0)
        available = await rdap_available(domain, timeout=settings.rdap_timeout_seconds)
        if available is not True:
            return DomainQuote(domain=domain, available=False, price_cents=0)
        return DomainQuote(domain=domain, available=True, price_cents=_pricing.price_cents(domain))

    async def balance_cents(self) -> int:
        """Available account balance in cents (``namecheap.users.getBalances``).

        The Namecheap API spends from this balance; checking it first lets a
        purchase fail loudly *before* the irreversible create call.
        """
        params = self._require_credentials()
        params["Command"] = "namecheap.users.getBalances"
        root = await self._call(params)
        # Parse by attribute (not a guessed element name): the result element
        # carries an ``AvailableBalance`` attribute.
        for el in root.iter():
            raw = el.attrib.get("AvailableBalance")
            if raw is not None:
                try:
                    return round(float(raw) * 100)
                except ValueError as exc:
                    raise RegistrarError(f"Namecheap returned a bad balance: {raw!r}") from exc
        raise RegistrarError("Namecheap response missing AvailableBalance")

    async def create_add_funds_request(self, amount_cents: int, return_url: str) -> str:
        """Start a credit-card top-up and return the hosted ``RedirectURL``.

        Namecheap funds an account through a hosted page where the card is
        entered (its API never charges a raw card); this returns that URL so a
        Stripe Issuing card can fund the balance the registrar then draws down.
        """
        params = self._require_credentials()
        params.update(
            {
                "Command": "namecheap.users.createaddfundsrequest",
                "Username": params["UserName"],
                "PaymentType": "Creditcard",
                "Amount": f"{amount_cents / 100:.2f}",
                "ReturnURL": return_url,
            }
        )
        root = await self._call(params)
        # The result element carries a ``RedirectURL`` attribute (hosted card-entry
        # page); match on the attribute rather than a guessed element name.
        for el in root.iter():
            url = el.attrib.get("RedirectURL")
            if url:
                return url
        raise RegistrarError("Namecheap add-funds response missing RedirectURL")

    async def register(self, domain: str) -> DomainRegistration:
        params = self._require_credentials()
        contact = settings.namecheap_contact or {}
        missing_contact = [f for f in _CONTACT_FIELDS if not contact.get(f)]
        if missing_contact:
            raise RegistrarError(
                f"Namecheap contact fields missing: {', '.join(missing_contact)} "
                "(set ABOS_NAMECHEAP_CONTACT as JSON)."
            )

        # Fail before the irreversible create when the balance can't cover it.
        if settings.namecheap_precheck_balance:
            need = _pricing.price_cents(domain)
            available = await self.balance_cents()
            if available < need:
                raise RegistrarError(
                    f"insufficient Namecheap balance: ${available / 100:.2f} available, "
                    f"need ~${need / 100:.2f} for {domain} — top up the account "
                    "(create_add_funds_request) before registering."
                )

        params.update({"Command": "namecheap.domains.create", "DomainName": domain, "Years": "1"})
        for role in _CONTACT_ROLES:
            for field in _CONTACT_FIELDS:
                params[f"{role}{field}"] = str(contact[field])

        url = _SANDBOX_URL if settings.namecheap_sandbox else _PROD_URL
        try:
            async with httpx.AsyncClient(timeout=settings.rdap_timeout_seconds * 3) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RegistrarError(f"Namecheap request failed: {exc}") from exc

        return self._parse_create_response(domain, resp.text)

    async def set_nameservers(self, domain: str, nameservers: list[str]) -> None:
        """Point ``domain`` at custom nameservers via ``domains.dns.setCustom``."""
        if not nameservers:
            raise RegistrarError("no nameservers given for delegation")
        sld, _, tld = domain.partition(".")
        if not sld or not tld:
            raise RegistrarError(f"cannot parse SLD/TLD from {domain!r}")
        params = self._require_credentials()
        params.update(
            {
                "Command": "namecheap.domains.dns.setCustom",
                "SLD": sld,
                "TLD": tld,
                "Nameservers": ",".join(nameservers),
            }
        )
        url = _SANDBOX_URL if settings.namecheap_sandbox else _PROD_URL
        try:
            async with httpx.AsyncClient(timeout=settings.rdap_timeout_seconds * 3) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RegistrarError(f"Namecheap request failed: {exc}") from exc

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            raise RegistrarError(f"Namecheap returned non-XML: {exc}") from exc
        if root.attrib.get("Status") != "OK":
            errors = [e.text or "" for e in root.iter() if _local(e.tag) == "Error"]
            raise RegistrarError(f"Namecheap error: {'; '.join(errors) or 'unknown'}")

    def _parse_create_response(self, domain: str, body: str) -> DomainRegistration:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise RegistrarError(f"Namecheap returned non-XML: {exc}") from exc

        if root.attrib.get("Status") != "OK":
            errors = [e.text or "" for e in root.iter() if _local(e.tag) == "Error"]
            raise RegistrarError(f"Namecheap error: {'; '.join(errors) or 'unknown'}")

        for el in root.iter():
            if _local(el.tag) == "DomainCreateResult":
                if el.attrib.get("Registered", "").lower() != "true":
                    raise RegistrarError(f"Namecheap did not register {domain}")
                charged = el.attrib.get("ChargedAmount")
                price_cents = (
                    round(float(charged) * 100) if charged else _pricing.price_cents(domain)
                )
                ref = el.attrib.get("OrderID") or el.attrib.get("TransactionID") or domain
                return DomainRegistration(
                    domain=domain, price_cents=price_cents, external_ref=str(ref)
                )
        raise RegistrarError("Namecheap response missing DomainCreateResult")
