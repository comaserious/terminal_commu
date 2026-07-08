from typing import assert_never

from commu.adapters.arca import ArcaAdapter
from commu.adapters.base import CommunityAdapter, RequestPolicy
from commu.adapters.dcinside import DcinsideAdapter
from commu.adapters.fmk import FmkAdapter
from commu.targets import CommunityTarget, Site


def adapter_for(target: CommunityTarget) -> CommunityAdapter:
    match target.site:
        case Site.FMKOREA:
            return FmkAdapter(target)
        case Site.DCINSIDE:
            return DcinsideAdapter(target)
        case Site.ARCA:
            return ArcaAdapter(target)
    assert_never(target.site)


__all__ = ["CommunityAdapter", "RequestPolicy", "adapter_for"]
