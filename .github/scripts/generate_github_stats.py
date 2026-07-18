#!/usr/bin/env python3

import argparse
from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
class GitHubAPIError(RuntimeError):
    pass


def request_json(
    url: str,
    token: str,
    payload: Optional[dict[str, Any]] = None,
) -> Union[dict[str, Any], list[dict[str, Any]]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "WineChord-profile-stats",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            response = json.loads(error.read().decode("utf-8"))
            message = response.get("message", str(error))
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = str(error)
        raise GitHubAPIError(
            f"GitHub API request failed with HTTP {error.code}: {message}"
        ) from None
    except URLError as error:
        raise GitHubAPIError(f"GitHub API request failed: {error.reason}") from None


def fetch_repositories(username: str, token: str) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1

    while True:
        query = urlencode(
            {
                "type": "owner",
                "sort": "full_name",
                "per_page": 100,
                "page": page,
            }
        )
        response = request_json(
            f"{API_ROOT}/users/{quote(username)}/repos?{query}", token
        )
        if not isinstance(response, list):
            raise GitHubAPIError("GitHub repositories response was not a list")

        repositories.extend(response)
        if len(response) < 100:
            return repositories
        page += 1


def fetch_search_count(search_query: str, endpoint: str, token: str) -> int:
    query = urlencode({"q": search_query, "per_page": 1})
    response = request_json(f"{API_ROOT}/search/{endpoint}?{query}", token)
    if not isinstance(response, dict) or not isinstance(response.get("total_count"), int):
        raise GitHubAPIError(f"GitHub {endpoint} search response was invalid")
    return response["total_count"]


def format_value(value: int) -> str:
    return f"{value:,}"


def render_card(
    username: str,
    profile: dict[str, Any],
    repositories: list[dict[str, Any]],
    commits: int,
    pull_requests: int,
    issues: int,
    reviews: int,
) -> str:
    original_repositories = [repo for repo in repositories if not repo.get("fork")]
    stars = sum(int(repo.get("stargazers_count", 0)) for repo in original_repositories)
    forks = sum(int(repo.get("forks_count", 0)) for repo in original_repositories)

    left_stats = (
        ("Public repositories", int(profile.get("public_repos", len(repositories)))),
        ("Stars earned", stars),
        ("Repository forks", forks),
        ("Followers", int(profile.get("followers", 0))),
    )
    right_stats = (
        ("Commits authored (last year)", commits),
        ("Pull requests authored", pull_requests),
        ("Issues authored", issues),
        ("Pull requests reviewed", reviews),
    )

    def render_column(stats: tuple[tuple[str, int], ...], x: int) -> str:
        rows = []
        for index, (label, value) in enumerate(stats):
            y = 88 + index * 34
            rows.append(
                f'<circle cx="{x}" cy="{y - 5}" r="3" fill="#539bf5"/>'
                f'<text x="{x + 14}" y="{y}" class="label">{escape(label)}</text>'
                f'<text x="{x + 275}" y="{y}" class="value" text-anchor="end">'
                f"{format_value(value)}</text>"
            )
        return "".join(rows)

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    safe_username = escape(username)
    title = f"{safe_username}'s GitHub Stats"

    return f'''<svg width="650" height="235" viewBox="0 0 650 235" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">A daily static snapshot of verified GitHub profile statistics.</desc>
  <style>
    .title {{ font: 600 20px "Segoe UI", Ubuntu, sans-serif; fill: #539bf5; }}
    .label {{ font: 400 13px "Segoe UI", Ubuntu, sans-serif; fill: #768390; }}
    .value {{ font: 600 14px "Segoe UI", Ubuntu, sans-serif; fill: #adbac7; }}
    .footer {{ font: 400 11px "Segoe UI", Ubuntu, sans-serif; fill: #636e7b; }}
  </style>
  <rect x="0.5" y="0.5" width="649" height="234" rx="8" fill="#22272e" stroke="#444c56"/>
  <text x="28" y="38" class="title">{title}</text>
  <path d="M28 55.5H622" stroke="#373e47"/>
  {render_column(left_stats, 32)}
  {render_column(right_stats, 339)}
  <path d="M28 207.5H622" stroke="#373e47"/>
  <text x="28" y="224" class="footer">Updated daily · {updated_at}</text>
</svg>
'''


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static GitHub profile card")
    parser.add_argument("--username", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    try:
        profile = request_json(
            f"{API_ROOT}/users/{quote(arguments.username)}", token
        )
        if not isinstance(profile, dict):
            raise GitHubAPIError("GitHub profile response was invalid")
        repositories = fetch_repositories(arguments.username, token)
        since = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
        commits = fetch_search_count(
            f"author:{arguments.username} author-date:>={since}", "commits", token
        )
        pull_requests = fetch_search_count(
            f"author:{arguments.username} type:pr", "issues", token
        )
        issues = fetch_search_count(
            f"author:{arguments.username} type:issue", "issues", token
        )
        reviews = fetch_search_count(
            f"reviewed-by:{arguments.username} type:pr", "issues", token
        )
        card = render_card(
            arguments.username,
            profile,
            repositories,
            commits,
            pull_requests,
            issues,
            reviews,
        )
    except GitHubAPIError as error:
        print(f"::error::{error}")
        return 1

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary_output.write_text(card, encoding="utf-8")
    temporary_output.replace(arguments.output)
    print(f"Generated {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
