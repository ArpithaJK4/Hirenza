import asyncio

import httpx
import respx

from app.agents.discovery.sources.ats import AshbySource, GreenhouseSource, LeverSource
from app.agents.discovery.sources.base import CompanyBoard, FetchContext
from app.agents.discovery.sources.email_alerts import parse_alert_html
from app.agents.discovery.sources.feeds import RemoteOKSource, WeWorkRemotelySource

CTX = FetchContext(queries=[], boards=[CompanyBoard(1, "Stripe", "stripe")])


def run(adapter, ctx=CTX):
    async def go():
        async with httpx.AsyncClient() as c:
            return await adapter.fetch(c, ctx)
    return asyncio.run(go())


@respx.mock
def test_greenhouse_parse_and_404():
    respx.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true").respond(json={"jobs": [
        {"id": 11, "title": "DevOps Engineer", "absolute_url": "https://x/11", "location": {"name": "Bengaluru"},
         "content": "&lt;p&gt;Kubernetes and Terraform&lt;/p&gt;", "first_published": "2026-11-17T08:00:00Z"}]})
    [b] = run(GreenhouseSource())
    assert b.authoritative and b.scope == "greenhouse:stripe"
    assert b.jobs[0].description == "Kubernetes and Terraform"
    assert b.jobs[0].posted_at.year == 2026

    respx.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true").respond(404)
    [b] = run(GreenhouseSource())
    assert b.dead and not b.jobs


@respx.mock
def test_lever_and_ashby():
    respx.get("https://api.lever.co/v0/postings/stripe?mode=json").respond(json=[
        {"id": "abc", "text": "SRE", "hostedUrl": "https://l/abc", "applyUrl": "https://l/abc/apply",
         "categories": {"location": "Pune", "team": "Infra"}, "createdAt": 1763366400000,
         "descriptionPlain": "Run AWS", "lists": [{"text": "Req", "content": "<li>Docker</li>"}],
         "workplaceType": "hybrid"}])
    [b] = run(LeverSource())
    j = b.jobs[0]
    assert j.apply_url.endswith("/apply") and "Docker" in j.description and j.remote_hint == "hybrid"

    respx.get("https://api.ashbyhq.com/posting-api/job-board/stripe?includeCompensation=true").respond(json={
        "jobs": [{"id": "z1", "title": "Platform Engineer", "location": "Remote", "isRemote": True,
                  "jobUrl": "https://a/z1", "publishedAt": "2026-11-16T00:00:00Z", "descriptionPlain": "K8s"},
                 {"id": "z2", "title": "Hidden", "isListed": False, "jobUrl": "https://a/z2"}]})
    [b] = run(AshbySource())
    assert [j.external_id for j in b.jobs] == ["z1"] and b.jobs[0].remote_hint == "remote"


@respx.mock
def test_remoteok_filters_tags_and_skips_legal_notice():
    respx.get("https://remoteok.com/api").respond(json=[
        {"legal": "notice"},
        {"id": 1, "position": "DevOps Engineer", "company": "R", "tags": ["devops"], "url": "https://r/1",
         "epoch": 1763366400, "location": "Worldwide"},
        {"id": 2, "position": "Copywriter", "company": "R", "tags": ["marketing"], "url": "https://r/2"}])
    [b] = run(RemoteOKSource())
    assert [j.external_id for j in b.jobs] == ["1"]


@respx.mock
def test_wwr_rss():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>Acme: Senior Backend Engineer</title><link>https://wwr/1</link><guid>https://wwr/1</guid>
      <region>Anywhere in the World</region><pubDate>Mon, 17 Nov 2026 08:00:00 +0000</pubDate>
      <description>&lt;p&gt;Python&lt;/p&gt;</description></item></channel></rss>"""
    respx.get(url__regex=r"https://weworkremotely\.com/.*").respond(text=rss)
    batches = run(WeWorkRemotelySource())
    j = batches[0].jobs[0]
    assert (j.company_name, j.title) == ("Acme", "Senior Backend Engineer")
    assert j.posted_at.year == 2026


def test_linkedin_alert_email_parse():
    html = """<table><tr><td>
      <a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x">DevOps Engineer</a>
      <p>Zeta · Bengaluru, Karnataka, India</p>
      <a href="https://www.linkedin.com/comm/jobs/view/4012345678/?x=2">View job</a>
    </td></tr><tr><td>
      <a href="https://www.linkedin.com/comm/jobs/view/4099999999/">Cloud Engineer</a>
      <p>Acme</p><p>Pune</p></td></tr></table>"""
    jobs = parse_alert_html(html, "linkedin")
    assert [j.external_id for j in jobs] == ["linkedin:4012345678", "linkedin:4099999999"]
    assert jobs[0].company_name == "Zeta" and "Bengaluru" in jobs[0].location
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert (jobs[1].company_name, jobs[1].location) == ("Acme", "Pune")
