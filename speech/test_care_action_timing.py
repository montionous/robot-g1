"""Care invite timing without SDK writes, ASR/TTS, sleeping or DB access."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parent
SCENE=ROOT/'scenarios/care_consultation_support'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(SCENE))
spec=importlib.util.spec_from_file_location('care_timing_scene',SCENE/'g1_voice_demo.py')
scene=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene)


class CareActionTimingTests(unittest.TestCase):
    def run_fake_scene(self,status='started',transfer=None,first_reply='您先别着急，我会陪着您。',second_reply='我会认真听您说。',memory=None):
        events=[]
        first={'reply':first_reply,'state':'CONSULTING','round_no':1}
        if transfer:first['transfer_to']=transfer
        consultation=Mock(round_no=1)
        consultation.start.return_value=first
        consultation.handle_user_text.side_effect=[
            {'reply':second_reply,'state':'CONSULTING','round_no':2},
            {'reply':'结束回复','state':'ENDED','end_reason':'user_requested','round_no':3},
        ]
        def action(_actions,name,**_):
            events.append(('action',name))
            return {'status':status}
        def speak(_speech,text,**_):events.append(('speak',text))
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for target in ('subprocess.Popen','requests.sessions.Session.request','sqlite3.connect'):
                stack.enter_context(patch(target,side_effect=AssertionError('offline test attempted '+target)))
            values={
                'get_elderly':{'name':'离线测试'},'create_session':123,
                'SpeechClient':Mock(),'RobotLedClient':Mock(),'RobotActionClient':Mock(),
                'CareConsultation':consultation,'is_care_trigger':True,
                'save_user_message':None,'save_assistant_message':None,'update_session_context':None,
                'finalize_care_session':{},'build_memory_announcement':memory or {},
                'build_showcase_profile_announcement':{},'announce_decision':None,
            }
            for name,value in values.items():
                stack.enter_context(patch.object(scene,name,return_value=value))
            stack.enter_context(patch.object(scene,'listen',side_effect=['胳膊酸','持续三天','先这样吧']))
            stack.enter_context(patch.object(scene,'trigger_robot_action',side_effect=action))
            stack.enter_context(patch.object(scene,'speak',side_effect=speak))
            stack.enter_context(patch.object(scene.time,'sleep',side_effect=lambda seconds:events.append(('wait',seconds))))
            scene.run_scene(elderly_id=1,max_rounds=20,dialect='mandarin',listen_seconds=6,
                announce_decisions=False,showcase=True,robot_actions='execute',confirm_g1_actions=True,
                robot_leds='off')
        return events

    def test_first_invite_starts_before_reply_with_one_lead(self):
        events=self.run_fake_scene()
        index=events.index(('action','acknowledge'))
        self.assertEqual(events[index:index+3],[('action','acknowledge'),('wait',1.5),('speak','您先别着急，我会陪着您。')])
        self.assertEqual(events.count(('action','acknowledge')),1)
        self.assertEqual(events.count(('wait',1.5)),1)
        self.assertIn(('speak','我会认真听您说。'),events)
        self.assertEqual(events[-1],('action','goodbye'))

    def test_routine_questions_and_advice_do_not_raise_arm(self):
        for reply in ('请问这种疼痛持续多久了？', '好的，请先坐下休息。',
                      '请告诉工作人员“我会陪着您”。', '您是不是担心没人陪着您？'):
            with self.subTest(reply=reply):
                events=self.run_fake_scene(first_reply=reply,second_reply=reply)
                self.assertNotIn(('action','acknowledge'),events)
                self.assertFalse(any(kind=='wait' for kind,_ in events))

    def test_later_supportive_reply_can_trigger_first_invite(self):
        events=self.run_fake_scene(first_reply='请问这种疼痛持续多久了？')
        index=events.index(('action','acknowledge'))
        self.assertEqual(events[index:index+3],[('action','acknowledge'),('wait',1.5),('speak','我会认真听您说。')])
        self.assertLess(events.index(('speak','请问这种疼痛持续多久了？')),index)

    def test_end_reply_does_not_trigger_invite(self):
        self.assertFalse(scene.should_acknowledge_care_reply({
            'reply':'我会陪着您。','state':'ENDED'}))

    def test_demo_disclaimer_never_reaches_speech(self):
        from care_memory_announcement import build_memory_announcement
        announcement=build_memory_announcement({'memory':{
            'preview':True,'should_store':True,'stored':False,
            'summary':'老人本次提到膝盖酸。','memory_key':'mobility'}},showcase=True)
        self.assertIn('不会写入正式护理档案',announcement['console_text'])
        self.assertNotIn('演示模式',announcement['text'])
        self.assertNotIn('不会写入',announcement['text'])
        events=self.run_fake_scene(memory=announcement)
        spoken=[value for kind,value in events if kind=='speak']
        self.assertIn(announcement['text'],spoken)
        self.assertFalse(any('演示模式' in value or '不会写入' in value for value in spoken))

    def test_simulated_follow_up_disclaimer_is_console_only(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            text=scene.build_care_decision_message({
                'risk_level':'needs_staff','new_staff_follow_up':True,
                'staff_follow_up_simulated':True},showcase=True)
        self.assertIn('工作人员',text)
        self.assertNotIn('演示模式',text)
        self.assertNotIn('模拟生成',text)
        self.assertIn('演示模式',output.getvalue())

    def test_inactive_or_failed_invite_adds_no_delay(self):
        for status in ('off','dry_run','busy','confirmation_required','failed'):
            with self.subTest(status=status):
                events=self.run_fake_scene(status)
                self.assertFalse(any(kind=='wait' for kind,_ in events))

    def test_transfer_does_not_trigger_invite_or_wait(self):
        events=self.run_fake_scene(transfer='CONTACT_FAMILY')
        self.assertFalse(any(kind in ('action','wait') for kind,_ in events))


if __name__=='__main__':unittest.main()
