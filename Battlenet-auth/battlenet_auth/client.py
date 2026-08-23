import inspect
import json
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from curl_cffi.requests import AsyncSession

from .exceptions import BattleNetError, ChallengeRequired, InvalidCredentials
from .helpers import (challenge_id, error_text, form_action, form_field,
                      is_redirect, location, srp_enabled)
from .srp import SrpClient, make_upgrade_verifier_hex

OAUTH_ENTRY = "https://account.battle.net/oauth2/authorization/account-settings"
ACCOUNT_API = ("/api/account", "/api/details")

_LOCALE_RE = re.compile(r"/login/([a-z]{2})/")
_CT_RE = re.compile(r"CT_[A-Z_]+")
_INPUT_ID_RE = re.compile(r'inputId"?\s*[:=]\s*"?([a-zA-Z_]+)')


class LoginResult:
    def __init__(
        self, session, ticket, account_id, used_srp, srp_version, account, trace
    ):
        self.session = session
        self.ticket = ticket
        self.account_id = account_id
        self.used_srp = used_srp
        self.srp_version = srp_version
        self.account = account
        self.trace = trace

    @property
    def cookies(self):
        return self.session.cookies.get_dict()

    @property
    def authorized(self):
        return bool(self.account)


class BattleNetClient:
    def __init__(
        self,
        region="eu",
        locale="en",
        impersonate="chrome",
        persist_login=True,
        timeout=30,
        proxies=None,
        send_upgrade_verifier=False,
        max_hops=30,
    ):
        self.region = region.lower()
        self.locale = locale.lower()
        self.persist_login = persist_login
        self.timeout = timeout
        self.send_upgrade_verifier = send_upgrade_verifier
        self.max_hops = max_hops

        self._proxies = proxies or []
        self._proxy_i = 0

        self.session = AsyncSession(impersonate=impersonate)
        langs = [
            f"{self.locale}-{self.locale.upper()}",
            f"{self.locale};q=0.9",
            "en-US;q=0.8",
            "en;q=0.7",
        ]
        self.session.headers.update({"accept-language": ",".join(langs)})

        self.trace = []
        self.origin = None
        self.host = None
        self.ticket = None
        self._srp_version = None

    def _current_proxy(self):
        if not self._proxies:
            return None

        return self._proxies[self._proxy_i % len(self._proxies)]

    def _rotate_proxy(self):
        self._proxy_i += 1

    def _json_headers(self, extra=None):
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": self.origin,
        }
        if extra:
            headers.update(extra)

        return headers

    async def _request(self, method, url, follow=False, retries=5, **kwargs):
        kwargs["allow_redirects"] = False
        kwargs.setdefault("timeout", self.timeout)

        for _ in range(retries):
            proxy = self._current_proxy()
            if proxy:
                kwargs["proxy"] = proxy

            try:
                res = await self.session.request(method, url, **kwargs)
            except Exception:
                if self._proxies:
                    self._rotate_proxy()
                    continue
                raise

            self.trace.append(
                {
                    "method": method,
                    "status": res.status_code,
                    "url": res.url,
                    "location": location(res),
                }
            )
            self._grab_ticket(res.url)
            hop = location(res)

            if hop:
                self._grab_ticket(hop)

            if res.status_code == 429 and self._proxies:
                self._rotate_proxy()
                continue

            if follow:
                res = await self._follow(res)

            return res

        raise BattleNetError(f"{method} {url}: не удалось после {retries} попыток")

    async def _follow(self, res):
        for _ in range(self.max_hops):
            if not is_redirect(res):
                return res

            res = await self._request("GET", urljoin(res.url, location(res)))

        raise BattleNetError("слишком много редиректов")

    async def close(self):
        await self.session.close()

    async def login(self, account_name, password, on_code=None, force_srp=True):
        login_url, html = await self._open_login_page()
        if login_url is None:
            return await self._finish(False)

        pw_url, pw_html = await self._submit_login(login_url, account_name, html)

        use_srp = force_srp and srp_enabled(pw_html)
        if use_srp:
            res = await self._send_srp(pw_url, pw_html, account_name, password)
        else:
            res = await self._send_plain(pw_url, pw_html, account_name, password)

        await self._after_password(res, on_code)
        return await self._finish(use_srp)

    async def _open_login_page(self):
        r = await self._request(
            "GET", OAUTH_ENTRY, follow=True, params={"ref": "/overview"}
        )

        if "/login/" not in urlsplit(r.url).path:
            return None, None

        parts = urlsplit(r.url)

        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.host = parts.netloc
        m = _LOCALE_RE.search(parts.path)

        if m:
            self.locale = m.group(1)

        return r.url, r.text

    async def _submit_login(self, login_url, account_name, html):
        data = {
            "accountName": account_name,
            "srpEnabled": form_field(html, "srpEnabled", "false"),
            "csrftoken": form_field(html, "csrftoken"),
            "sessionTimeout": form_field(html, "sessionTimeout")
            or str(int(time.time() * 1000) + 30 * 60 * 1000),
        }
        r = await self._request(
            "POST",
            login_url,
            data=data,
            headers={"origin": self.origin, "referer": login_url},
        )

        if is_redirect(r):
            page = await self._request(
                "GET", urljoin(login_url, location(r)), follow=True
            )
            return page.url, page.text

        return r.url, r.text

    async def _srp_params(self, account_name):
        r = await self._request(
            "POST",
            f"{self.origin}/login/srp",
            params={"csrfToken": "true"},
            json={"inputs": [{"input_id": "account_name", "value": account_name}]},
            headers=self._json_headers(),
        )

        if r.status_code != 200:
            raise BattleNetError(f"srp {r.status_code}: {r.text[:200]}")

        return r.json()

    async def _send_srp(self, pw_url, pw_html, account_name, password):
        params = await self._srp_params(account_name)
        self._srp_version = int(params["version"])
        srp_user = params["username"]

        proof = SrpClient(
            params["modulus"],
            params["generator"],
            params["version"],
            params["iterations"],
        ).prove(srp_user, password, params["salt"], params["public_B"])

        upgrade = ""
        if (
            self.send_upgrade_verifier
            and params.get("eligible_credential_upgrade")
            and int(params["version"]) == 1
        ):
            upgrade = make_upgrade_verifier_hex(
                params["modulus"],
                params["generator"],
                srp_user,
                password,
                int(params.get("iterations") or 15000),
            )

        data = {
            "username": account_name,
            "password": "." * len(password),
            "upgradeVerifier": upgrade,
            "useSrp": "true",
            "publicA": proof.public_A_hex,
            "clientEvidenceM1": proof.client_evidence_M1_hex,
            "usePasskey": "false",
            "srpEnabled": "true",
            "csrftoken": params.get("csrf_token") or form_field(pw_html, "csrftoken"),
            "accountName": account_name,
        }
        if self.persist_login:
            data["persistLogin"] = "on"

        return await self._request(
            "POST",
            pw_url,
            data=data,
            headers={"origin": self.origin, "referer": pw_url},
        )

    async def _send_plain(self, pw_url, pw_html, account_name, password):
        data = {
            "username": account_name,
            "password": password,
            "upgradeVerifier": "",
            "useSrp": "false",
            "publicA": "",
            "clientEvidenceM1": "",
            "usePasskey": "false",
            "srpEnabled": form_field(pw_html, "srpEnabled", "false"),
            "csrftoken": form_field(pw_html, "csrftoken"),
            "accountName": account_name,
        }
        if self.persist_login:
            data["persistLogin"] = "on"

        return await self._request(
            "POST",
            pw_url,
            data=data,
            headers={"origin": self.origin, "referer": pw_url},
        )

    async def _after_password(self, res, on_code):
        for _ in range(self.max_hops):
            if not is_redirect(res):
                if self.host and self.host in res.url and "/login/" in res.url:
                    raise InvalidCredentials(error_text(res.text) or "вход не принят")

                return

            target = urljoin(res.url, location(res))
            parts = urlsplit(target)

            if not (parts.netloc == self.host and parts.path.startswith("/login")):
                await self._request("GET", target, follow=True)
                return

            path = parts.path
            if "/password" in path:
                page = await self._request("GET", target, follow=True)
                raise InvalidCredentials(
                    error_text(page.text) or "неверный логин или пароль"
                )

            if "account-locked" in path or "/challenge/" in path:
                res = await self._verify(target, on_code)
                continue

            if "/legal" in path:
                res = await self._accept_legal(target)
                continue

            res = await self._request("GET", target)

        raise BattleNetError("логин не завершился")

    async def _verify(self, url, on_code):
        r = await self._request("GET", url)
        for _ in range(self.max_hops):
            if not is_redirect(r):
                break

            r = await self._request("GET", urljoin(url, location(r)))
            url = r.url

        cid = challenge_id(r.url) or challenge_id(r.text)
        query = parse_qs(urlsplit(r.url).query)
        ref = query.get("ref", [""])[0]
        app = query.get("app", ["bas"])[0]

        if urlsplit(r.url).path.rstrip("/").endswith("/choose"):
            offered = _CT_RE.findall(r.text) or ["CT_EMAIL"]
            method = (
                "CT_AUTHENTICATOR"
                if "CT_AUTHENTICATOR" in offered
                else "CT_SMS" if "CT_SMS" in offered else offered[0]
            )

            await self._request(
                "POST",
                f"{self.origin}/login/challenge/{cid}/choose",
                json={"challenge_id": cid, "challenge_type": method},
                headers=self._json_headers(),
            )

            code_page = f"{self.origin}/login/{self.locale}/challenge/{cid}?ref={ref}&app={app}&sendCode=true"
            r = await self._request("GET", code_page)

        field = form_field(r.text, "inputs[0].inputId")
        if not field:
            found = _INPUT_ID_RE.search(r.text)
            field = found.group(1) if found else "email"

        kind = {
            "email": "почта",
            "authenticator": "2FA",
            "sms": "SMS",
        }.get(field.lower(), "EMAIL")

        if on_code is None:
            raise ChallengeRequired(kind, cid)

        code = on_code(f"Код ({kind}): ")
        if inspect.isawaitable(code):
            code = await code

        if not code:
            raise ChallengeRequired(kind, cid)

        action = form_action(r.text)
        submit = (
            urljoin(r.url, action.group(1)) if action and action.group(1) else r.url
        )
        return await self._request(
            "POST",
            submit,
            data={
                "inputs[0].inputId": field,
                "inputs[0].value": code.strip(),
                "csrftoken": form_field(r.text, "csrftoken"),
            },
            headers={"origin": self.origin, "referer": r.url},
        )

    async def _accept_legal(self, url):
        r = await self._request("GET", url)
        if is_redirect(r):
            return r

        action = form_action(r.text)
        submit = (
            urljoin(r.url, action.group(1))
            if action and action.group(1) is not None
            else r.url
        )

        return await self._request(
            "POST",
            submit,
            data={"csrftoken": form_field(r.text, "csrftoken")},
            headers={"origin": self.origin, "referer": r.url},
        )

    async def _finish(self, used_srp):
        await self._request(
            "GET", OAUTH_ENTRY, follow=True, params={"ref": "/overview"}
        )
        account = await self._account() or {}
        account_id = self.ticket.rsplit("-", 1)[-1] if self.ticket else None

        if not account and account_id is None:
            raise BattleNetError("сессия не подтверждена")

        return LoginResult(
            self.session,
            self.ticket,
            account_id,
            used_srp,
            self._srp_version,
            account,
            self.trace,
        )

    async def _account(self):
        for path in ACCOUNT_API:
            r = await self._request(
                "GET",
                "https://account.battle.net" + path,
                headers={"accept": "application/json"},
            )
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()

        return None

    def _grab_ticket(self, url):
        st = parse_qs(urlsplit(url).query).get("ST", [None])[0]

        if st:
            self.ticket = st

    def save_session(self, path):
        jar = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.session.cookies.jar
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(jar, f)

    def read_session(self, path):
        with open(path, encoding="utf-8") as f:
            for c in json.load(f):
                self.session.cookies.set(
                    c["name"], c["value"], domain=c["domain"], path=c["path"]
                )
