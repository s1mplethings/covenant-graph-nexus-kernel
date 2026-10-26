from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol

from .contracts import CommunityPost, CommunitySource, CommunityThread, DiscoveryTopicSet, canonical_hash, utc_now


DISCOVERY_ADAPTER_INTERFACE_VERSION = "community-discovery-adapter-v1.0"
_TAG = re.compile(r"<[^>]+>")


def _plain(value: Any, *, limit: int = 12000) -> str:
    text = html.unescape(_TAG.sub(" ", str(value or "")))
    return " ".join(text.split())[:limit]


class CommunityReadAdapter(Protocol):
    adapter_ref: str
    platform: str

    def search(self, queries: tuple[str, ...], *, max_results: int, cursor: str | None = None) -> tuple[CommunityThread, ...]: ...
    def read_thread(self, thread_id: str) -> CommunityThread: ...


class JSONTransport(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any] | list[Any]: ...


class UrllibJSONTransport:
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any] | list[Any]:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoints are adapter-owned
            payload = response.read(2_000_000)
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, (dict, list)):
            raise ValueError("community API returned non-container JSON")
        return value


@dataclass
class RecordedCommunityReadAdapter:
    platform: str
    threads: tuple[CommunityThread, ...]
    adapter_ref: str = "community.read.recorded@1"

    def search(self, queries: tuple[str, ...], *, max_results: int, cursor: str | None = None) -> tuple[CommunityThread, ...]:
        terms = tuple(term.lower() for term in queries)
        found = [thread for thread in self.threads if any(term in (thread.title + " " + thread.thread_summary).lower() for term in terms)]
        return tuple(found[:max_results])

    def read_thread(self, thread_id: str) -> CommunityThread:
        return next(thread for thread in self.threads if thread.thread_id == thread_id)


@dataclass
class GitHubPublicReadAdapter:
    transport: JSONTransport = field(default_factory=UrllibJSONTransport)
    platform: str = "github"
    adapter_ref: str = "community.read.github-public@1"
    api_base: str = "https://api.github.com"

    def search(self, queries: tuple[str, ...], *, max_results: int, cursor: str | None = None) -> tuple[CommunityThread, ...]:
        del cursor
        results: dict[str, CommunityThread] = {}
        bounded_queries = queries[:5]
        # Pull enough candidates per topic to survive duplicate and pull-request
        # filtering while keeping the official search budget at five requests.
        per_query = min(10, max_results)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "CGKN-Community-Operator/1.0", "X-GitHub-Api-Version": "2022-11-28"}
        for query in bounded_queries:
            # The community operator is not a general issue crawler. Restrict
            # discovery to threads whose maintainers explicitly classify them
            # as questions; this removes implementation backlogs and bot-owned
            # task boards before ranking ever sees them.
            q = urllib.parse.quote(f'{query} in:title,body is:issue is:open label:question archived:false')
            raw = self.transport.get(f"{self.api_base}/search/issues?q={q}&sort=updated&order=desc&per_page={per_query}", headers=headers, timeout=20)
            if not isinstance(raw, Mapping):
                continue
            for item in raw.get("items", []):
                if not isinstance(item, Mapping) or item.get("pull_request"):
                    continue
                thread = self._from_search_item(item, query)
                results.setdefault(thread.canonical_url, thread)
                if len(results) >= max_results:
                    return tuple(results.values())
        return tuple(results.values())

    def read_thread(self, thread_id: str) -> CommunityThread:
        raise NotImplementedError("read_thread requires a repository URL identity in v1")

    @staticmethod
    def _from_search_item(item: Mapping[str, Any], query: str) -> CommunityThread:
        issue_url = str(item.get("html_url") or "")
        thread_id = "github-" + canonical_hash(issue_url)[7:23]
        user = item.get("user") if isinstance(item.get("user"), Mapping) else {}
        author = str(user.get("login") or "public-user")
        body = _plain(item.get("body") or item.get("title"))
        created = str(item.get("created_at") or utc_now())
        updated = str(item.get("updated_at") or created)
        labels = tuple(str(label.get("name")) for label in item.get("labels", []) if isinstance(label, Mapping) and label.get("name"))
        normalized_labels = {label.casefold() for label in labels}
        is_question = "question" in normalized_labels
        post = CommunityPost(
            post_id=f"github-post-{item.get('id')}", thread_id=thread_id, parent_post_id=None,
            author_public_identity=author, content=body or _plain(item.get("title")), created_at=created,
            edited_at=updated if updated != created else None, links=tuple(re.findall(r"https?://\S+", body)),
            public_metadata={
                "query": query,
                "state": item.get("state"),
                "comments": item.get("comments", 0),
                "source": "official_github_search_api",
                # These conservative priors express only what the official
                # query and maintainer label prove. Unknown community rules
                # still force HUMAN_REVIEW before any draft can be used.
                "relevance": 0.65 if is_question else 0.4,
                "ability_to_help": 0.7 if is_question else 0.3,
                "discussion_quality": 0.7 if is_question else 0.5,
            },
            our_reply_target=True,
        )
        return CommunityThread(
            thread_id, "github", issue_url, _plain(item.get("title"), limit=500), author, created, updated,
            str(item.get("repository_url") or "github"), labels, (post,), _plain(body, limit=600), (post.post_id,), 0.0,
        )


