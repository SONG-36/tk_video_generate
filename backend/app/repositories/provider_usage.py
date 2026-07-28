from sqlalchemy.orm import Session

from app.models.provider_usage import ProviderUsage
from app.repositories.base import BaseRepository


class ProviderUsageRepository(BaseRepository[ProviderUsage]):
    def __init__(self, session: Session):
        super().__init__(session, ProviderUsage)

