"""Dialogue-level regression tests; no robot, network or persistent DB access."""
import contextlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

SCENE=Path(__file__).resolve().parent/'scenarios/care_consultation_support'
sys.path.insert(0,str(SCENE))
from care_question_state import (analyze_care_questions, apply_question_state,
    guard_care_questions, question_topics, question_state_prompt)
import care_controller
import care_personalization

WALK='您现在站起来和走路，还和平时一样稳吗？'
BASELINE='今天这种膝部不适和平时相比，是差不多还是明显一些？'

def user(text):return {'role':'user','content':text}
def robot(text):return {'role':'assistant','content':text}

PROFILE={
    'conditions':[{'body_area':'knee','condition_name':'膝骨关节炎'}],
    'baselines':[
        {'baseline_key':'usual_knee_state','baseline_value':'平时偶尔酸胀'},
        {'baseline_key':'walking_independence','baseline_value':'平时室内独立行走'},
    ],
    'events':[],'memories':[],
}


class QuestionStateTests(unittest.TestCase):
    def test_short_answer_belongs_to_last_question_not_other_topic(self):
        state=analyze_care_questions([robot(WALK),user('嗯，差不多。')])
        self.assertEqual(state['confirmed'],{'walking':'嗯，差不多。'})
        state=analyze_care_questions([robot(BASELINE),user('嗯，差不多。')])
        self.assertEqual(set(state['confirmed']),{'baseline_comparison'})

    def test_common_short_answers_and_paraphrased_walking_questions(self):
        for answer in ('还是差不多。','跟以前一样。','不太稳。','不是很稳。'):
            state=analyze_care_questions([robot(WALK),user(answer)])
            self.assertIn('walking',state['confirmed'])
            self.assertNotIn('walking',question_topics(guard_care_questions('您走起来还稳吗？',state)))

    def test_short_answer_is_not_a_fact_without_question(self):
        for turns in ([user('嗯，差不多。')],
                      [robot('平时走路稳的档案我看到了。'),user('嗯，差不多。')],
                      [robot(WALK),user('陪我聊聊'),user('嗯，差不多。')]):
            self.assertNotIn('walking',analyze_care_questions(turns)['confirmed'])

    def test_dont_infer_answer_from_question_or_history_statement(self):
        state=analyze_care_questions([robot(WALK),user('不知道稳不稳。')])
        self.assertFalse(state['confirmed'])
        self.assertFalse(analyze_care_questions([robot('您的档案以前写着走路稳定。')])['confirmed'])

    def test_unknown_and_off_topic_answers_stay_unknown(self):
        for value in ('嗯。','好的。','不知道。','没注意。','可能还稳吧。','我有点担心，陪我聊聊。'):
            with self.subTest(value=value):
                state=analyze_care_questions([robot(WALK),user(value)])
                self.assertNotIn('walking',state['confirmed'])
                self.assertNotIn('walking',question_topics(guard_care_questions(WALK,state)))

    def test_repeat_allowed_when_unanswered_and_not_heard(self):
        for value in ('没听清，能再说一遍吗？','刚才没听见。','这是什么意思，我不明白。'):
            state=analyze_care_questions([robot(WALK),user(value)])
            self.assertFalse(state['confirmed'])
            self.assertIn('walking',state['repeat_requested'])
            self.assertEqual(guard_care_questions(WALK,state),WALK)

    def test_known_fact_survives_later_unclear_turn(self):
        state=analyze_care_questions([robot(WALK),user('走路还稳。'),
            robot('请慢慢说。'),user('没听清。')])
        self.assertIn('walking',state['confirmed'])
        self.assertNotIn('walking',question_topics(guard_care_questions(WALK,state)))

    def test_explicit_facts_and_corrections_are_preserved_as_raw_words(self):
        state=analyze_care_questions([user('走路还稳。'),robot('请慢慢说。'),user('现在走路不稳了。')])
        self.assertEqual(state['confirmed']['walking'],'现在走路不稳了。')
        self.assertIn('现在走路不稳了',question_state_prompt(state))

    def test_duration_and_injury_questions_also_use_contextual_answers(self):
        for question,answer,topic in (
            ('这种不适持续多久了？','三天了。','duration'),
            ('最近有没有摔倒或扭伤？','没有。','injury'),
            (BASELINE,'比平时要明显一些。','baseline_comparison')):
            state=analyze_care_questions([robot(question),user(answer)])
            self.assertIn(topic,state['confirmed'])
            self.assertNotIn(topic,question_topics(guard_care_questions(question,state)))

    def test_guard_removes_only_repeated_question_keeps_support(self):
        state=analyze_care_questions([robot(WALK),user('差不多。'),robot('您慢慢说。'),user('陪我聊聊。')])
        reply=guard_care_questions('我会陪着您，您慢慢说。'+WALK,state)
        self.assertEqual(reply,'我会陪着您，您慢慢说。')

    def test_plan_stops_forcing_a_completed_question(self):
        plan={'preferred_question':WALK,'fallback_reply':WALK,'must_use':['旧目标'],
              'required_groups':[{'name':'旧目标','any':['不存在的关键词']}],'personalized':True}
        state=analyze_care_questions([robot(WALK),user('差不多。')])
        result=apply_question_state(plan,state)
        self.assertIsNone(result['preferred_question'])
        self.assertFalse(result['required_groups'])
        self.assertNotIn('walking',question_topics(result['fallback_reply']))

    def test_advice_and_duration_statements_are_not_removed(self):
        state=analyze_care_questions([robot('这种情况持续多久了？'),user('三天了。')])
        text='您说这种不适已经三天了，建议工作人员进一步关注。'
        self.assertEqual(guard_care_questions(text,state),text)

    def test_date_of_injury_is_not_symptom_duration(self):
        state=analyze_care_questions([user('我三天前摔倒了。')])
        self.assertNotIn('duration',state['confirmed'])
        self.assertIn('injury',state['confirmed'])

    def test_answer_does_not_spread_across_multiple_questions(self):
        state=analyze_care_questions([robot(WALK+BASELINE),user('差不多。')])
        self.assertFalse(state['confirmed'])


