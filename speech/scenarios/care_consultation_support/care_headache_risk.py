"""Headache routing policy: staff review by default; sudden AND severe escalates.

No diagnosis, prescriptions or physical actions are performed here. Reference:
https://www.nhs.uk/symptoms/headaches/ (sudden, extremely painful headache).
The default staff-review level is this project's older-adult care policy.
"""
from __future__ import annotations

import re


HEADACHE = re.compile(r"头痛|头疼|脑袋[疼痛]|脑壳[疼痛]|(?:头|脑袋|脑壳)(?:部|顶)?(?:突然|一下子|忽然|刚才|现在|开始|有点|有一点|特别|非常|很)*[疼痛]")
DENIED_HEADACHE = re.compile(r"(?:没有|没|不再|并不|不)(?:头痛|头疼|脑袋[疼痛])|(?:头|脑袋|脑壳)(?:已经|现在)?不[疼痛](?:了)?")
SUDDEN = re.compile(r"突然|忽然|一下子|猛地|瞬间|一下就")
SEVERE = re.compile(r"(?:疼|痛).{0,4}(?:厉害|受不了|要命|难以忍受)|(?:剧烈|特别|非常|极其)(?:地|的)?(?:疼|痛)|剧烈(?:的)?(?:头|脑袋)[疼痛]|(?:特别|非常)厉害的?头[疼痛]|从来没这么[疼痛]|最[疼痛]")
NOT_SUDDEN = re.compile(r"不是突然|没有突然|并非突然|不是一下子|慢慢开始|逐渐开始|慢慢出现|逐渐出现|一点点疼起来")
NOT_SEVERE = re.compile(r"(?:不|没|没有|并不|不是|不算)(?:特别|非常|那么|很|太)?(?:剧烈|厉害|严重|疼|痛)")
HISTORICAL_OR_HYPOTHETICAL = re.compile(r"以前|曾经|去年|上次|假如|如果|比如|听说")
OTHER_PAIN = re.compile(r"(?:膝|腰|腿|脚|胳膊|肩|肚|腹|胸).{0,6}[疼痛]")
YES = re.compile(r"(?:嗯[，, ]*)?(?:是|是的|对|对的|有|确实是)[。！!，, ]*")


def _single_attribute_question(text):
    """A bare yes can confirm one explicitly asked attribute, never an OR list."""
    if not re.search(r"[？?]|吗|是不是|是否",text):return None
    if OTHER_PAIN.search(text) and not HEADACHE.search(text):return None
    sudden=bool(SUDDEN.search(text))
    severe=bool(SEVERE.search(text))
    if sudden==severe or re.search(r"或者|以及|和|有没有|手脚|视力|恶心|呕吐|说话",text):
        return None
    return 'sudden' if sudden else 'severe'


def classify_headache_risk(text, *, history=None):
    turns=list(history or [])+[{'role':'user','content':str(text or '')}]
    active=False
    sudden=False
    severe=False
    previous_question=None
    for turn in turns:
        value=re.sub(r"\s+","",str(turn.get('content') or ''))
        if turn.get('role')=='assistant':
            previous_question=_single_attribute_question(value)
            continue
        if turn.get('role')!='user':continue
        if active and YES.fullmatch(value) and previous_question:
            if previous_question=='sudden':sudden=True
            else:severe=True
        previous_question=None
        for clause in re.split(r"[，,。！？!?；;]|但是|不过|可是",value):
            if not clause:continue
            if HISTORICAL_OR_HYPOTHETICAL.search(clause) and not re.search(r"现在|这次|今天",clause):
                continue
            if DENIED_HEADACHE.search(clause):
                active=False;sudden=False;severe=False
                continue
            mentions_head=bool(HEADACHE.search(clause))
            if not mentions_head and OTHER_PAIN.search(clause):
                # Do not borrow headache severity from a different body area.
                active=False;sudden=False;severe=False
                continue
            if mentions_head:active=True
            if not active:continue
            if NOT_SUDDEN.search(clause):sudden=False
            elif SUDDEN.search(clause):sudden=True
            if NOT_SEVERE.search(clause):severe=False
            elif SEVERE.search(clause):severe=True
    if not active:return None
    if sudden and severe:
        return {'risk_level':'external_route','matched':['headache_sudden','headache_severe'],
                'route_to':'URGENT_ASSISTANCE','reason':'突发且异常剧烈的头痛，转交异常情况处理。'}
    return {'risk_level':'needs_staff','matched':['headache_staff_review'],
            'route_to':None,'reason':'您提到头痛，需要工作人员进一步了解。'}
