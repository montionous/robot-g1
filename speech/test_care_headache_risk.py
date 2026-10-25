"""Routing and lifecycle tests for the project's headache care policy."""
import unittest

import test_care_question_state as existing
from care_risk import classify_risk


def user(text):return {'role':'user','content':text}
def robot(text):return {'role':'assistant','content':text}


class HeadacheRiskTests(unittest.TestCase):
    def test_plain_headache_is_staff_review_not_low_or_urgent(self):
        for text in ('我有点头痛。','我今天头疼。','我头有一点疼。','脑袋疼，没别的。'):
            with self.subTest(text=text):
                result=classify_risk(text)
                self.assertEqual(result['risk_level'],'needs_staff')
                self.assertIsNone(result['route_to'])

    def test_spoken_and_live_asr_headache_wordings_still_need_staff(self):
        for text in ('我今天头都点疼。','我头有些疼。','头有一点点疼。','我头有点儿疼。'):
            with self.subTest(text=text):
                result=classify_risk(text)
                self.assertEqual(result['risk_level'],'needs_staff')
                self.assertIsNone(result['route_to'])
                history=[user(text),robot('什么时候开始的？')]
                self.assertEqual(classify_risk('刚开始的。',history=history)['risk_level'],'needs_staff')

    def test_looser_headache_wording_does_not_borrow_other_pain_or_past_facts(self):
        for text in ('我以前头有些疼。','如果头有一点点疼怎么办？',
                     '头有些痒，膝盖有点疼。','我没有头痛，只有腿有点疼。'):
            with self.subTest(text=text):
                self.assertEqual(classify_risk(text)['risk_level'],'low')

    def test_simple_sudden_severe_utterances_route_urgent(self):
        for text in ('我的头突然疼得特别厉害。','我突然头痛的厉害。',
                     '脑袋一下子痛得受不了。','突然剧烈头痛。'):
            with self.subTest(text=text):
                result=classify_risk(text)
                self.assertEqual(result['route_to'],'URGENT_ASSISTANCE')
                self.assertIn('headache_sudden',result['matched'])
                self.assertIn('headache_severe',result['matched'])

    def test_sudden_or_severe_alone_does_not_force_urgent(self):
        for text in ('我突然有点头痛。','我今天头痛得厉害。','头痛是慢慢变严重的。'):
            with self.subTest(text=text):
                self.assertEqual(classify_risk(text)['risk_level'],'needs_staff')

    def test_tolerating_pain_or_later_improvement_does_not_erase_reported_red_flag(self):
        for text in ('突然头痛得特别厉害，但我还能忍住。',
                     '突然头痛得特别厉害，现在慢慢好一些了。'):
            with self.subTest(text=text):
                self.assertEqual(classify_risk(text)['route_to'],'URGENT_ASSISTANCE')

    def test_headache_context_supports_later_explicit_escalation(self):
        history=[user('我有点头痛。'),robot('头痛什么时候开始的？')]
        result=classify_risk('刚才突然一下就疼得特别厉害。',history=history)
        self.assertEqual(result['route_to'],'URGENT_ASSISTANCE')

    def test_bare_yes_confirms_only_single_attribute_question(self):
        history=[user('我头痛得特别厉害。'),robot('头痛是突然出现的吗？')]
        self.assertEqual(classify_risk('嗯，是的。',history=history)['route_to'],'URGENT_ASSISTANCE')

    def test_ambiguous_multiple_symptom_yes_does_not_invent_specific_fact(self):
        history=[user('我有点头痛。'),robot('有没有手脚麻木或说话不清楚？')]
        result=classify_risk('有一些。',history=history)
        self.assertEqual(result['risk_level'],'needs_staff')
        self.assertIsNone(result['route_to'])

    def test_robot_suggestion_is_not_patient_evidence(self):
        history=[user('我有点头痛。'),robot('会不会突然疼得特别厉害？')]
        self.assertIsNone(classify_risk('我没注意。',history=history)['route_to'])

    def test_negated_sudden_or_severity_does_not_escalate(self):
        for text in ('头痛不是突然开始的，只是有点疼。',
                     '突然头痛，但不是特别厉害。','头痛不严重，也没有突然变痛。'):
            with self.subTest(text=text):
                self.assertEqual(classify_risk(text)['risk_level'],'needs_staff')

    def test_past_hypothetical_and_denied_headache_not_used_as_current(self):
        for text in ('我没有头痛。','如果突然头痛得特别厉害该怎么办？',
                     '我以前有过突然剧烈头痛。'):
            with self.subTest(text=text):
                self.assertEqual(classify_risk(text)['risk_level'],'low')

    def test_other_body_pain_does_not_supply_headache_severity(self):
        history=[user('我有点头痛。'),robot('还有其它情况吗？')]
        self.assertIsNone(classify_risk('膝盖突然疼得特别厉害。',history=history)['route_to'])

    def test_existing_other_domain_routes_unchanged(self):
        self.assertEqual(classify_risk('膝盖有点酸。',care_domain='mobility')['risk_level'],'low')
        self.assertEqual(classify_risk('头晕。',care_domain='dizziness')['risk_level'],'needs_staff')
        self.assertEqual(classify_risk('胸口很痛，喘不上气。')['route_to'],'URGENT_ASSISTANCE')


