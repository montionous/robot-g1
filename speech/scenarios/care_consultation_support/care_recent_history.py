"""Use observation dates of related verified records, never import timestamps."""
from __future__ import annotations

from datetime import datetime, timedelta

from care_memory_persistence import derive_memory_key

# Dialogue freshness window, not a medical conclusion about symptom continuity.
RECENT_HISTORY_DAYS = 7


def find_recent_related_history(profile, *, care_domain, user_text, now=None,
                                recent_days=RECENT_HISTORY_DAYS):
    clock=now or datetime.now().astimezone()
    if clock.tzinfo is None:
        clock=clock.astimezone()
    key=derive_memory_key(care_domain,user_text)
    # A generic domain key cannot establish that the same symptom was recorded.
    if key.endswith((':general_discomfort',':consultation')):
        return None
    candidates=[]
    for memory in profile.get('memories',[]):
        if memory.get('memory_key')!=key or memory.get('verified') not in (True,1):
            continue
        try:
            stamp=str(memory.get('last_observed_at') or '')
            observed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if observed.tzinfo is None:observed=observed.replace(tzinfo=clock.tzinfo)
            age=clock-observed
        except (TypeError,ValueError,OverflowError):
            continue
        if timedelta(0)<=age<=timedelta(days=recent_days):
            candidates.append((observed,{
                'memory_key':key,'observed_at':stamp,'observation_date':observed.date().isoformat(),
                'age_days':round(age.total_seconds()/86400,3),
                'window_days':recent_days,'summary':str(memory.get('summary') or ''),
            }))
    return max(candidates,key=lambda row:row[0])[1] if candidates else None


def apply_recent_history(plan, *, care_domain, user_text, history, question_state, now=None):
    # Resolve the topic from the elder's words only; robot statements and profile
    # summaries do not establish which body area this consultation concerns.
    user_turns=[str(item.get('content') or '') for item in history or [] if item.get('role')=='user']
    if user_text and (not user_turns or user_turns[-1]!=user_text):user_turns.append(user_text)
    # Use the latest explicit topic, falling back to the preceding elder turns
    # for short answers such as “差不多”.
    key_text=''
    for text in reversed(user_turns):
        key=derive_memory_key(care_domain,text)
        if not key.endswith((':general_discomfort',':consultation')):
            key_text=text
            break
    recent=find_recent_related_history(plan.get('profile') or {},
        care_domain=care_domain,user_text=key_text,now=now)
    plan['recent_related_history']=recent
    if recent:
        question_state['recent_related_history']=recent
        plan.setdefault('context_facts',[]).append(
            f"{recent['observation_date']}已有同类护理记录：{recent['summary']}。"
            '这是既往观察，不代表此后一直持续，也不代表当前功能状态已经确认。'
        )
    return plan
