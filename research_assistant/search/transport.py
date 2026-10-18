"""Small HTTPS transport with bounded retries, pacing and reproducible evidence.

Only successful response bodies are optionally archived. Credentials stay in request
headers and are never included in evidence or exception messages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import hashlib
from http.client import HTTPException
import json
import math
from pathlib import Path
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, getproxies
import uuid

from .models import ProviderError


OFFICIAL_HOSTS = frozenset({"export.arxiv.org", "api.semanticscholar.org", "api.crossref.org", "api.openalex.org"})
MIN_INTERVALS = {"export.arxiv.org": 3.0, "api.semanticscholar.org": 1.0, "api.crossref.org": 1.0, "api.openalex.org": 1.0}
_SHARED_LOCK = threading.Lock()
_SHARED_LAST_REQUEST: dict[str, float] = {}


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    url: str
    retrieved_at: str
    sha256: str
    evidence_path: str = ""
    route: str = ""
    attempts: int = 1


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Official API endpoints do not require redirects. Refuse them so an
        # upstream redirect can never forward an API key to another endpoint.
        raise ProviderError("检索 API 返回了重定向；为保护凭据已拒绝跟随。")


class HttpTransport:
    """GET the official APIs; injectable I/O and clock make tests offline."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        max_retries: int = 2,
        max_response_bytes: int = 8 * 1024 * 1024,
        max_retry_after: float = 30.0,
        evidence_dir: str | Path | None = None,
        opener: Callable | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        proxy_mode: str = "system",
    ):
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须为正的有限秒数")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 10:
            raise ValueError("max_retries 必须为 0 到 10 的整数")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes 必须为正整数")
        if isinstance(max_retry_after, bool) or not math.isfinite(max_retry_after) or max_retry_after < 0:
            raise ValueError("max_retry_after 必须为非负有限秒数")
        if proxy_mode not in {"auto", "direct", "system"}:
            raise ValueError("proxy_mode 必须为 auto、direct 或 system")
        self.timeout = float(timeout)
        self.max_retries = max_retries
        self.max_response_bytes = max_response_bytes
        self.max_retry_after = float(max_retry_after)
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        self.proxy_mode = proxy_mode
        if opener is not None:
            self._routes = [("injected", opener)]
        elif proxy_mode == "system":
            self._routes = [("system", build_opener(_NoRedirect()).open)]
        else:
            self._routes = [("direct", build_opener(ProxyHandler({}), _NoRedirect()).open)]
            if proxy_mode == "auto" and (getproxies().get("https") or getproxies().get("http")):
                self._routes.append(("system", build_opener(_NoRedirect()).open))
        self._preferred_route = 0
        self._sleep = sleep if sleep is not None else time.sleep
        self._clock = clock if clock is not None else time.monotonic
        if sleep is None and clock is None:
            # Multiple provider instances still respect the official host limit.
            self._lock = _SHARED_LOCK
            self._last_request = _SHARED_LAST_REQUEST
        else:
            self._lock = threading.Lock()
            self._last_request: dict[str, float] = {}

    def _pace(self, host: str) -> None:
        with self._lock:
            now = self._clock()
            previous = self._last_request.get(host)
            if previous is not None:
                delay = MIN_INTERVALS[host] - (now - previous)
                if delay > 0:
                    self._sleep(delay)
            self._last_request[host] = self._clock()

    @staticmethod
    def _parse_retry_after(value: str | None) -> tuple[str | None, float | None]:
        """Keep only valid public Retry-After values, with no upper truncation."""
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            return None, None
        value = value.strip()
        try:
            delay = float(value)
            if not math.isfinite(delay) or delay < 0:
                return None, None
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                delay = max(0.0, date.timestamp() - time.time())
                if not math.isfinite(delay):
                    return None, None
            except (TypeError, ValueError, OverflowError):
                return None, None
        return value, delay

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        _, requested = self._parse_retry_after(retry_after)
        return requested if requested is not None else min(0.5 * 2**attempt, self.max_retry_after)

    def _failure_details(self, url: str, history: list[dict], *, code: int | None = None,
                         retry_after: str | None = None) -> dict:
        header, seconds = self._parse_retry_after(retry_after)
        limited = code == 429
        recommended = seconds if seconds is not None else (300.0 if limited else None)
        retry_at = None
        if recommended is not None:
            try:
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=math.ceil(recommended))).isoformat()
            except (OverflowError, ValueError):
                pass
        return {"request_url": url, "http_status": code, "route": history[-1]["route"] if history else None,
                "attempts": [dict(attempt) for attempt in history], "rate_limited": limited,
                "retry_after": header, "retry_after_seconds": seconds,
                "recommended_wait_seconds": recommended, "retry_at": retry_at,
                "wait_source": "server" if seconds is not None else "local_policy" if limited else None}

    def _archive(self, response: HttpResponse) -> str:
        if self.evidence_dir is None:
            return ""
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            body_path = self.evidence_dir / f"{response.sha256}.response"
            receipt_id = hashlib.sha256((response.url + response.retrieved_at + response.sha256).encode("utf-8")).hexdigest()
            metadata_path = self.evidence_dir / f"{receipt_id}.json"
            # Replace each file atomically; no process shares a partial writer.
            for target, content in (
                (body_path, response.body),
                (metadata_path, json.dumps({
                    "request_url": response.url,
                    "retrieved_at": response.retrieved_at,
                    "response_sha256": response.sha256,
                    "response_file": body_path.name,
                    "route": response.route,
                    "attempts": response.attempts,
                }, ensure_ascii=False, indent=2).encode("utf-8")),
            ):
                temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                try:
                    temp_path.write_bytes(content)
                    temp_path.replace(target)
                finally:
                    temp_path.unlink(missing_ok=True)
            return str(body_path.resolve())
        except OSError:
            raise ProviderError("检索成功，但无法写入原始响应证据目录；请检查目录权限和磁盘空间。") from None

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname in OFFICIAL_HOSTS
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ProviderError("检索请求只允许使用官方 API 的 HTTPS 地址。")
        request_headers = {"User-Agent": "multi-agent-research-assistant/1.0", "Accept": "application/json, application/atom+xml"}
        if headers:
            request_headers.update(headers)
        for header, value in request_headers.items():
            if (
                not isinstance(header, str)
                or not isinstance(value, str)
                or not header
                or any(ord(char) <= 32 or ord(char) >= 127 or char == ":" for char in header)
                or any(ord(char) < 32 or ord(char) >= 127 for char in value)
            ):
                raise ProviderError("检索请求包含无效的 HTTP 请求头。")
        try:
            request = Request(url, headers=request_headers, method="GET")
        except (TypeError, ValueError):
            raise ProviderError("检索请求包含无效的 HTTP 参数。") from None
        history: list[dict] = []
        for attempt in range(self.max_retries + 1):
            self._pace(parsed.hostname)
            retry_after = None
            code = None
            route_name, open_request = self._routes[self._preferred_route]
            started = self._clock()
            attempt_info = {"attempt": attempt + 1, "route": route_name,
                            "started_at": datetime.now(timezone.utc).isoformat()}
            try:
                with open_request(request, timeout=self.timeout) as remote:
                    status = getattr(remote, "status", 200)
                    if status != 200:
                        raise HTTPError(url, status, "API HTTP failure", getattr(remote, "headers", {}), None)
                    body = remote.read(self.max_response_bytes + 1)
                if not isinstance(body, bytes):
                    raise ProviderError("检索 API 返回了无效的响应类型。")
                if len(body) > self.max_response_bytes:
                    raise ProviderError("检索 API 响应超过大小限制。")
                if not body.strip():
                    raise ProviderError("检索 API 返回了空响应，不能将其视为零条检索结果。")
                response = HttpResponse(
                    body=body,
                    url=url,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    sha256=hashlib.sha256(body).hexdigest(),
                    route=route_name,
                    attempts=attempt + 1,
                )
                evidence_path = self._archive(response)
                if evidence_path:
                    response = HttpResponse(body, url, response.retrieved_at, response.sha256, evidence_path, route_name, attempt + 1)
                return response
            except HTTPError as exc:
                code = exc.code
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                exc.close()
                header, delay = self._parse_retry_after(retry_after)
                attempt_info.update(outcome="http_error", http_status=code, retry_after=header,
                                    retry_after_seconds=delay, elapsed_seconds=round(self._clock() - started, 6))
                history.append(attempt_info)
                details = self._failure_details(url, history, code=code, retry_after=retry_after)
                if code == 429:
                    wait = math.ceil(details["recommended_wait_seconds"])
                    origin = "服务端 Retry-After" if details["wait_source"] == "server" else "本地保守建议；服务端未提供有效 Retry-After"
                    raise ProviderError(f"论文 API 请求收到 HTTP 429 限流响应，本轮已停止，不自动重试或切换路线。建议等待 {wait} 秒（{origin}），恢复时间不能保证。", details=details) from None
                if not 500 <= code <= 599:
                    raise ProviderError(f"检索 API 请求失败（HTTP {code}）；请检查 API 权限或请求参数。", details=details) from None
                if delay is not None and delay > self.max_retry_after:
                    raise ProviderError(f"检索 API 返回 HTTP {code}，要求等待 {math.ceil(delay)} 秒，超过自动等待上限；本轮已停止，未提前重试。", details=details) from None
                failure = f"HTTP {code}"
            except (URLError, TimeoutError, OSError, HTTPException) as exc:
                # Do not stringify network exceptions: custom handlers and
                # proxies can include header values in their error messages.
                failure = "网络连接或读取超时"
                attempt_info.update(outcome="network_error", network_error_type=type(exc).__name__,
                                    underlying_error_type=type(getattr(exc, "reason", exc)).__name__,
                                    elapsed_seconds=round(self._clock() - started, 6))
                history.append(attempt_info)
                # Route fallback shares the existing retry budget. API HTTP
                # errors (including 429) never trigger a proxy/route change.
                if len(self._routes) > 1:
                    self._preferred_route = (self._preferred_route + 1) % len(self._routes)
            except ValueError:
                attempt_info.update(outcome="invalid_request", elapsed_seconds=round(self._clock() - started, 6))
                history.append(attempt_info)
                raise ProviderError("检索请求包含无效的 HTTP 参数。", details=self._failure_details(url, history)) from None
            if attempt == self.max_retries:
                raise ProviderError(f"检索 API 请求失败（{failure}）；已用尽 {self.max_retries} 次重试。", details=self._failure_details(url, history, code=code, retry_after=retry_after)) from None
            self._sleep(self._retry_delay(attempt, retry_after))
        raise AssertionError("unreachable")
