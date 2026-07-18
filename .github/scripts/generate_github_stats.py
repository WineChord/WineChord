#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
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
GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestReviewContributions
    }
  }
}
"""


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


def fetch_search_count(username: str, item_type: str, token: str) -> int:
    query = urlencode({"q": f"author:{username} type:{item_type}", "per_page": 1})
    response = request_json(f"{API_ROOT}/search/issues?{query}", token)
    if not isinstance(response, dict) or not isinstance(response.get("total_count"), int):
        raise GitHubAPIError(f"GitHub {item_type} search response was invalid")
    return response["total_count"]


def fetch_contributions(username: str, token: str) -> Optional[dict[str, int]]:
    response = request_json(
        f"{API_ROOT}/graphql",
        token,
        {"query": GRAPHQL_QUERY, "variables": {"login": username}},
    )
    if not isinstance(response, dict):
        raise GitHubAPIError("GitHub GraphQL response was invalid")

    errors = response.get("errors")
    if errors:
        error_types = {error.get("type") for error in errors if isinstance(error, dict)}
        if "RESOURCE_LIMITS_EXCEEDED" in error_types:
            print(
                "::warning::GitHub contribution metrics exceeded the per-query resource "
                "budget; publishing the remaining verified statistics."
            )
            return None
        messages = "; ".join(
            error.get("message", "Unknown GraphQL error")
            for error in errors
            if isinstance(error, dict)
        )
        raise GitHubAPIError(f"GitHub GraphQL returned errors: {messages}")

    try:
        collection = response["data"]["user"]["contributionsCollection"]
        return {
            "commits": int(collection["totalCommitContributions"]),
            "reviews": int(collection["totalPullRequestReviewContributions"]),
        }
    except (KeyError, TypeError, ValueError):
        raise GitHubAPIError("GitHub contribution metrics response was invalid") from None


def format_value(value: Optional[int]) -> str:
    return "—" if value is None else f"{value:,}"


def render_card(
    username: str,
    profile: dict[str, Any],
    repositories: list[dict[str, Any]],
    pull_requests: int,
    issues: int,
    contributions: Optional[dict[str, int]],
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
        ("Commits (last year)", contributions["commits"] if contributions else None),
        ("Pull requests authored", pull_requests),
        ("Issues authored", issues),
        ("Code reviews (last year)", contributions["reviews"] if contributions else None),
    )

    def render_column(stats: tuple[tuple[str, Optional[int]], ...], x: int) -> str:
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
        pull_requests = fetch_search_count(arguments.username, "pr", token)
        issues = fetch_search_count(arguments.username, "issue", token)
        contributions = fetch_contributions(arguments.username, token)
        card = render_card(
            arguments.username,
            profile,
            repositories,
            pull_requests,
            issues,
            contributions,
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
