from app.agents.discovery.sources.aggregators import AdzunaSource, JSearchSource
from app.agents.discovery.sources.ats import AshbySource, GreenhouseSource, LeverSource
from app.agents.discovery.sources.base import SourceAdapter
from app.agents.discovery.sources.email_alerts import EmailAlertsSource
from app.agents.discovery.sources.feeds import RemoteOKSource, WeWorkRemotelySource

ADAPTERS: dict[str, type[SourceAdapter]] = {
    a.key: a for a in (GreenhouseSource, LeverSource, AshbySource, RemoteOKSource,
                       WeWorkRemotelySource, AdzunaSource, JSearchSource, EmailAlertsSource)
}