@dataclass
class HackerNewsPublicReadAdapter:
    transport: JSONTransport = field(default_factory=UrllibJSONTransport)
    platform: str = "hackernews"
    adapter_ref: str = "community.read.hackernews-public@1"
    api_base: str = "https://hacker-news.firebaseio.com/v0"

    def search(self, queries: tuple[str, ...], *, max_results: int, cursor: str | None = None) -> tuple[CommunityThread, ...]:
        del cursor
        ids = self.transport.get(self.api_base + "/newstories.json", headers={"User-Agent": "CGKN-Community-Operator/1.0"}, timeout=20)
        if not isinstance(ids, list):
            return ()
        terms = tuple(term.lower() for term in queries)
        results: list[CommunityThread] = []
        # This is a discovery fallback, not a firehose. Keep the official API
        # fan-out low enough for an explicit bounded scan.
        for raw_id in ids[:30]:
            item = self.transport.get(f"{self.api_base}/item/{int(raw_id)}.json", headers={"User-Agent": "CGKN-Community-Operator/1.0"}, timeout=10)
            if not isinstance(item, Mapping):
                continue
            title = _plain(item.get("title"))
            body = _plain(item.get("text"))
            if not any(term in (title + " " + body).lower() for term in terms):
                continue
            created = dt.datetime.fromtimestamp(int(item.get("time", 0)), dt.timezone.utc).isoformat().replace("+00:00", "Z")
            thread_id = f"hn-{item.get('id')}"
            post = CommunityPost(thread_id + "-root", thread_id, None, str(item.get("by") or "public-user"), body or title, created, links=tuple(filter(None, (str(item.get("url") or ""),))), public_metadata={"score": item.get("score", 0), "descendants": item.get("descendants", 0), "source": "official_hn_firebase_api"}, our_reply_target=True)
            results.append(CommunityThread(thread_id, "hackernews", f"https://news.ycombinator.com/item?id={item.get('id')}", title, post.author_public_identity, created, created, "Hacker News", (), (post,), body[:600], (post.post_id,), 0.0))
            if len(results) >= max_results:
                break
        return tuple(results)

    def read_thread(self, thread_id: str) -> CommunityThread:
        raw_id = thread_id.removeprefix("hn-")
        found = self.search((raw_id,), max_results=1)
        if not found:
            raise KeyError(thread_id)
        return found[0]


class DiscoveryCoordinator:
    """Bounded multi-source scan. Deduplication is by canonical thread URL."""

    def __init__(self, adapters: Mapping[str, CommunityReadAdapter]) -> None:
        self.adapters = dict(adapters)

    def scan(self, sources: Iterable[CommunitySource], topics: DiscoveryTopicSet, *, max_results: int) -> tuple[CommunityThread, ...]:
        unique: dict[str, CommunityThread] = {}
        for source in sources:
            adapter = self.adapters.get(source.source_id)
            if adapter is None or adapter.platform != source.platform:
                continue
            per_source_budget = min(max_results, topics.max_queries_per_platform * topics.max_results_per_query)
            for thread in adapter.search(topics.queries[:topics.max_queries_per_platform], max_results=per_source_budget):
                unique.setdefault(thread.canonical_url, thread)
                if len(unique) >= max_results:
                    return tuple(unique.values())
        return tuple(unique.values())