class CareControllerQuestionTests(unittest.TestCase):
    def setUp(self):
        self.stack=contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('sqlite3.connect','requests.sessions.Session.request','subprocess.Popen'):
            self.stack.enter_context(patch(target,side_effect=AssertionError('offline access: '+target)))
        self.stack.enter_context(patch.object(care_personalization,'get_personal_care_profile',return_value=PROFILE))
        self.stack.enter_context(patch.object(care_controller,'CareEndIntentLLM',return_value=Mock(
            classify=Mock(return_value={'should_end':False,'confidence':1}))))
        self.stack.enter_context(patch.object(care_controller,'CareNeedBridge',return_value=Mock(
            sync=Mock(return_value=None))))
        self.llm=Mock()
        self.llm.generate_reply.side_effect=lambda **kw:{
            'text': '您之前的膝部档案记着平时偶有酸胀。'+BASELINE if kw['round_no']==1 else WALK,
            'llm_ms':1,'model':'offline'}
        self.care=care_controller.CareConsultation(elderly_id=1,session_id=1,llm=self.llm,dry_run=True,
            answer_judge=Mock(classify=Mock(side_effect=RuntimeError("offline judge unavailable"))))

    def prepare_walking_question(self):
        self.care.start('我今天膝盖有点酸。',preclassified=True)
        reply=self.care.handle_user_text('比平时要明显一些。')
        self.assertIn('walking',question_topics(reply['reply']))

    def test_live_reproduction_answer_then_companionship_no_reasking(self):
        self.prepare_walking_question()
        answer=self.care.handle_user_text('嗯，差不多。')
        self.assertIn('walking',answer['question_state']['confirmed'])
        self.assertNotIn('walking',question_topics(answer['reply']))
        support=self.care.handle_user_text('我有点担心，想让你陪我聊聊。')
        self.assertNotIn('walking',question_topics(support['reply']))
        self.assertIn('陪',support['reply'])
        self.assertIsNone(support['personalization_plan']['preferred_question'])
        self.assertNotEqual(support['personalization_plan']['strategy'],'functional_baseline_comparison')
        self.assertEqual(self.care.history[-1]['content'],support['reply'])

    def test_cannot_hear_can_repeat_without_marking_answered(self):
        self.prepare_walking_question()
        result=self.care.handle_user_text('没听清，能再说一遍吗？')
        self.assertNotIn('walking',result['question_state']['confirmed'])
        self.assertIn('walking',question_topics(result['reply']))

    def test_fallback_cannot_reintroduce_completed_question(self):
        self.prepare_walking_question()
        malformed_plan={'personalized':True,'required_groups':[{'name':'missing','any':['zzzz']}],
            'fallback_reply':WALK,'strategy':'legacy','profile':{},'must_use':[]}
        with patch.object(care_controller,'build_personalization_plan',return_value=malformed_plan):
            result=self.care.handle_user_text('嗯，差不多。')
        self.assertTrue(result['personalization_check']['fallback_used'])
        self.assertTrue(result['personalization_check']['repeated_question_removed'])
        self.assertNotIn('walking',question_topics(result['reply']))

    def test_provided_comparison_not_reasked_on_first_turn(self):
        result=self.care.start('膝盖今天比平时更酸。',preclassified=True)
        self.assertIn('baseline_comparison',result['question_state']['confirmed'])
        self.assertNotIn('baseline_comparison',question_topics(result['reply']))


if __name__=='__main__':unittest.main()