class HeadacheControllerTests(unittest.TestCase):
    def setUp(self):existing.CareControllerQuestionTests.setUp(self)

    def test_plain_headache_creates_one_simulated_staff_item(self):
        result=self.care.start('我有点头痛。',preclassified=True)
        self.assertEqual(result['risk_level'],'needs_staff')
        self.assertTrue(result['new_staff_follow_up'])
        self.assertTrue(result['staff_follow_up_simulated'])
        self.assertIsNone(result['assistance_request_id'])
        self.assertEqual(result['risk_reason'],'您提到头痛，需要工作人员进一步了解。')
        later=self.care.handle_user_text('刚刚开始。')
        self.assertEqual(later['risk_level'],'needs_staff')
        self.assertFalse(later['new_staff_follow_up'])

    def test_live_asr_miswording_creates_staff_review_and_keeps_it_next_turn(self):
        result=self.care.start('我今天头都点疼。',preclassified=True)
        self.assertEqual(result['risk_level'],'needs_staff')
        self.assertTrue(result['new_staff_follow_up'])
        self.assertTrue(result['staff_follow_up_simulated'])
        later=self.care.handle_user_text('刚开始的。')
        self.assertEqual(later['risk_level'],'needs_staff')
        self.assertFalse(later['new_staff_follow_up'])

    def test_severe_sudden_headache_exits_before_reply_model(self):
        result=self.care.start('我的头突然疼得特别厉害。',preclassified=True)
        self.assertEqual(result['risk_level'],'external_route')
        self.assertEqual(result['state'],'TRANSFER_EXTERNAL_ABNORMALITY')
        self.assertEqual(result['transfer_to'],'URGENT_ASSISTANCE')
        self.assertFalse(result['staff_follow_up_created'])
        self.llm.generate_reply.assert_not_called()

    def test_later_escalation_reuses_headache_history(self):
        self.care.start('我有点头痛。',preclassified=True)
        result=self.care.handle_user_text('刚才突然疼得特别厉害，从来没这么疼过。')
        self.assertEqual(result['transfer_to'],'URGENT_ASSISTANCE')

    def test_decision_speech_does_not_claim_unreported_persistence(self):
        import test_care_action_timing
        result=self.care.start('我有点头痛。',preclassified=True)
        text=test_care_action_timing.scene.build_care_decision_message(result,showcase=True)
        self.assertIn('头痛',text)
        self.assertNotIn('持续',text)
        self.assertNotIn('反复',text)
        self.assertNotIn('已记录',text)


if __name__=='__main__':unittest.main()
