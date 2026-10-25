"""Daily observed asset snapshots, UTC. Never backfills missing history."""
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from ..database import SessionLocal
from ..models import User
from . import finance

logger = logging.getLogger(__name__)


def capture_daily(session_factory=None):
    """Separate transaction/session per user, safe across multiple server workers.

    Same user/day is checked under the finance user lock. An existing manual
    capture wins and is not overwritten. Failures do not stop other users.
    """
    factory = session_factory or SessionLocal
    with factory() as db:
        user_ids = list(db.scalars(select(User.id)).all())
    captured, skipped, failed = 0, 0, 0
    for user_id in user_ids:
        # Request payload is stable for a day's retries. effective_at is assigned
        # by execute only on initial creation, not replayed with a fresh hash.
        day = datetime.now(timezone.utc).date().isoformat()
        with factory() as db:
            try:
                finance.execute(db, user_id=user_id, kind='snapshot', key='daily-snapshot:'+day,
                                data={'trigger':'daily_scheduler_utc'})
                db.commit()
                captured += 1
            except HTTPException as exc:
                db.rollback()
                if exc.status_code == 409 and exc.detail == 'Daily snapshot already captured; immutable':
                    skipped += 1
                else:
                    failed += 1
                    logger.exception('finance.snapshot.failed user=%s day=%s', user_id, day)
            except Exception:
                db.rollback()
                failed += 1
                logger.exception('finance.snapshot.failed user=%s day=%s', user_id, day)
    logger.info('finance.snapshot.daily captured=%s skipped=%s failed=%s timezone=UTC', captured, skipped, failed)
    return {'captured': captured, 'skipped': skipped, 'failed': failed}


class FinanceSnapshotScheduler:
    def __init__(self):
        self.scheduler = None

    def start(self):
        from ..config import get_settings
        if not get_settings().finance_snapshot_scheduler_enabled or self.scheduler is not None:
            return
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone='UTC')
        scheduler.add_job(capture_daily, 'cron', hour=0, minute=5, id='finance-daily-utc',
                          coalesce=True, max_instances=1, misfire_grace_time=3600)
        # Startup catches only today; a paused server never fabricates missed days.
        scheduler.add_job(capture_daily, 'date', run_date=datetime.now(timezone.utc),
                          id='finance-startup-current-day')
        scheduler.start()
        self.scheduler = scheduler
        logger.info('finance.snapshot.scheduler.started timezone=UTC daily=00:05 startup=current_day_only')

    def shutdown(self):
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=True)
            self.scheduler = None


scheduler = FinanceSnapshotScheduler()
