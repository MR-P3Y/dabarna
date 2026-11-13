"""Read-only clocks for the existing workers. Never creates or starts a game."""
from datetime import datetime, timedelta, timezone

from app.core import config as cfg
from app.models.game import GameAutoDraw
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.services.game_autopilot_config_service import AUTOPILOT_LEVELS, GameAutopilotConfigService
from app.services.game_autopilot_worker import GameAutopilotWorker, _as_datetime


def automation_timeline(db) -> list[dict]:
    group=cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID
    actor=cfg.GAME_AUTOPILOT_SYSTEM_USER_ID
    if not group:
        return []
    autopilot_ready=bool(actor and cfg.GAME_AUTOPILOT_RUNTIME_ENABLED and db.get(User,actor) is not None)
    clocks=[]
    for level in AUTOPILOT_LEVELS:
        config=db.get(GameAutopilotConfig,level)
        topic=GameAutopilotConfigService.topic_id_for_level(level)
        if not config or not topic:
            continue
        item={'level':level,'phase':'WAITING','deadline_utc':None,'duration_seconds':None,'game_id':None}
        game=GameAutopilotWorker._active_game(db,level=level,group_id=group,topic_id=topic)
        if game:
            item['game_id']=game.id
            if game.status=='RUNNING':
                control=db.get(GameAutoDraw,game.id) if game.draw_mode=='AUTO' else None
                if not control:
                    item['phase']='MANUAL_DRAW'
                elif control.status=='PAUSED':
                    item['phase']='PAUSED'
                elif control.status=='RUNNING' and cfg.GAME_AUTO_DRAW_ENABLED:
                    item.update(phase='NEXT_NUMBER',deadline_utc=_iso(control.next_draw_at),duration_seconds=control.interval_seconds)
            elif game.execution_source!='SYSTEM':
                item['phase']='MANUAL'
            elif not autopilot_ready or not config.enabled:
                continue
            elif config.start_mode=='AUTO':
                durations=GameAutopilotWorker.countdowns_for_games(db,{game.id:level})
                if game.id in durations:
                    item.update(phase='START',deadline_utc=_iso(game.scheduled_start_at),duration_seconds=durations[game.id])
                else:
                    item['phase']='WAITING_PLAYERS'
            else:
                item['phase']='MANUAL_START'
        elif autopilot_ready and config.enabled and config.scheduler_mode=='AUTO':
            if config.card_price is None or int(config.card_price)<=0 or (config.draw_mode=='AUTO' and not cfg.GAME_AUTO_DRAW_ENABLED):
                item['phase']='NOT_READY'
            else:
                latest=GameAutopilotWorker._latest_ended_game(db,level=level,group_id=group,topic_id=topic)
                ended=_as_datetime(latest.ended_at) if latest else None
                if latest and not ended:
                    item['phase']='MISSING_END_TIME'
                elif ended:
                    delay=max(0,int(config.cooldown_seconds or 0),int(config.repeat_interval_seconds or 0))
                    item.update(phase='NEXT_GAME',deadline_utc=_iso(ended+timedelta(seconds=delay)),duration_seconds=delay)
                else:
                    item['phase']='AWAITING_CREATION'
        elif not autopilot_ready or not config.enabled:
            continue
        clocks.append(item)
    return clocks


def _iso(value):
    value=_as_datetime(value)
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None
