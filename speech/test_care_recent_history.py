"""Recent observed history informs questions without inventing current facts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import test_care_question_state as existing
from care_recent_history import find_recent_related_history, apply_recent_history
from care_question_state import analyze_care_questions, guard_care_questions, question_topics, question_state_prompt
import care_personalization

TZ=timezone(timedelta(hours=8))
NOW=datetime(2026,10,25,13,0,tzinfo=TZ)
ONSET='这种不适是最近才出现的，还是已经持续了一段时间？'

def memory(observed=None,**kwargs):
    return {'memory_key':'mobility:knee_discomfort','summary':'此前膝盖酸胀，休息后缓解。',
        'occurrence_count':1,'verified':1,'last_observed_at':observed or (NOW-timedelta(days=3)).isoformat(),
        'created_at':NOW.isoformat(),**kwargs}

def lookup(memories,**kwargs):
    return find_recent_related_history({'memories':memories},care_domain='mobility',
        user_text=kwargs.pop('user_text','我膝盖有点疼。'),now=NOW,**kwargs)


class RecentHistoryTests(unittest.TestCase):
    def test_recent_observation_is_found_and_does_not_create_current_fact(self):
        recent=lookup([memory()])
        self.assertEqual(recent['observation_date'],'2026-10-22')
        state=analyze_care_questions([existing.user('我膝盖有点疼。')])
        plan={'profile':{'memories':[memory()]}}
        apply_recent_history(plan,care_domain='mobility',user_text='我膝盖有点疼。',
            history=[],question_state=state,now=NOW)
        self.assertFalse(state['confirmed'])
        self.assertNotIn('onset',question_topics(guard_care_questions(ONSET,state)))
        self.assertIn('记录日期不等于症状持续时长',question_state_prompt(state))

    def test_old_observation_stays_old_even_when_just_inserted(self):
        self.assertIsNone(lookup([memory('2026-08-18T15:20:00')]))

    def test_missing_invalid_future_or_unverified_time_is_not_recent(self):
        for row in (memory('invalid'),memory((NOW+timedelta(days=1)).isoformat()),
                    memory(verified=0),memory(last_observed_at=''),
                    {'memory_key':'mobility:knee_discomfort','verified':1,'created_at':NOW.isoformat()}):
            with self.subTest(row=row):self.assertIsNone(lookup([row]))

    def test_other_body_area_does_not_establish_recent_same_symptom(self):
        self.assertIsNone(lookup([memory()],user_text='腰部有点疼。'))
        self.assertIsNone(lookup([memory()],user_text='身体不舒服。'))

    def test_inclusive_window_and_timezone_conversion(self):
        limit=NOW-timedelta(days=7)
        self.assertIsNotNone(lookup([memory(limit.astimezone(timezone.utc).isoformat())]))
        self.assertIsNone(lookup([memory((limit-timedelta(seconds=1)).isoformat())]))
        self.assertIsNotNone(lookup([memory((NOW-timedelta(days=1)).replace(tzinfo=None).isoformat())]))

    def test_latest_matching_observation_wins(self):
        recent=lookup([memory((NOW-timedelta(days=4)).isoformat()),memory((NOW-timedelta(days=1)).isoformat())])
        self.assertEqual(recent['observation_date'],'2026-10-24')

    def test_short_answer_keeps_elder_topic_not_robot_profile_topic(self):
        state=analyze_care_questions([])
        plan={'profile':{'memories':[memory()]}}
        apply_recent_history(plan,care_domain='mobility',user_text='差不多。',
            history=[existing.user('腰部疼。'),existing.robot('档案中膝盖以前酸胀。')],
            question_state=state,now=NOW)
        self.assertIsNone(plan['recent_related_history'])

    def test_continuity_question_allowed_but_answered_one_not_repeated(self):
        state=analyze_care_questions([])
        state['recent_related_history']=lookup([memory()])
        reply=guard_care_questions(ONSET,state)
        self.assertIn('2026-10-22',reply)
        self.assertIn('recent_course',question_topics(reply))
        self.assertNotIn('onset',question_topics(reply))
        state['confirmed']['recent_course']='上次缓解之后又出现的。'
        self.assertNotIn('recent_course',question_topics(guard_care_questions(reply,state)))

    def test_old_or_unknown_history_allows_current_onset_question(self):
        state=analyze_care_questions([])
        self.assertEqual(guard_care_questions(ONSET,state),ONSET)

    def test_elder_volunteers_current_onset_no_reasking_continuity(self):
        state=analyze_care_questions([existing.user('这次是昨天下午开始疼的。')])
        self.assertIn('onset',state['confirmed'])
        state['recent_related_history']=lookup([memory()])
        reply=guard_care_questions(ONSET,state)
        self.assertFalse(question_topics(reply) & {'onset','recent_course'})

    def test_elder_volunteers_recurrence_no_repeat_course_question(self):
        state=analyze_care_questions([existing.user('上次好了一阵又疼起来了。')])
        self.assertIn('recent_course',state['confirmed'])
        state['recent_related_history']=lookup([memory()])
        question='您之前提过类似不适，这次是一直没缓解，还是缓解后又出现了？'
        self.assertNotIn('recent_course',question_topics(guard_care_questions(question,state)))


class RecentHistoryControllerTests(unittest.TestCase):
    def setUp(self):
        existing.CareControllerQuestionTests.setUp(self)

    def run_with_age(self,days):
        profile=deepcopy(existing.PROFILE)
        observed=(datetime.now().astimezone()-timedelta(days=days)).isoformat()
        profile['memories']=[memory(observed)]
        with patch.object(care_personalization,'get_personal_care_profile',return_value=profile):
            existing.CareControllerQuestionTests.prepare_walking_question(self)
            self.llm.generate_reply.side_effect=lambda **kw:{'text':ONSET,'llm_ms':1,'model':'offline'}
            return self.care.handle_user_text('嗯，差不多。')

    def test_recent_record_changes_onset_question_to_history_aware_follow_up(self):
        result=self.run_with_age(3)
        self.assertIn('recent_related_history',result['question_state'])
        self.assertNotIn('onset',question_topics(result['reply']))
        self.assertIn('recent_course',question_topics(result['reply']))
        self.assertNotIn('duration',result['question_state']['confirmed'])
        self.assertNotIn('recent_course',result['question_state']['confirmed'])

    def test_old_record_keeps_onset_question_available(self):
        result=self.run_with_age(60)
        self.assertFalse(result['personalization_plan']['recent_related_history'])
        self.assertIn('onset',question_topics(result['reply']))


if __name__=='__main__':unittest.main()
