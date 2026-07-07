from typing import assert_never

from fmk_reader.adapters.base import CommunityAdapter, RequestPolicy
from fmk_reader.adapters.fmk import FmkAdapter
from fmk_reader.targets import CommunityTarget, Site


def adapter_for(target: CommunityTarget) -> CommunityAdapter:
    match target.site:
        case Site.FMKOREA:
            return FmkAdapter(target)
        case Site.DCINSIDE:
            raise NotImplementedError("DCInside adapter is not implemented")
        case Site.ARCA:
            raise NotImplementedError("Arca adapter is not implemented")
    assert_never(target.site)


__all__ = ["CommunityAdapter", "RequestPolicy", "adapter_for"]
