"""Client for the UK Parliament Hansard and Members APIs."""

from __future__ import annotations

import re
from typing import Optional

import httpx
from dataclasses import dataclass


MEMBERS_API = "https://members-api.parliament.uk/api"
HANSARD_API = "https://hansard-api.parliament.uk"


@dataclass
class Member:
    id: int
    name: str
    party: str
    constituency: str
    house: str  # "Commons" or "Lords"
    thumbnail_url: Optional[str] = None


@dataclass
class Contribution:
    contribution_id: str
    member_id: int
    member_name: str
    text: str
    debate_title: str
    debate_section_id: str
    sitting_date: str
    house: str
    section: str
    hansard_url: str


def _build_hansard_url(house: str, sitting_date: str, debate_section_id: str, debate_title: str) -> str:
    """Construct a hansard.parliament.uk URL from API fields."""
    date_str = sitting_date.split("T")[0]
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", debate_title)
    slug = "".join(word.capitalize() for word in slug.split())
    return f"https://hansard.parliament.uk/{house}/{date_str}/debates/{debate_section_id}/{slug}"


def search_members(name: str, current_only: bool = True) -> list[Member]:
    """Search for an MP or Lord by name."""
    params = {"Name": name, "take": 10}
    if current_only:
        params["IsCurrentMember"] = "true"

    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{MEMBERS_API}/Members/Search", params=params)
        resp.raise_for_status()
        data = resp.json()

    members = []
    for item in data.get("items", []):
        v = item["value"]
        house_num = v.get("latestHouseMembership", {}).get("house", 1)
        members.append(Member(
            id=v["id"],
            name=v["nameDisplayAs"],
            party=v.get("latestParty", {}).get("name", "Unknown"),
            constituency=v.get("latestHouseMembership", {}).get("membershipFrom", "Unknown"),
            house="Commons" if house_num == 1 else "Lords",
            thumbnail_url=v.get("thumbnailUrl"),
        ))
    return members


def get_member_contributions(
    member_id: int,
    search_term: Optional[str] = None,
    take: int = 50,
    skip: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[Contribution]:
    """Fetch spoken contributions for a member from the Hansard API."""
    params = {
        "queryParameters.memberId": member_id,
        "queryParameters.take": take,
        "queryParameters.skip": skip,
        "queryParameters.orderBy": "SittingDateDesc",
    }
    if search_term:
        params["queryParameters.searchTerm"] = search_term
    if start_date:
        params["queryParameters.startDate"] = start_date
    if end_date:
        params["queryParameters.endDate"] = end_date

    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{HANSARD_API}/search/contributions/Spoken.json",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    contributions = []
    for item in data.get("Results", []):
        text = item.get("ContributionTextFull") or item.get("ContributionText", "")
        debate_title = item.get("DebateSection", "")
        debate_section_id = item.get("DebateSectionExtId", "")
        sitting_date = item.get("SittingDate", "")
        house = item.get("House", "Commons")

        contributions.append(Contribution(
            contribution_id=item.get("ContributionExtId", ""),
            member_id=item.get("MemberId", member_id),
            member_name=item.get("MemberName", ""),
            text=text,
            debate_title=debate_title,
            debate_section_id=debate_section_id,
            sitting_date=sitting_date,
            house=house,
            section=item.get("Section", ""),
            hansard_url=_build_hansard_url(house, sitting_date, debate_section_id, debate_title),
        ))
    return contributions


def get_latest_contributions(
    member_id: int,
    since_date: str,
    take: int = 20,
) -> list[Contribution]:
    """Get contributions from a member since a given date. Used for alerts."""
    return get_member_contributions(
        member_id=member_id,
        start_date=since_date,
        take=take,
    )
