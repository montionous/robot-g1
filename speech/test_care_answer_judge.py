"""Answer-judge protocol and controller integration without external effects."""
import json
import unittest
from unittest.mock import Mock,patch

import test_care_question_state as existing
from care_answer_judge_llm import CareAnswerJudgeLLM
from care_question_state import question_topics


class AnswerJudgeProtocolTests(unittest.TestCase):
    def test_valid_quoted_evidence(self):
        answer='去食堂依旧自己走，脚下还是老样子。'
        raw=json.dumps({'status':'answered','confidence':.96,'evidence':answer})
        result=CareAnswerJudgeLLM._parse_decision(raw,topic='walking',answer=answer)
        self.assertEqual(result['evidence'],answer)
        self.assertEqual(result['topic'],'walking')

    def test_fabricated_or_missing_evidence_rejected(self):
        for evidence in ('', '老人行走稳定，没有跌倒风险。',42):
            with self.subTest(evidence=evidence),self.assertRaises(ValueError):
                CareAnswerJudgeLLM._parse_decision(json.dumps({
                    'status':'answered','confidence':.99,'evidence':evidence}),
                    topic='walking',answer='嗯，差不多。')

    def test_uncertain_quote_cannot_be_marked_answered(self):
        for evidence in ('不知道。','可能还稳吧。','没听清。'):
            with self.subTest(evidence=evidence),self.assertRaises(ValueError):
                CareAnswerJudgeLLM._parse_decision(json.dumps({
                    'status':'answered','confidence':.99,'evidence':evidence}),
                    topic='walking',answer=evidence)

    def test_invalid_status_confidence_and_json_rejected(self):
        for raw in ('not json',json.dumps({'status':'yes','confidence':.9}),
                    json.dumps({'status':'unclear','confidence':True}),
                    json.dumps({'status':'unclear','confidence':'0.9'}),
                    json.dumps({'status':'unclear','confidence':float('nan')}),
                    json.dumps({'status':'unclear','confidence':1.1})):
            with self.subTest(raw=raw),self.assertRaises((ValueError,TypeError)):
                CareAnswerJudgeLLM._parse_decision(raw,topic='walking',answer='好的。')

    def test_api_sends_question_current_answer_and_uses_timeout(self):
        judge=CareAnswerJudgeLLM.__new__(CareAnswerJudgeLLM)
        judge.model='offline-model';judge.timeout=8;judge.url='https://example.invalid';judge.api_key='offline'
        response=Mock(ok=True)
        response.json.return_value={'choices':[{'message':{'content':json.dumps({
            'status':'not_answered','confidence':.95,'evidence':'','reason':'only acknowledgement'})}}]}
        with patch('care_answer_judge_llm.requests.post',return_value=response) as post:
            result=judge.classify(question=existing.WALK,answer='好的。',topic='walking')
        request=post.call_args.kwargs
        self.assertEqual(request['timeout'],8)
        content=json.loads(request['json']['messages'][1]['content'])
        self.assertEqual(content['question'],existing.WALK)
        self.assertEqual(content['current_answer'],'好的。')
        self.assertEqual(result['status'],'not_answered')


class AnswerJudgeControllerTests(unittest.TestCase):
    def setUp(self):
        existing.CareControllerQuestionTests.setUp(self)

    def prepare(self):
        existing.CareControllerQuestionTests.prepare_walking_question(self)

    def install(self,status='answered',confidence=.95):
        self.judge=Mock()
        self.judge.classify.side_effect=lambda **kw:{'topic':kw['topic'],
            'status':status,'confidence':confidence,'evidence':kw['answer'] if status=='answered' else '',
            'reason':'offline semantic decision','llm_ms':1,'model':'offline'}
        self.care.answer_judge=self.judge

    def test_natural_answer_uses_llm_and_survives_later_turns(self):
        self.prepare();self.install()
        answer='去食堂依旧自己走，脚下还是老样子。'
        result=self.care.handle_user_text(answer)
        self.assertEqual(result['answer_decision']['source'],'llm')
        self.assertTrue(result['answer_decision']['used'])
        self.assertEqual(result['question_state']['confirmed']['walking'],answer)
        self.assertNotIn('walking',question_topics(result['reply']))
        self.care.handle_user_text('我有点担心，想让你陪我聊聊。')
        self.assertEqual(self.judge.classify.call_count,1)
        self.assertIn('walking',self.care.last_question_state['confirmed'])

    def test_semantic_unclear_overrides_short_answer_rule(self):
        self.prepare();self.install(status='unclear')
        result=self.care.handle_user_text('嗯，差不多。')
        self.assertTrue(result['answer_decision']['used'])
        self.assertNotIn('walking',result['question_state']['confirmed'])

    def test_semantic_request_to_repeat_allows_unanswered_question(self):
        self.prepare();self.install(status='repeat_requested')
        result=self.care.handle_user_text('我耳背，刚那句落了半截，劳驾重讲。')
        self.assertIn('walking',result['question_state']['repeat_requested'])
        self.assertIn('walking',question_topics(result['reply']))

    def test_low_confidence_does_not_create_health_fact(self):
        self.prepare();self.install(confidence=.5)
        result=self.care.handle_user_text('去食堂依旧自己走，脚下还是老样子。')
        self.assertFalse(result['answer_decision']['used'])
        self.assertNotIn('walking',result['question_state']['confirmed'])

    def test_timeout_falls_back_without_new_fact(self):
        self.prepare();self.care.answer_judge=Mock(classify=Mock(side_effect=TimeoutError()))
        result=self.care.handle_user_text('去食堂依旧自己走，脚下还是老样子。')
        self.assertEqual(result['answer_decision']['source'],'rule_fallback')
        self.assertNotIn('walking',result['question_state']['confirmed'])

    def test_no_previous_question_skips_judge(self):
        self.install()
        self.care.start('我今天膝盖有点酸。',preclassified=True)
        self.judge.classify.assert_not_called()


if __name__=='__main__':unittest.main()
